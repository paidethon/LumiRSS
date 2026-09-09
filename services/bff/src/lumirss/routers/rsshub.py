"""Rsshub routes (moved verbatim from main.py)."""


import asyncio
from typing import Literal

import httpx
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.config import LumiSettings
from lumirss.deps import (
    _get_rsshub_control_store,
    _get_rsshub_credentials_store,
    _get_rsshub_service,
    _preview_json,
)
from lumirss.models import (
    FeedPreviewResult,
    RssHubCatalog,
    RssHubConfigView,
)
from lumirss.routers.ai_settings import SecretValuePut
from lumirss.rsshub import (
    RssHubNotConfigured,
)
from lumirss.rsshub_control import (
    RssHubInvalidValue,
    config_view,
)

router = APIRouter()


class RssHubPreviewRequest(BaseModel):
    """POST /api/v1/rsshub/preview body (0014): route + parameter values."""

    routeId: str = Field(min_length=1)
    params: dict[str, str] = Field(default_factory=dict)


@router.get("/api/v1/rsshub/routes", response_model=RssHubCatalog)
async def rsshub_routes(request: Request) -> dict[str, object]:
    """Lumi-owned RSSHub route catalog (static, always available).

    ``configured`` reports whether the server has an RSSHUB_BASE_URL —
    the catalog itself is independent of the instance. Route descriptors
    carry enough metadata for the Web to render parameter forms; path
    construction happens server-side on preview.
    """
    service = _get_rsshub_service(request)
    try:
        service.load_settings()
        configured = True
    except RssHubNotConfigured:
        configured = False
    return {
        "configured": configured,
        "routes": [
            {
                "id": route.id,
                "title": route.title,
                "description": route.description,
                "pathTemplate": route.path_template,
                "parameters": [
                    {
                        "key": parameter.key,
                        "label": parameter.label,
                        "required": parameter.required,
                        "pattern": parameter.pattern,
                        "example": parameter.example,
                        "help": parameter.help,
                    }
                    for parameter in route.parameters
                ],
            }
            for route in service.list_routes()
        ],
    }


@router.post(
    "/api/v1/rsshub/preview",
    response_model=FeedPreviewResult,
    response_model_exclude_none=False,
)
async def rsshub_preview(
    body: RssHubPreviewRequest, request: Request
) -> dict[str, object]:
    """Preview one configured RSSHub route — NON-MUTATING.

    Constructs the path server-side (validated + encoded parameters),
    fetches the generated feed from the server-configured RSSHub
    instance, parses offline and reads the subscription list for
    alreadySubscribed. The returned feedUrl is the FreshRSS-facing
    subscription URL; subscribing is POST /api/v1/subscriptions (0013).
    """
    service = _get_rsshub_service(request)
    preview = await service.preview(body.routeId, body.params)
    return _preview_json(preview)


async def _probe_rsshub(client: httpx.AsyncClient, url: str, source: str) -> dict[str, object]:
    """One bounded /healthz probe (2s timeout, honest latency or failure)."""
    import time as _time

    started = _time.monotonic()
    try:
        response = await client.get(f"{url}/healthz", timeout=2.0)
        reachable = response.status_code == 200
    except Exception:
        reachable = False
    latency = int((_time.monotonic() - started) * 1000)
    return {
        "url": url,
        "source": source,
        "reachable": reachable,
        "latencyMs": latency if reachable else None,
    }


def _rsshub_runtime_configured() -> bool:
    from pydantic import ValidationError as _ValidationError

    from lumirss.config import RssHubSettings

    try:
        return bool(RssHubSettings().RSSHUB_BASE_URL)
    except _ValidationError:
        return False


class RssHubConfigPatch(BaseModel):
    """PATCH /api/v1/rsshub/config body: allow-listed non-secret values."""

    values: dict[str, object] = Field(default_factory=dict)


async def _rsshub_config_view_async(request: Request) -> dict[str, object]:
    store = _get_rsshub_control_store(request)
    desired = await store.desired()
    flags = await store.restart_required_flags()
    return {
        "schemaVersion": 1,
        "configured": _rsshub_runtime_configured(),
        "pendingCount": flags["count"],
        "pendingSecrets": flags["pendingSecrets"],
        "groups": config_view(store, desired, flags),
    }


@router.get(
    "/api/v1/rsshub/config",
    response_model=RssHubConfigView,
    # Historical wire format: secret items carry "configured" (no "value"),
    # non-secret items carry "value" (no "configured"), "options" is always
    # present (null for non-enum items) — exclude_unset reproduces exactly that.
    response_model_exclude_none=False,
    response_model_exclude_unset=True,
)
async def get_rsshub_config(request: Request) -> dict[str, object]:
    return await _rsshub_config_view_async(request)


@router.patch(
    "/api/v1/rsshub/config",
    response_model=RssHubConfigView,
    response_model_exclude_none=False,
    response_model_exclude_unset=True,
)
async def patch_rsshub_config(
    body: RssHubConfigPatch, request: Request
) -> dict[str, object]:
    """Update allow-listed non-secret desired values (validated + typed).

    Secrets are never accepted here — use the secret endpoints. Saving only
    updates the DESIRED config; the UI reports restartRequired honestly.
    """
    store = _get_rsshub_control_store(request)
    await store.patch_desired({k: v for k, v in body.values.items()})
    return await _rsshub_config_view_async(request)


@router.get("/api/v1/rsshub/config/export")
async def export_rsshub_config(request: Request) -> Response:
    """Render the desired config as an env fragment (secrets never echoed)."""
    from lumirss.rsshub_control import export_env

    store = _get_rsshub_control_store(request)
    desired = await store.desired()
    return Response(
        content=export_env(store, desired),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rsshub.env"'},
    )


# ---- Gate: auto-detect, custom credentials, server-side env file ----


class RssHubDetectCandidate(BaseModel):
    url: str
    source: str
    reachable: bool
    latencyMs: int | None = None


class RssHubDetectResult(BaseModel):
    """GET /api/v1/rsshub/detect — bounded candidate probing."""

    configured: bool
    candidates: list[RssHubDetectCandidate] = []


@router.get("/api/v1/rsshub/detect", response_model=RssHubDetectResult)
async def detect_rsshub(request: Request) -> dict[str, object]:
    """Auto-identify the RSSHub instance within BOUNDED candidates only:
    the configured URL, this project's compose DNS name, and the host
    loopback. Never a LAN scan; never any authenticated read-back."""
    from lumirss.config import RssHubSettings

    configured = RssHubSettings().RSSHUB_BASE_URL
    candidates: list[dict[str, object]] = []
    probes: list[tuple[str, str]] = []
    if configured:
        probes.append((configured, "configured"))
    probes.append(("http://rsshub:1200", "compose-dns"))
    probes.append(("http://127.0.0.1:1200", "host-loopback"))
    client = request.app.state.http_client
    results = await asyncio.gather(
        *(_probe_rsshub(client, url, source) for url, source in probes),
        return_exceptions=True,
    )
    for item in results:
        if isinstance(item, BaseException):
            continue
        candidates.append(item)  # type: ignore[arg-type]
    return {"configured": bool(configured), "candidates": candidates}


class RssHubCredentialCreate(BaseModel):
    """POST /api/v1/rsshub/credentials body (value is write-only)."""

    name: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=253)
    envKey: str = Field(min_length=1, max_length=64)
    kind: Literal["cookie", "token", "api_key", "bearer", "other"]
    value: str = Field(min_length=1, max_length=10000)
    route: str = Field(default="", max_length=200)


class RssHubCredentialValuePut(BaseModel):
    """PUT /api/v1/rsshub/credentials/{id}/value body."""

    value: str = Field(min_length=1, max_length=10000)


@router.get("/api/v1/rsshub/credentials", response_model=list[dict[str, object]])
async def list_rsshub_credentials(request: Request) -> list[dict[str, object]]:
    """Custom site/route credentials (values are write-only; configured
    flags only). Adding one NEVER fabricates an RSSHub route."""
    return await _get_rsshub_credentials_store(request).list_entries()


@router.post("/api/v1/rsshub/credentials", response_model=dict[str, object], status_code=201)
async def create_rsshub_credential(
    body: RssHubCredentialCreate, request: Request
) -> dict[str, object]:
    return await _get_rsshub_credentials_store(request).create(
        name=body.name,
        domain=body.domain,
        env_key=body.envKey,
        kind=body.kind,
        value=body.value,
        route=body.route,
    )


class RssHubCredentialMetadataPatch(BaseModel):
    """PATCH /api/v1/rsshub/credentials/{id} body (metadata only)."""

    name: str | None = None
    route: str | None = None


@router.patch("/api/v1/rsshub/credentials/{credential_id}", response_model=dict[str, object])
async def patch_rsshub_credential(
    credential_id: str, body: RssHubCredentialMetadataPatch, request: Request
) -> dict[str, object]:
    return await _get_rsshub_credentials_store(request).update_metadata(
        credential_id,
        name=body.name,
        route=body.route,
    )


@router.put("/api/v1/rsshub/credentials/{credential_id}/value", status_code=204)
async def put_rsshub_credential_value(
    credential_id: str, body: RssHubCredentialValuePut, request: Request
) -> Response:
    if not body.value.strip():
        raise RssHubInvalidValue("value must not be blank.")
    await _get_rsshub_credentials_store(request).set_value(credential_id, body.value)
    return Response(status_code=204)


@router.delete("/api/v1/rsshub/credentials/{credential_id}", status_code=204)
async def delete_rsshub_credential(credential_id: str, request: Request) -> Response:
    await _get_rsshub_credentials_store(request).delete(credential_id)
    return Response(status_code=204)


@router.post("/api/v1/rsshub/config/env-file")
async def materialize_rsshub_env_file(request: Request) -> dict[str, object]:
    """Write the FULL env file (secret values included) server-side to a
    0600 file under the BFF data dir for apply_rsshub_config.py. The file
    content never passes through the browser; the response carries only
    counts and the file name."""
    import os as _os

    from lumirss.rsshub_control import render_env_file

    store = _get_rsshub_control_store(request)
    credentials = _get_rsshub_credentials_store(request)
    desired = await store.desired()
    custom_values = await credentials.collect_values()
    content = render_env_file(store, desired, custom_values)
    settings = LumiSettings()
    target_dir = settings.data_dir / "rsshub"
    # 0700 目录 + 建文件即 0600：secrets 不经默认权限暴露出窗口期
    target_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    _os.chmod(target_dir, 0o700)
    target = target_dir / "rsshub.env"
    tmp = target_dir / ".rsshub.env.tmp"
    fd = _os.open(tmp, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
    with _os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    _os.chmod(tmp, 0o600)
    _os.replace(tmp, target)
    _os.chmod(target, 0o600)
    secret_count = len(store.secret_configured_map()) and sum(
        1 for configured in store.secret_configured_map().values() if configured
    )
    return {
        "fileName": "rsshub.env",
        "dirName": "rsshub",
        "lineCount": len(content.splitlines()),
        "secretCount": secret_count,
        "customCredentialCount": len(custom_values),
        "note": "Written server-side (0600). Apply with apply_rsshub_config.py.",
    }


@router.put("/api/v1/rsshub/config/secrets/{key}", status_code=204)
async def put_rsshub_secret(
    key: str, body: SecretValuePut, request: Request
) -> Response:
    """Write one route credential / secret (write-only, never read back)."""
    store = _get_rsshub_control_store(request)
    await store.set_secret(key, body.value)
    return Response(status_code=204)


@router.delete("/api/v1/rsshub/config/secrets/{key}", status_code=204)
async def delete_rsshub_secret(key: str, request: Request) -> Response:
    """Clear one secret (explicit action)."""
    store = _get_rsshub_control_store(request)
    await store.delete_secret(key)
    return Response(status_code=204)


@router.post("/api/v1/rsshub/config/apply", status_code=204)
async def apply_rsshub_config(request: Request) -> Response:
    """Operator confirms the desired config has been applied after restart."""
    store = _get_rsshub_control_store(request)
    await store.mark_applied()
    return Response(status_code=204)


