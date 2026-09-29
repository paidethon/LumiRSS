"""NEW-285 个人简报 RSS 发布路由 — 凭据管理 + 可撤销私有 Atom。

- POST   /api/v1/briefings/feed/enable  → 明文 token 一次性返回
- POST   /api/v1/briefings/feed/rotate  → 旧 token 立即失效
- POST   /api/v1/briefings/feed/revoke  → 撤销（feed 立即 404）
- GET    /api/v1/briefings/feed         → 状态（绝不含 token）
- GET    /feeds/briefings/{token}.atom  → 公开免登录；只有「已确认」
           期次；错 token / 已撤销 / 未启用 → 同一 404（不泄露存在性）。
"""

import hashlib
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.atom_render import AtomEntry, render_feed, rfc3339
from lumirss.machine_auth import index_machine_token, machine_user_context
from lumirss.new281_briefings import BriefingStore, provenance_label
from lumirss.new285_feed import BriefingFeedStore, FeedTokenStateConflict
from lumirss.new290_corrections import CorrectionStore

router = APIRouter()

_MAX_FEED_ISSUES = 50
_NOT_FOUND = Response(
    status_code=404,
    media_type="application/xml",
    content="<error>not found</error>",
)


def _stable_issue_guid(issue_id: str) -> str:
    return "urn:lumi:briefing:" + hashlib.sha256(
        issue_id.encode("utf-8")
    ).hexdigest()[:32]


@router.post("/api/v1/briefings/feed/enable")
async def enable_feed(request: Request) -> Response:
    try:
        created = await BriefingFeedStore(request.app.state.db).enable()
    except FeedTokenStateConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "feed_state_conflict", "message": str(exc)}},
        )
    # 归属索引：公开路由经 token_owner_index 解析作用域（0067 同机制）。
    await index_machine_token(request, created["token"], "briefing_feed")
    return JSONResponse(
        {
            "token": created["token"],
            "path": created["path"],
            "note": "token 只显示这一次（库存哈希）。撤销后所有订阅者立即 404。",
        }
    )


@router.post("/api/v1/briefings/feed/rotate")
async def rotate_feed(request: Request) -> Response:
    try:
        rotated = await BriefingFeedStore(request.app.state.db).rotate()
    except FeedTokenStateConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "feed_state_conflict", "message": str(exc)}},
        )
    await index_machine_token(request, rotated["token"], "briefing_feed")
    return JSONResponse(
        {
            "token": rotated["token"],
            "path": rotated["path"],
            "note": "旧 token 已立即失效；新 token 只显示这一次。",
        }
    )


@router.post("/api/v1/briefings/feed/revoke")
async def revoke_feed(request: Request) -> Response:
    revoked = await BriefingFeedStore(request.app.state.db).revoke()
    if not revoked:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "feed_not_found", "message": "feed 未启用。"}},
        )
    return Response(status_code=204)


@router.get("/api/v1/briefings/feed")
async def feed_state(request: Request) -> Response:
    state = await BriefingFeedStore(request.app.state.db).get_state()
    return JSONResponse(
        {
            "enabled": bool(state and state["enabled"]),
            "createdAt": state["createdAt"] if state else None,
            "rotatedAt": state["rotatedAt"] if state else None,
            "revokedAt": state["revokedAt"] if state else None,
            "honestyNote": (
                "凭据只存哈希，此处永远不含 token；feed 只含已确认期次的"
                "摘要卡与更正提示，不含任何私人笔记。"
            ),
        }
    )


@router.get("/feeds/briefings/{token}.atom")
async def briefing_atom(token: str, request: Request) -> Response:
    """私有 Atom 订阅（公开免登录；token 即凭据）。"""
    async with machine_user_context(request, token) as uid:
        if uid is None:
            return _NOT_FOUND
        store = BriefingFeedStore(request.app.state.db)
        if not await store.verify(token):
            return _NOT_FOUND
        # NEW-341：共享入口对本人数据的成功读取留痕（尽力而为）。
        from lumirss.new341_access_log import record_access_event

        await record_access_event(request.app.state.db, "briefing_feed", "个人简报 Atom")
        issues = await BriefingStore(request.app.state.db).list_issues(limit=200)
        confirmed = [
            i for i in issues if i["status"] == "confirmed"
        ][:_MAX_FEED_ISSUES]
        from lumirss.util import utc_now

        generated_at = rfc3339(utc_now()) or utc_now()
        entries: list[AtomEntry] = []
        for summary in confirmed:
            issue = await BriefingStore(request.app.state.db).get_issue(
                summary["id"]
            )
            corrections = await CorrectionStore(
                request.app.state.db
            ).list_corrections(issue["id"])
            entries.append(_issue_entry(issue, corrections, generated_at))
        if not entries:
            entries.append(
                AtomEntry(
                    entry_id="urn:lumi:briefing:none",
                    title="（还没有已确认的简报期次）",
                    updated=generated_at,
                    content_html="<p>确认一期简报后会出现在这里。</p>",
                )
            )
        atom = render_feed(
            feed_id="urn:lumi:briefing-feed",
            title="LumiRSS 个人简报（私有订阅）",
            updated=generated_at,
            self_href=str(request.url),
            entries=entries,
            feed_author="LumiRSS",
        )
        return Response(
            content=atom, media_type="application/atom+xml; charset=utf-8"
        )


def _issue_entry(
    issue: dict[str, Any], corrections: list[dict[str, Any]], fallback: str
) -> AtomEntry:
    html_parts = [f"<h2>{issue['title']}</h2>"]
    for section in issue.get("sections") or []:
        key = str(section.get("key"))
        in_section = [
            i for i in issue.get("items") or [] if i.get("sectionKey") == key
        ]
        if not in_section:
            continue
        html_parts.append(f"<h3>{section.get('label') or key}</h3><ul>")
        for item in in_section:
            marker = provenance_label(str(item.get("provenance") or "manual"))
            link = f' <a href="{item["url"]}">原文</a>' if item.get("url") else ""
            html_parts.append(
                f"<li>【{marker}】{item.get('title')}{link}<br>"
                f"<small>{item.get('feedTitle')}</small></li>"
            )
        html_parts.append("</ul>")
    for correction in corrections:
        html_parts.append(
            f"<p><strong>更正 {correction['createdAt']}</strong>："
            f"{correction['body']}</p>"
        )
    if corrections:
        html_parts.append("<p>以上更正为追加记录，原期次未做静默替换。</p>")
    updated = rfc3339(str(issue.get("confirmedAt") or "")) or fallback
    return AtomEntry(
        entry_id=_stable_issue_guid(str(issue["id"])),
        title=str(issue["title"]),
        updated=updated,
        content_html="".join(html_parts),
        published=rfc3339(str(issue.get("confirmedAt") or "")) or None,
    )
