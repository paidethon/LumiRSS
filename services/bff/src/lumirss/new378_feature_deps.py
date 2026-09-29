"""NEW-378 实例功能依赖图 —— 某功能依赖哪些已配置服务、缺哪一项、
探测时间是什么时候。

探测只做**本地检查**（env 变量、配置文件/目录存在性、每用户库的
绑定行），绝不发外部网络请求，因此测试零网络也稳定可跑。秘密值
永不出现：秘密只有「已配置 / 未配置」两个状态位（与系统面板同一
口径）。探测结果落 admin_feature_probes（每依赖项一行最新态 +
实际探测时间）；功能图读取最新态，未探测的依赖如实给
status="unknown" + 探测指引，不编造。

依赖 → 检查的映射（全部只读既有真源）：
- freshrss_binding   —— 任一活跃账户的 freshrss_binding 行存在；
- rsshub_url         —— LUMIRSS RSSHUB_BASE_URL（或 FRESHRSS 回落）非空；
- smtp               —— 任一活跃账户 digest_settings 的 smtp_host 非空；
- imap               —— 任一活跃账户 mail_settings/mail_accounts 配置；
- ai_provider        —— 任一活跃账户的 AI provider key 已配置
                       （ai_settings 的 provider 非空即可，不读键值）；
- rag_model          —— RAG 依赖组安装（fastembed 可导入）或词法降级
                       如实标注；
- webhook_signing_key —— NEW-304 SigningKeyStore 当前钥存在；
- obsidian_vault     —— LUMIRSS_OBSIDIAN_VAULT_DIR 非空且目录存在；
- sqlite             —— 控制库文件存在（运行中必真，作图底）。
"""

import importlib.util
from pathlib import Path
from typing import Any

from lumirss.util import utc_now

DEP_KINDS: dict[str, str] = {
    "freshrss_binding": "FreshRSS 绑定（任一活跃账户）",
    "rsshub_url": "RSSHub 地址",
    "smtp": "SMTP 发信（邮件摘要）",
    "imap": "IMAP 收信（邮件导入）",
    "ai_provider": "AI provider",
    "rag_model": "RAG 语义索引运行时",
    "webhook_signing_key": "Webhook 签名钥",
    "obsidian_vault": "Obsidian 仓库目录",
    "sqlite": "Lumi SQLite 控制库",
}

FEATURES: list[dict[str, Any]] = [
    {"key": "native_rss", "label": "原生 RSS/Atom 订阅", "deps": ["sqlite", "freshrss_binding"]},
    {"key": "rsshub_sources", "label": "RSSHub 非RSS 来源", "deps": ["sqlite", "rsshub_url", "freshrss_binding"]},
    {"key": "mail_digest", "label": "邮件摘要", "deps": ["sqlite", "smtp"]},
    {"key": "mail_import", "label": "邮件导入", "deps": ["sqlite", "imap"]},
    {"key": "ai_features", "label": "AI 能力（摘要/翻译/问答）", "deps": ["sqlite", "ai_provider"]},
    {"key": "rag_semantic", "label": "RAG 语义检索", "deps": ["sqlite", "rag_model"]},
    {"key": "webhook_inbox", "label": "Webhook 接入", "deps": ["sqlite", "webhook_signing_key"]},
    {"key": "obsidian_sync", "label": "Obsidian 只读同步", "deps": ["sqlite", "obsidian_vault"]},
]

_DEP_LIMIT = 50


async def _active_user_db_paths(state: Any, control_db: Any) -> list[Path]:
    from lumirss.accounts_store import AccountsStore
    from lumirss.user_scope import RoutingDatabase

    try:
        user_ids = await AccountsStore(control_db).active_user_ids()
    except Exception:  # noqa: BLE001
        return []
    routing = state.db
    if not isinstance(routing, RoutingDatabase):
        return []
    return [routing.user_db_path(uid) for uid in user_ids[:_DEP_LIMIT]]


async def _probe_freshrss_binding_async(state: Any, control_db: Any) -> dict[str, Any]:
    from lumirss.storage import Database

    for path in await _active_user_db_paths(state, control_db):
        try:
            db = Database(path)
            await db.migrate()
            row = await db.fetch_one("SELECT id FROM freshrss_binding WHERE id = 1", ())
            if row is not None:
                return {"configured": True, "detail": "存在已绑定 FreshRSS 的活跃账户。"}
        except Exception:  # noqa: BLE001 — 打不开的账户跳过
            continue
    return {"configured": False, "detail": "没有任何活跃账户完成 FreshRSS 绑定。"}


async def _probe_smtp_async(state: Any, control_db: Any) -> dict[str, Any]:
    from lumirss.storage import Database

    for path in await _active_user_db_paths(state, control_db):
        try:
            db = Database(path)
            await db.migrate()
            row = await db.fetch_one(
                "SELECT smtp_host, enabled FROM digest_settings WHERE id = 1", ()
            )
            if row is not None and str(row["smtp_host"] or "").strip():
                return {"configured": True, "detail": "存在已配置 SMTP 的邮件摘要设置。"}
        except Exception:  # noqa: BLE001
            continue
    return {"configured": False, "detail": "没有账户配置邮件摘要 SMTP。"}


async def _probe_imap_async(state: Any, control_db: Any) -> dict[str, Any]:
    """IMAP 配置 = 每用户 secrets 的 mail_imap 条目（host+user 齐备）。"""
    import json as _json

    from lumirss.mail_imap import _IMAP_CONFIG_ENTRY
    from lumirss.user_scope import RoutingSecretsStore

    secrets = getattr(state, "secrets_store", None)
    if not isinstance(secrets, RoutingSecretsStore):
        return {"configured": False, "detail": "secrets 存储不可用。"}
    for path in await _active_user_db_paths(state, control_db):
        try:
            store = secrets.store_for(path.parent.name)
            raw = store.get(_IMAP_CONFIG_ENTRY)
            if not raw:
                continue
            data = _json.loads(raw)
            if isinstance(data, dict) and data.get("host") and data.get("user"):
                return {"configured": True, "detail": "存在已配置 IMAP 的邮件账户。"}
        except Exception:  # noqa: BLE001 — 解析失败按未配置继续
            continue
    return {"configured": False, "detail": "没有账户配置 IMAP 邮件账户。"}


async def _probe_ai_provider_async(state: Any, control_db: Any) -> dict[str, Any]:
    """provider/base_url/model 配置位检查（密钥值绝不读取或回显）。"""
    from lumirss.config import LumiSettings
    from lumirss.storage import Database

    if str(LumiSettings().AI_API_KEY.get_secret_value() or "").strip():
        return {"configured": True, "detail": "实例级 AI_API_KEY 已配置（值不回显）。"}
    for path in await _active_user_db_paths(state, control_db):
        try:
            db = Database(path)
            await db.migrate()
            rows = await db.fetch_all(
                "SELECT key, value FROM lumi_settings WHERE key IN ('ai.base_url', 'ai.model')",
                (),
            )
            values = {str(row["key"]): str(row["value"] or "").strip() for row in rows}
            if values.get("ai.base_url") and values.get("ai.model"):
                return {"configured": True, "detail": "存在已配置 base_url+model 的 AI 设置。"}
        except Exception:  # noqa: BLE001 — 打不开的账户跳过
            continue
    return {
        "configured": False,
        "detail": "未配置 AI provider（env AI_API_KEY 与账户级 base_url+model 均缺）。",
        "note": "仅检查配置位存在性，密钥值绝不读取回显。",
    }


def _probe_rsshub_url() -> dict[str, Any]:
    from lumirss.config import RssHubSettings

    settings = RssHubSettings()
    if settings.RSSHUB_BASE_URL.strip() or settings.RSSHUB_FRESHRSS_BASE_URL.strip():
        return {"configured": True, "detail": "RSSHUB_BASE_URL（或 FreshRSS 回落）已配置。"}
    return {"configured": False, "detail": "未配置 RSSHUB_BASE_URL。"}


def _probe_obsidian_vault() -> dict[str, Any]:
    from lumirss.config import LumiSettings

    value = LumiSettings().LUMIRSS_OBSIDIAN_VAULT_DIR.strip()
    if not value:
        return {"configured": False, "detail": "未配置 LUMIRSS_OBSIDIAN_VAULT_DIR。"}
    if Path(value).is_dir():
        return {"configured": True, "detail": "仓库目录存在。"}
    return {"configured": False, "detail": "已配置但目录不存在。"}


def _probe_rag_model() -> dict[str, Any]:
    if importlib.util.find_spec("fastembed") is not None:
        return {"configured": True, "detail": "语义嵌入运行时已安装（fastembed）。"}
    return {
        "configured": False,
        "detail": "未安装 RAG 依赖组（fastembed）——语义检索降级为词法检索。",
    }


def _probe_sqlite(state: Any) -> dict[str, Any]:
    from lumirss.config import LumiSettings

    path = Path(LumiSettings().LUMIRSS_DB_PATH)
    if path.exists():
        return {"configured": True, "detail": "控制库文件存在。"}
    return {"configured": False, "detail": "控制库文件不存在（实例从未启动？）。"}


async def _probe_webhook_key_async(control_db: Any) -> dict[str, Any]:
    try:
        from lumirss.new304_webhook_keys import SigningKeyStore

        snapshot = await SigningKeyStore(control_db).snapshot()
        keys = snapshot.get("keys") or []
        current = [k for k in keys if str(k.get("state", "")) == "active"] if isinstance(keys, list) else []
        if current:
            return {"configured": True, "detail": "存在 active 签名钥（钥值不回显）。"}
        return {"configured": False, "detail": "没有 active 签名钥（尚未轮换）。"}
    except Exception:  # noqa: BLE001
        return {"configured": False, "detail": "签名钥存储不可用。"}


async def probe_all(state: Any, control_db: Any) -> dict[str, Any]:
    """运行全部本地探测并落库（每依赖项一行最新态 + 实际探测时间）。"""
    await control_db.migrate()
    probed_at = utc_now()
    results: dict[str, dict[str, Any]] = {}
    results["freshrss_binding"] = await _probe_freshrss_binding_async(state, control_db)
    results["smtp"] = await _probe_smtp_async(control_db=control_db, state=state)
    results["imap"] = await _probe_imap_async(control_db=control_db, state=state)
    results["ai_provider"] = await _probe_ai_provider_async(control_db=control_db, state=state)
    results["rsshub_url"] = _probe_rsshub_url()
    results["obsidian_vault"] = _probe_obsidian_vault()
    results["rag_model"] = _probe_rag_model()
    results["sqlite"] = _probe_sqlite(state)
    results["webhook_signing_key"] = await _probe_webhook_key_async(control_db)

    for dep_key, result in results.items():
        await control_db.execute(
            "INSERT OR REPLACE INTO admin_feature_probes (dep_key, configured, detail, probed_at)"
            " VALUES (?, ?, ?, ?)",
            (
                dep_key,
                1 if result["configured"] else 0,
                str(result["detail"]),
                probed_at,
            ),
        )

    stored = await stored_probe_state(control_db)
    return {
        "features": [
            {
                "key": feature["key"],
                "label": feature["label"],
                "deps": [
                    {
                        "key": dep,
                        "kind": DEP_KINDS.get(dep, dep),
                        "status": "configured" if stored.get(dep, {}).get("configured") else "missing",
                        "detail": stored.get(dep, {}).get("detail", ""),
                        "probedAt": stored.get(dep, {}).get("probedAt"),
                    }
                    for dep in feature["deps"]
                ],
                "ready": all(stored.get(dep, {}).get("configured") for dep in feature["deps"]),
            }
            for feature in FEATURES
        ],
        "probedAt": probed_at,
        "notes": [
            "探测只做本地检查，不发外部网络请求；外部连通性看系统面板服务健康。",
            "秘密只有 已配置/未配置 状态位，值永不回显。",
        ],
    }


async def stored_probe_state(control_db: Any) -> dict[str, dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all("SELECT dep_key, configured, detail, probed_at FROM admin_feature_probes", ())
    return {
        str(row["dep_key"]): {
            "configured": bool(row["configured"]),
            "detail": str(row["detail"]),
            "probedAt": str(row["probed_at"]),
        }
        for row in rows
    }


async def dependency_graph(control_db: Any) -> dict[str, Any]:
    """不触发探测的只读视图（未探测 → unknown，如实呈现）。"""
    stored = await stored_probe_state(control_db)
    features = []
    for feature in FEATURES:
        deps = []
        ready = True
        for dep in feature["deps"]:
            state_row = stored.get(dep)
            if state_row is None:
                status = "unknown"
                ready = False
            else:
                status = "configured" if state_row["configured"] else "missing"
                ready = ready and state_row["configured"]
            deps.append(
                {
                    "key": dep,
                    "kind": DEP_KINDS.get(dep, dep),
                    "status": status,
                    "detail": (state_row or {}).get("detail", ""),
                    "probedAt": (state_row or {}).get("probedAt"),
                }
            )
        features.append({"key": feature["key"], "label": feature["label"], "deps": deps, "ready": ready})
    return {
        "features": features,
        "notes": [
            "未探测的依赖如实标 unknown；运行 POST /probe 获得实际探测时间。",
            "秘密只有 已配置/未配置 状态位，值永不回显。",
        ],
    }
