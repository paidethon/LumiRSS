"""Catalog ↔ pinned-upstream RSSHub metadata check.

The Lumi catalog (rsshub.CATALOG) hand-curates a small allowlist of
RSSHub routes with Lumi-owned labels/help/validation. The upstream facts
(route paths, parameter names) must stay aligned with the RSSHub image we
pin in docker-compose. This test validates every catalog route against
the vendored upstream snapshot (``rsshub_routes.generated.json``,
extracted from the pinned image by ``scripts/export_rsshub_routes.py``).

A failure here means the RSSHub image pin was bumped (or a catalog entry
edited) and the two no longer agree: re-run the export script and fix the
catalog entry — before shipping, not after a user hits a 404 upstream.
"""

import json
import re
from pathlib import Path

from lumirss.rsshub import CATALOG

SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "lumirss" / "rsshub_routes.generated.json"
)

# Hand-written catalogs stay honest: the snapshot must record the exact
# image the compose files pin.
COMPOSE_PIN_RE = re.compile(r"image:\s*(diygod/rsshub@sha256:[0-9a-f]{64})")


def _compose_pin() -> str | None:
    compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    match = COMPOSE_PIN_RE.search(compose.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _snapshot_routes(namespace: str) -> dict:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    return snapshot["namespaces"].get(namespace, {})


def _is_param(segment: str) -> bool:
    return segment.startswith(":")


def _upstream_regex(upstream_path: str) -> "re.Pattern[str]":
    """Compile an upstream path pattern (":param" segments, optional "?"
    suffixes, e.g. "/:category{.+}?") into a matchable regex."""
    pattern = "^"
    for segment in upstream_path.strip("/").split("/"):
        if not segment:
            continue
        optional = segment.endswith("?")
        core = segment[:-1] if optional else segment
        body = "/[^/]+" if _is_param(segment) else "/" + re.escape(core)
        pattern += f"(?:{body})?" if optional else body
    return re.compile(pattern + "/?$")


def upstream_matches(template_tail: str, upstream_path: str) -> bool:
    """Whether a catalog path tail (namespace stripped, {param} for
    placeholders) matches an upstream path pattern."""
    tail = "/" + template_tail.strip("/")
    return _upstream_regex(upstream_path).fullmatch(tail) is not None


def _find_upstream(route):
    """(upstream_path, route_meta | None) for one catalog route."""
    parts = route.path_template.strip("/").split("/")
    namespace, tail = parts[0], "/".join(parts[1:])
    for upstream_path, meta in _snapshot_routes(namespace).items():
        if upstream_matches(tail, upstream_path):
            return upstream_path, meta
    return None, None


def _placeholders(path_template: str) -> list[str]:
    return re.findall(r"\{(\w+)\}", path_template)


def test_snapshot_is_present_and_pinned():
    assert SNAPSHOT_PATH.exists(), (
        "rsshub_routes.generated.json is missing — run "
        "scripts/export_rsshub_routes.py against the pinned image."
    )
    meta = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["_meta"]
    pin = _compose_pin()
    assert pin is not None, "docker-compose.yml does not pin diygod/rsshub by digest"
    assert meta["rsshubImage"] == pin, (
        "Snapshot was extracted from a different image than the compose pin "
        f"(snapshot: {meta['rsshubImage']}, compose: {pin}) — refresh the snapshot."
    )


def test_every_catalog_route_exists_upstream():
    missing = []
    for route in CATALOG:
        upstream_path, _meta = _find_upstream(route)
        if upstream_path is None:
            missing.append(f"{route.id} ({route.path_template})")
    assert not missing, (
        "Catalog routes with no matching upstream path in the pinned "
        f"snapshot: {', '.join(missing)}"
    )


def test_catalog_parameters_exist_upstream():
    unknown = []
    for route in CATALOG:
        _path, meta = _find_upstream(route)
        if meta is None:
            continue
        upstream_params = set(meta.get("parameters") or {})
        for placeholder in _placeholders(route.path_template):
            if placeholder not in upstream_params:
                unknown.append(f"{route.id}: {{{placeholder}}}")
        for parameter in route.parameters:
            if parameter.required and parameter.key not in upstream_params:
                unknown.append(f"{route.id}: parameter {parameter.key}")
    assert not unknown, (
        "Catalog placeholders/required parameters not documented upstream: "
        f"{', '.join(unknown)}"
    )


def test_snapshot_covers_all_curated_namespaces():
    namespaces = {route.path_template.strip("/").split("/")[0] for route in CATALOG}
    snapshot_namespaces = set(json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["namespaces"])
    assert namespaces <= snapshot_namespaces, (
        f"Snapshot missing curated namespaces: {namespaces - snapshot_namespaces}"
    )
