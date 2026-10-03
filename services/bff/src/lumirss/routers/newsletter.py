"""Newsletter issues — 外发简报发送账本（R19 已发送内容页）.

外发简报（digest 邮件）与「外部邮件订阅收件箱」（bridge 列表）是两件
事：本路由只暴露前者——``deliver_digest`` 的逐次发送账本（见
newsletter_issues.py）。已发送行回看正文快照（渲染边界在 Web 端：
DOMPurify）；失败行支持重试，重试只投递账目中尚未成功的收件人。

draft / scheduled 过滤值被接受但诚实返回空列表：outbound digest 没有
草稿机制，计划发送是 digest 设置（/api/v1/digest/settings）而非期号
记录——本路由不伪造这两种形态。

收件人地址对非管理员（role ∉ {owner, admin}）脱敏（本地部分首字符 +
***）；地址明文永不进入日志。
"""


from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lumirss.deps import StrictId
from lumirss.mail_digest import (
    DigestEmpty,
    SmtpNotConfigured,
    retry_digest_issue,
)
from lumirss.newsletter_issues import NewsletterIssueStore, parse_recipients

from .mail import _digest_store, _no_digest_items_response

router = APIRouter()

# 与任务口径一致：账本只持久化 sent / failed 两种形态。
_LEDGER_STATUSES = ("sent", "failed")
_FILTER_STATUSES = ("sent", "draft", "scheduled", "failed")
_ADMIN_ROLES = ("owner", "admin")


class NewsletterIssueRecipient(BaseModel):
    """逐收件人账目（非管理员 address 为脱敏形态）。"""

    address: str
    status: str
    error: str | None = None
    sentAt: str | None = None


class NewsletterIssueSummary(BaseModel):
    """列表行：主题 / 时间 / 状态 / 来源 / 收件人数。"""

    id: int
    subject: str
    status: str
    source: str
    origin: str
    itemCount: int
    recipientCount: int
    error: str | None = None
    createdAt: str
    sentAt: str | None = None


class NewsletterIssueList(BaseModel):
    items: list[NewsletterIssueSummary]


class NewsletterIssueDetail(NewsletterIssueSummary):
    """详情：正文快照仅在存在时给出（历史/失败行诚实 bodyAvailable=false）。"""

    bodyAvailable: bool
    text: str | None = None
    html: str | None = None
    dedupeKey: str
    providerReceipt: str
    recipients: list[NewsletterIssueRecipient]


class NewsletterRetryResult(BaseModel):
    issueId: int
    status: str
    sentCount: int
    skippedCount: int


def _issue_store(request: Request) -> NewsletterIssueStore:
    return NewsletterIssueStore(request.app.state.db)


def _principal_role(request: Request) -> str:
    principal = request.scope.get("lumi_principal")
    return str((principal or {}).get("role") or "")


def _mask_email(address: str) -> str:
    """a***@domain —— 本地部分只保留首字符；无 @ 的畸形输入整体遮蔽。"""
    local, sep, domain = address.partition("@")
    if not sep:
        return "***"
    head = local[:1] if local else ""
    return f"{head}***@{domain}"


def _recipient_views(
    recipients: list[dict], admin: bool
) -> list[NewsletterIssueRecipient]:
    views: list[NewsletterIssueRecipient] = []
    for entry in recipients:
        address = str(entry.get("address") or "")
        sent_at = entry.get("sentAt")
        error = str(entry.get("error") or "")
        views.append(
            NewsletterIssueRecipient(
                address=address if admin else _mask_email(address),
                status=str(entry.get("status") or ""),
                error=error or None,
                sentAt=str(sent_at) if sent_at else None,
            )
        )
    return views


def _summary(row: dict) -> NewsletterIssueSummary:
    sent_at = row.get("sent_at")
    error = row.get("error")
    return NewsletterIssueSummary(
        id=int(row["id"]),
        subject=str(row["subject"] or ""),
        status=str(row["status"] or ""),
        source=str(row["source"] or ""),
        origin=str(row["origin"] or "manual"),
        itemCount=int(row.get("item_count") or 0),
        recipientCount=int(row.get("recipient_count") or 0),
        error=str(error) if error else None,
        createdAt=str(row["created_at"] or ""),
        sentAt=str(sent_at) if sent_at else None,
    )


@router.get("/api/v1/newsletter/issues", response_model=NewsletterIssueList)
async def list_newsletter_issues(request: Request, status: str = "sent") -> Response:
    """按状态过滤的发送账本（新→旧，有界 ≤50）。

    draft / scheduled 当前没有持久化形态（无草稿机制；计划发送是
    digest 设置而非期号）→ 诚实空列表，不伪造记录。"""
    if status not in _FILTER_STATUSES:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_status",
                    "message": "status 需为 sent / draft / scheduled / failed。",
                }
            },
        )
    if status not in _LEDGER_STATUSES:
        return NewsletterIssueList(items=[])
    rows = await _issue_store(request).list_issues(status)
    return NewsletterIssueList(items=[_summary(row) for row in rows])


@router.get("/api/v1/newsletter/issues/{issue_id}", response_model=NewsletterIssueDetail)
async def get_newsletter_issue(issue_id: StrictId, request: Request) -> Response:
    row = await _issue_store(request).get_issue(int(issue_id))
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "not_found", "message": "简报记录不存在。"}
            },
        )
    admin = _principal_role(request) in _ADMIN_ROLES
    text = row.get("body_text")
    html = row.get("body_html")
    body_available = text is not None or html is not None
    summary = _summary(row)
    return NewsletterIssueDetail(
        **summary.model_dump(),
        bodyAvailable=body_available,
        text=str(text) if body_available and text is not None else None,
        html=str(html) if body_available and html is not None else None,
        dedupeKey=str(row.get("dedupe_key") or ""),
        providerReceipt=str(row.get("provider_receipt") or ""),
        recipients=_recipient_views(
            parse_recipients(row.get("recipients_json")), admin
        ),
    )


@router.post(
    "/api/v1/newsletter/issues/{issue_id}/retry",
    response_model=NewsletterRetryResult,
)
async def retry_newsletter_issue(issue_id: StrictId, request: Request) -> Response:
    """重试一次失败的发送：只投递账目中尚未成功的收件人。

    已 sent 的收件人绝不重发（逐收件人账目 + 地址合并，见
    mail_digest.retry_digest_issue）；账目显示全部已送达时不触碰
    SMTP，直接把该行修复为 sent。SMTP 未配置 → 稳定 503。"""
    store = _issue_store(request)
    row = await store.get_issue(int(issue_id))
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "not_found", "message": "简报记录不存在。"}
            },
        )
    if str(row["status"] or "") != "failed":
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "not_retryable",
                    "message": "只有失败的发送可以重试。",
                }
            },
        )
    settings = await _digest_store(request).load()
    if not settings["smtpHost"] or not settings["toAddr"]:
        raise SmtpNotConfigured("SMTP 未配置完成（服务器或收件地址缺失）。")
    try:
        result = await retry_digest_issue(
            request.app.state.db,
            request.app.state.secrets_store,
            settings,
            row,
        )
    except DigestEmpty:
        return _no_digest_items_response()
    return NewsletterRetryResult(
        issueId=int(result["issueId"]),
        status=str(result["status"]),
        sentCount=int(result.get("sentCount") or 0),
        skippedCount=int(result.get("skippedCount") or 0),
    )
