"""N181 逐来源数据外发清单 — 从「当前真实配置」推导的数据外发说明。

只读聚合，每个能力一条：configured 取自当前用户库 / 秘密库的真实配置
（AI 摘要/翻译/对话 → ai.base_url；LibreTranslate → translation 引擎与
URL；WebDAV → backup.webdav；IMAP → secrets 里的 mail_imap；远程图片 →
便携设置 readerImageMode；TTS → 本机语音合成，恒为本机）。

- providerHost 只含主机名：绝不返回路径、用户名、端口语义之外的任何
  信息，更不含密钥值（负向测试覆盖）；
- 未配置的能力如实返回 configured=false —— Web 端显示「不发送」；
- 本端点不做任何网络请求，只读本地配置。
"""

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.models import DataFlowItem, DataFlowsResponse

router = APIRouter()


def _hostname_of(url: str) -> str | None:
    """URL → 主机名（小写、去端口/路径/凭据）；解析失败 → None。"""
    raw = (url or "").strip()
    if not raw:
        return None
    if "//" not in raw:
        raw = f"//{raw}"
    try:
        host = urlparse(raw).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _configured_flow(
    capability: str, host: str | None, categories: list[str]
) -> DataFlowItem:
    return DataFlowItem(
        capability=capability,
        configured=True,
        providerHost=host,
        dataCategories=categories,
        local=False,
    )


def _unconfigured_flow(capability: str) -> DataFlowItem:
    return DataFlowItem(capability=capability, configured=False)


async def _ai_settings(db: Any) -> dict[str, str]:
    from lumirss.ai_settings import AiSettingsStore

    try:
        return await AiSettingsStore(db).load()
    except Exception:  # noqa: BLE001 — 配置读不到 = 未配置，绝不 500
        return {}


async def _portable_settings(db: Any) -> dict[str, Any]:
    from lumirss.app_settings import AppSettingsStore

    try:
        document, _stored = await AppSettingsStore(db).load()
        return document.model_dump()
    except Exception:  # noqa: BLE001 — 读不到按默认口径（all）处理
        return {}


def build_data_flows(
    ai: dict[str, str],
    portable: dict[str, Any],
    webdav_doc: dict[str, Any],
    webdav_ready: bool,
    imap_config: Any,
) -> list[DataFlowItem]:
    """纯函数组装（可独立测试）：输入全部来自当前请求者的真实配置。"""
    ai_host = _hostname_of(ai.get("ai.base_url", ""))
    ai_ready = bool(ai_host) and bool(ai.get("ai.model", "").strip())
    engine = ai.get("translation.engine", "ai")
    libretranslate_host = _hostname_of(ai.get("translation.libretranslate_url", ""))

    reader_image_mode = portable.get("readerImageMode", "all")
    webdav_host = _hostname_of(str(webdav_doc.get("serverUrl", "")))
    imap_host = _hostname_of(str(getattr(imap_config, "host", "") or ""))

    flows = [
        # 云端 AI（摘要 / 翻译 / 对话共用同一 provider 配置）
        _configured_flow("ai-summary", ai_host, ["条目标题与正文", "语言偏好"])
        if ai_ready
        else _unconfigured_flow("ai-summary"),
        _configured_flow("ai-translation", ai_host, ["待翻译文本"])
        if ai_ready and engine == "ai"
        else _unconfigured_flow("ai-translation"),
        _configured_flow("ai-chat", ai_host, ["对话消息", "引用的条目内容"])
        if ai_ready
        else _unconfigured_flow("ai-chat"),
        # LibreTranslate（自建 MT，经 BFF 调用）
        _configured_flow("libretranslate", libretranslate_host, ["待翻译文本"])
        if engine == "libretranslate" and libretranslate_host
        else _unconfigured_flow("libretranslate"),
        # TTS：浏览器本机语音合成——文本不出设备
        DataFlowItem(
            capability="tts",
            configured=True,
            providerHost=None,
            dataCategories=["当前朗读文本（仅在本机合成语音）"],
            local=True,
        ),
        # 远程图片：图片显示关闭时不产生任何对外请求
        _configured_flow(
            "remote-images",
            None,
            ["远程图片请求（图片来源站可见你的 IP 与 User-Agent）"],
        )
        if reader_image_mode != "hidden"
        else _unconfigured_flow("remote-images"),
        # WebDAV 备份目标
        _configured_flow("webdav", webdav_host, ["完整备份包（不含秘密值）"])
        if webdav_ready and webdav_host
        else _unconfigured_flow("webdav"),
        # IMAP 邮件简报收信
        _configured_flow("imap", imap_host, ["收件箱邮件内容"])
        if imap_config is not None and imap_host
        else _unconfigured_flow("imap"),
    ]
    return flows


@router.get("/api/v1/privacy/data-flows", response_model=DataFlowsResponse)
async def get_data_flows(request: Request) -> DataFlowsResponse:
    """N181：逐来源数据外发清单（来自真实配置，只读，无网络请求）。"""
    from lumirss.backup import WebDavSettingsStore
    from lumirss.mail_imap import load_imap_config

    db = request.app.state.db
    secrets = request.app.state.secrets_store

    ai = await _ai_settings(db)
    portable = await _portable_settings(db)
    webdav_store = WebDavSettingsStore(db, secrets)
    webdav_doc = await webdav_store.load()
    imap_config = load_imap_config(secrets)
    flows = build_data_flows(
        ai,
        portable,
        webdav_doc,
        webdav_store.configured(webdav_doc),
        imap_config,
    )
    return DataFlowsResponse(flows=flows)


# -- N189 个人活动记录清除 -----------------------------------------------------

_RETAINED_NOTES = [
    "已读/收藏/笔记等业务状态不受影响（它们不是活动记录）",
    "阅读路径不存储在服务端（设备本地，N050 口径）——无服务端记录可清除",
    "语音书签保存在设备本地——本端点触达不到，也不冒充已清除",
]

_ACTIVITY_BUCKETS = ("loginEvents", "aiTaskLogs", "searchSnapshots")


def _cutoff_iso(before: str) -> str | None:
    """「YYYY-MM-DD」（或带时间的 ISO 日期）→ 当日时刻的 utc_now() 同形
    文本（ISO 文本比较口径，与各表 created_at 存储形态一致）。
    非法 → None（调用方回 400，不猜）。"""
    from datetime import UTC, datetime

    text = str(before or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _iso_to_epoch(iso_text: str) -> int:
    from datetime import UTC, datetime

    parsed = datetime.fromisoformat(iso_text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


async def _require_user(request: Request) -> str | None:
    """session 模式下解析服务端身份；basic 模式没有账户会话语义 → None。"""
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


def _reject(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": err_type, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def _activity_counts(request: Request, user_id: str, cutoff: str) -> dict[str, int]:
    from lumirss.ai_task_log import AiTaskLogStore
    from lumirss.auth_store import AuthStore
    from lumirss.search_snapshot_store import SearchSnapshotStore

    return {
        "loginEvents": await AuthStore(
            request.app.state.control_db
        ).count_login_events_before(user_id, _iso_to_epoch(cutoff)),
        "aiTaskLogs": await AiTaskLogStore(request.app.state.db).count_before(cutoff),
        "searchSnapshots": await SearchSnapshotStore(
            request.app.state.db
        ).count_before(cutoff),
    }


class ActivityPurgeBody(BaseModel):
    """POST /me/activity-purge — 清除某日期之前的服务端活动记录。"""

    before: str = Field(min_length=4, max_length=32)
    include: dict[str, bool] = Field(default_factory=dict)


@router.get("/api/v1/me/activity-purge/preview", response_model=None)
async def activity_purge_preview(request: Request, before: str) -> JSONResponse:
    """预览各活动桶在 before 之前的记录数（只读，不清除）。"""
    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    cutoff = _cutoff_iso(before)
    if cutoff is None:
        return _reject(400, "invalid_request", "before 必须是 ISO 日期（如 2026-01-01）。")
    counts = await _activity_counts(request, user_id, cutoff)
    return JSONResponse(
        content={"before": cutoff, "counts": counts, "retained": _RETAINED_NOTES},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/v1/me/activity-purge", response_model=None)
async def activity_purge(body: ActivityPurgeBody, request: Request) -> JSONResponse:
    """N189：清除 before 之前的服务端活动记录（登录事件 / AI 任务日志 /
    搜索快照；按 include 选择，缺省全清）。响应如实列出各桶删除数与
    保留说明；绝不触碰已读/收藏/笔记等业务状态。已删除的记录不会因
    缓存复活（这些表没有任何缓存写入路径）。"""
    from lumirss.ai_task_log import AiTaskLogStore
    from lumirss.auth_store import AuthStore
    from lumirss.search_snapshot_store import SearchSnapshotStore

    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    cutoff = _cutoff_iso(body.before)
    if cutoff is None:
        return _reject(400, "invalid_request", "before 必须是 ISO 日期（如 2026-01-01）。")
    include = {str(k): bool(v) for k, v in body.include.items()}

    def wants(bucket: str) -> bool:
        return include.get(bucket, True)  # 缺省 = 清除

    deleted: dict[str, int] = {bucket: 0 for bucket in _ACTIVITY_BUCKETS}
    if wants("loginEvents"):
        deleted["loginEvents"] = await AuthStore(
            request.app.state.control_db
        ).purge_login_events_before(user_id, _iso_to_epoch(cutoff))
    if wants("aiTaskLogs"):
        deleted["aiTaskLogs"] = await AiTaskLogStore(request.app.state.db).purge_before(cutoff)
    if wants("searchSnapshots"):
        deleted["searchSnapshots"] = await SearchSnapshotStore(
            request.app.state.db
        ).purge_before(cutoff)
    return JSONResponse(
        content={"before": cutoff, "deleted": deleted, "retained": _RETAINED_NOTES},
        headers={"Cache-Control": "no-store"},
    )
