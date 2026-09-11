"""Mail bridge + digest routes (phase2 G5).

Bridge: list CRUD (secret shown ONCE at creation), webhook ingest at
/api/mail/ingest/{uuid} (bearer secret, constant-time), per-list Atom at
/feeds/mail/{uuid}.{secret}.atom. Digest: settings (SMTP password
write-only), send-now. The IMAP path reuses the bridge; it is disabled
until credentials are configured.
"""


from fastapi import APIRouter, Request, Response

from lumirss.mail_bridge import (
    MailBridgeInvalid,
    MailBridgeNotFound,
    MailBridgeStore,
)
from lumirss.mail_digest import (
    DigestScheduler,
    DigestStore,
    SmtpNotConfigured,
    SmtpSendFailed,
    compose_digest,
    send_digest_smtp,
)
from lumirss.models import (
    DigestSendNowRequest,
    DigestSettings,
    DigestSettingsUpdate,
    MailBridgeList,
    MailBridgeListCreate,
    MailBridgeListCreated,
    MailBridgeListResponse,
    MailIngestResult,
)

from ..deps import _get_mail_bridge_store

router = APIRouter()

_MAX_RAW_BYTES = 10 * 1024 * 1024


def _digest_store(request: Request) -> DigestStore:
    return DigestStore(request.app.state.db, request.app.state.secrets_store)


@router.post(
    "/api/v1/mail/bridge-lists",
    response_model=MailBridgeListCreated,
    status_code=201,
)
async def create_bridge_list(
    payload: MailBridgeListCreate, request: Request
) -> MailBridgeListCreated:
    store: MailBridgeStore = _get_mail_bridge_store(request)
    created = await store.create_list(payload.name)
    return MailBridgeListCreated(
        uuid=created.uuid,
        name=created.name,
        createdAt=created.created_at,
        secret=created.secret,
    )


@router.get("/api/v1/mail/bridge-lists", response_model=MailBridgeListResponse)
async def list_bridge_lists(request: Request) -> MailBridgeListResponse:
    store: MailBridgeStore = _get_mail_bridge_store(request)
    lists = await store.list_lists()
    return MailBridgeListResponse(
        items=[
            MailBridgeList(uuid=lst.uuid, name=lst.name, createdAt=lst.created_at)
            for lst in lists
        ]
    )


@router.delete("/api/v1/mail/bridge-lists/{list_uuid}", status_code=204)
async def delete_bridge_list(list_uuid: str, request: Request) -> Response:
    store: MailBridgeStore = _get_mail_bridge_store(request)
    deleted = await store.delete_list(list_uuid)
    if not deleted:
        raise MailBridgeNotFound(list_uuid)
    return Response(status_code=204)


@router.post(
    "/api/mail/ingest/{list_uuid}",
    response_model=MailIngestResult,
)
async def ingest_mail(list_uuid: str, request: Request) -> MailIngestResult:
    """Authenticated thin bridge: bearer secret + raw MIME body.

    Lives at /api/mail/* (not /api/v1/*): it is machine-to-machine and
    still passes through the same security middlewares by path prefix.
    """
    store: MailBridgeStore = _get_mail_bridge_store(request)
    auth = request.headers.get("authorization", "")
    supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
    target = await store.get_list(list_uuid)
    if target is None or not store.secrets_match(supplied, target):
        raise MailBridgeNotFound(list_uuid)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_RAW_BYTES:
            raise MailBridgeInvalid("Message exceeds the 10MB limit.")
        chunks.append(chunk)
    result = await store.ingest(target, b"".join(chunks))
    return MailIngestResult(
        status=result["status"],
        messageId=str(result.get("messageId", "")),
        subject=result.get("subject"),
        attachments=int(result.get("attachments", 0)),
    )


@router.get("/feeds/mail/{list_uuid}.{secret}.atom")
async def serve_mail_atom(list_uuid: str, secret: str, request: Request) -> Response:
    """Per-list Atom for FreshRSS (constant-time secret check)."""
    import xml.sax.saxutils as _xml

    store: MailBridgeStore = _get_mail_bridge_store(request)
    target = await store.get_list(list_uuid)
    if target is None or not store.secrets_match(secret, target):
        raise MailBridgeNotFound(list_uuid)
    entries = await store.list_entries(list_uuid)
    esc = _xml.escape
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{esc(target.name)}</title>",
        f"  <id>urn:lumirss:mailbridge:{target.uuid}</id>",
        "  <updated>" + esc(entries[0]["received_at"] if entries else "") + "</updated>",
    ]
    for entry in entries:
        lines.append("  <entry>")
        lines.append(
            f"    <id>{esc('urn:lumirss:mailentry:' + str(entry['message_id']))}</id>"
        )
        lines.append(f"    <title>{esc(str(entry['subject']))}</title>")
        note = (
            f"<p>{int(entry['attachment_count'])} 个附件（不保存内容）</p>"
            if entry["attachment_count"]
            else ""
        )
        lines.append(
            f'    <content type="html">{esc(note + str(entry["html"] or ""))}</content>'
        )
        lines.append("  </entry>")
    lines.append("</feed>")
    return Response(
        content="\n".join(lines) + "\n",
        media_type="application/atom+xml; charset=utf-8",
    )


@router.get("/api/v1/digest/settings", response_model=DigestSettings)
async def get_digest_settings(request: Request) -> DigestSettings:
    settings = await _digest_store(request).load()
    return _digest_model(settings)


@router.put("/api/v1/digest/settings", response_model=DigestSettings)
async def update_digest_settings(
    payload: DigestSettingsUpdate, request: Request
) -> DigestSettings:
    store = _digest_store(request)
    settings = await store.save(payload.model_dump(exclude_none=True))
    if payload.smtpPassword is not None:
        await store.set_password(payload.smtpPassword)
        settings = await store.load()
    return _digest_model(settings)


@router.post("/api/v1/digest/send-now", response_model=MailIngestResult)
async def digest_send_now(payload: DigestSendNowRequest, request: Request) -> MailIngestResult:
    """Immediate send with the configured relay (never a test to real
    third parties — tests use local sinks only)."""
    store = _digest_store(request)
    settings = await store.load()
    if not settings["smtpHost"] or not settings["toAddr"]:
        raise SmtpNotConfigured("SMTP 未配置完成（服务器或收件地址缺失）。")
    digest_items = []
    for ref in payload.entryRefs[:20]:
        digest_items.append(
            {"title": ref.get("title", ""), "url": ref.get("url", ""), "source": ref.get("source", "")}
        )
    text, html = compose_digest("LumiRSS 文章摘要", digest_items)
    password = request.app.state.secrets_store.get("digest_smtp_password") or ""
    try:
        send_digest_smtp(
            host=settings["smtpHost"],
            port=settings["smtpPort"],
            user=settings["smtpUser"],
            password=password,
            from_addr=settings["fromAddr"] or settings["smtpUser"],
            to_addr=settings["toAddr"],
            subject="LumiRSS 文章摘要",
            text=text,
            html=html,
        )
    except SmtpSendFailed as exc:
        await store.mark_error(str(exc))
        raise
    await store.mark_sent()
    return MailIngestResult(status="sent", messageId="")


def _digest_model(settings) -> DigestSettings:
    return DigestSettings(
        enabled=settings["enabled"],
        hour=settings["hour"],
        source=settings["source"],
        limitCount=settings["limitCount"],
        smtpHost=settings["smtpHost"],
        smtpPort=settings["smtpPort"],
        smtpUser=settings["smtpUser"],
        fromAddr=settings["fromAddr"],
        toAddr=settings["toAddr"],
        lastSentAt=settings["lastSentAt"],
        lastError=settings["lastError"],
        passwordConfigured=settings.get("passwordConfigured", False),
    )


_ = (DigestScheduler,)  # wired into the shared background loop
