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
