"""Opml routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request, Response

from lumirss.deps import _get_control_adapter
from lumirss.models import (
    OpmlImportPreview,
    OpmlImportResult,
)
from lumirss.opml import (
    MAX_OPML_BYTES,
    OpmlService,
    OpmlTooLarge,
)

router = APIRouter()


async def _read_bounded_opml(request: Request) -> bytes:
    """Read the raw OPML upload with a hard size cap (never buffers more
    than MAX_OPML_BYTES + one chunk before rejecting)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_OPML_BYTES:
            raise OpmlTooLarge("OPML file exceeds the 2 MiB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/api/v1/opml/export")
async def opml_export(request: Request) -> Response:
    """Download the FreshRSS OPML export (subscriptions + categories only).

    Proxied through the BFF so the browser never learns FreshRSS
    credentials. The document contains no settings dump, no API keys, no
    read history and no favorites — only the subscription outline tree
    FreshRSS itself produces.
    """
    control = _get_control_adapter(request)
    xml = await control.export_opml()
    return Response(
        content=xml,
        media_type="text/x-opml; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="LumiRSS-subscriptions.opml"'
        },
    )


@router.post("/api/v1/opml/import/preview", response_model=OpmlImportPreview)
async def opml_import_preview(request: Request) -> dict[str, object]:
    """Parse an uploaded OPML and report what an import WOULD do.

    Strictly non-mutating: bounded read → defusedxml parse → counts
    (new / duplicates / invalid / per-category). Duplicates are only the
    reliably detectable kind: exact feed-URL matches against the current
    FreshRSS subscriptions (plus repeats inside the file). Importing is
    POST /api/v1/opml/import.
    """
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request))
    return await service.preview(data)


@router.post(
    "/api/v1/opml/import",
    response_model=OpmlImportResult,
    response_model_exclude_none=False,  # uncategorized added feed → null label
)
async def opml_import(request: Request) -> dict[str, object]:
    """Merge-import an OPML: subscribe each NEW feed, categorize it, report.

    Merge-only — existing subscriptions are reported as duplicates and
    never modified, nothing is unsubscribed or overwritten (destructive
    restore is out of 0013 scope). Per-feed failures (rejected feeds,
    upstream timeouts) are reported honestly in the result; the file is
    re-parsed and the subscription list re-read at import time, so the
    preview is advisory, never a stale contract.
    """
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request))
    return await service.import_opml(data)


