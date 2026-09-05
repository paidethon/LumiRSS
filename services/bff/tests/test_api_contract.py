"""Web↔BFF API contract test (version-skew guard).

The two production HTTP 404s (POST /api/v1/backups, GET /api/v1/rsshub/config)
were caused by a stale BFF process predating those routes while the web
bundle already called them. This test pins the contract INSIDE one
repository/CI run: every /api/v1 path the web client can request must be
registered on the FastAPI app. A future "web calls a route the BFF never
had" regression now fails here instead of surfacing as a browser 404.

(The deployment-skew half — an old BFF image in a running stack — is
covered by GET /api/v1/version + the About page provenance display.)
"""

import re
from pathlib import Path

from lumirss.main import app

WEB_CLIENT = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "web"
    / "src"
    / "api"
    / "client.ts"
)


def _normalize_path(path: str) -> str:
    """Shape-only normalization: /backups/{job_id} and /backups/${jobId}
    both collapse to /backups/{} — parameter NAMES differ per side and
    must not fail the contract; the path SHAPE is the contract."""
    path = path.split("?", 1)[0]
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    return re.sub(r"\{[^}]*\}", "{}", path)


def _registered_api_routes() -> set[str]:
    paths = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/v1"):
            paths.add(_normalize_path(path))
    return paths


def _client_paths() -> set[str]:
    """Every /api/v1 path literal the web client can build."""
    source = WEB_CLIENT.read_text(encoding="utf-8")
    paths: set[str] = set()
    # Template literals: `${API_BASE}/backups/${jobId}` — capture the tail
    # and re-attach the prefix the API_BASE constant carries.
    for match in re.finditer(r"\$\{API_BASE\}(/[^`'\"]*)", source):
        paths.add("/api/v1" + _normalize_path(match.group(1)))
    # Plain literals that already embed the prefix (rare, e.g. helpers).
    for match in re.finditer(r"[\"'](/api/v1/[^\"'?]*)[\"']", source):
        paths.add(_normalize_path(match.group(1)))
    return paths


def test_web_client_paths_exist_on_bff():
    assert WEB_CLIENT.exists(), f"missing {WEB_CLIENT}"
    client_paths = _client_paths()
    # Guard against the extractor silently matching nothing.
    assert len(client_paths) >= 25, sorted(client_paths)
    registered = _registered_api_routes()
    missing = sorted(p for p in client_paths if p not in registered)
    assert not missing, (
        "web client calls routes the BFF does not register "
        f"(stale-BFF 404 class): {missing}"
    )


def test_critical_control_plane_routes_are_registered():
    """The exact routes from the production 404 incident, with methods."""
    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/v1"):
            methods_by_path.setdefault(path, set()).update(
                getattr(route, "methods", set())
            )
    for path, method in (
        ("/api/v1/rsshub/config", "GET"),
        ("/api/v1/rsshub/config", "PATCH"),
        ("/api/v1/backups", "GET"),
        ("/api/v1/backups", "POST"),
        ("/api/v1/backups/{job_id}", "GET"),
        ("/api/v1/backups/webdav", "GET"),
        ("/api/v1/backups/webdav", "PUT"),
        ("/api/v1/backups/webdav/test", "POST"),
        ("/api/v1/backups/remote", "GET"),
        ("/api/v1/restore/preview", "POST"),
        ("/api/v1/restore", "POST"),
        ("/api/v1/settings/ai", "GET"),
        ("/api/v1/settings/ai", "PUT"),
        ("/api/v1/settings/ai/key", "PUT"),
        ("/api/v1/settings/ai/profiles", "GET"),
        ("/api/v1/settings/ai/profiles", "POST"),
        ("/api/v1/settings/ai/profiles/{profile_id}", "PATCH"),
        ("/api/v1/settings/ai/profiles/{profile_id}", "DELETE"),
        ("/api/v1/settings/ai/profiles/{profile_id}/secret", "PUT"),
        ("/api/v1/settings/ai/profiles/{profile_id}/secret", "DELETE"),
        ("/api/v1/settings/ai/purposes", "GET"),
        ("/api/v1/settings/ai/purposes", "PUT"),
        ("/api/v1/version", "GET"),
    ):
        assert path in methods_by_path, f"missing route {path}"
        assert method in methods_by_path[path], (
            f"route {path} missing method {method}"
        )
