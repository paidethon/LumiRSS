"""NEW-397 实例服务状态页 —— 真实本地检测台账，绝不虚构可用率。

边界（硬规则）：

- 检测只用**本地事实**：控制库 ``SELECT 1``、FreshRSS/RSSHub/AI 的
  配置字段存在性——不做网络探测、不算可用率百分比、没有的数据绝不
  出现（未配置就是 unconfigured，不是「降级可用」）；
- 每次检测追加一行台账；读取侧每面取最新一条 = 「最近检测时间」，
  历史只保留每面最近 20 条；
- 已登录用户即可查看（实例自用规模；不含任何凭据材料）。
"""

from typing import Any

from lumirss.config import FreshRSSSettings, LumiSettings, RssHubSettings
from lumirss.storage import Database
from lumirss.util import utc_now

_HISTORY_PER_SURFACE = 20

SURFACE_LABELS = {
    "control_db": "Lumi 控制库",
    "freshrss": "FreshRSS 配置",
    "rsshub": "RSSHub 配置",
    "ai": "AI 配置",
}


async def _check_control_db(db: Database) -> tuple[str, str]:
    try:
        row = await db.fetch_one("SELECT 1 AS ok", ())
        applied = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM schema_migrations", ()
        )
    except Exception as exc:  # noqa: BLE001 — 检测结论进台账，不抛给状态页
        return "fail", f"控制库不可用：{type(exc).__name__}。"
    if row is None or int(row["ok"]) != 1:
        return "fail", "控制库 SELECT 1 未返回。"
    return "ok", f"控制库可读写，已应用迁移 {int(applied['n'])} 个。"


def _check_freshrss() -> tuple[str, str]:
    """配置面字段存在性（FreshRSSSettings 未配置时实例化即校验失败）。"""
    try:
        settings = FreshRSSSettings()
    except Exception:  # noqa: BLE001 — ValidationError = 必填配置缺失
        return "unconfigured", (
            "未配置：FRESHRSS_BASE_URL / FRESHRSS_USERNAME /"
            " FRESHRSS_API_PASSWORD。"
        )
    base = settings.FRESHRSS_BASE_URL.strip()
    username = settings.FRESHRSS_USERNAME.strip()
    password = settings.FRESHRSS_API_PASSWORD.get_secret_value().strip()
    missing = [
        name
        for name, value in (
            ("FRESHRSS_BASE_URL", base),
            ("FRESHRSS_USERNAME", username),
            ("FRESHRSS_API_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        return "unconfigured", f"未配置：{'、'.join(missing)}。"
    return "ok", "FreshRSS 连接配置齐备（本页不做网络探测）。"


def _check_rsshub() -> tuple[str, str]:
    try:
        settings = RssHubSettings()
    except Exception:  # noqa: BLE001 — ValidationError = 必填配置缺失
        return "unconfigured", "未配置：RSSHUB_BASE_URL。"
    base = settings.RSSHUB_BASE_URL.strip()
    if not base:
        return "unconfigured", "未配置：RSSHUB_BASE_URL。"
    return "ok", "RSSHub 基地址已配置（本页不做网络探测）。"


def _check_ai() -> tuple[str, str]:
    if not LumiSettings().ai_configured:
        return "unconfigured", "未配置：AI_API_KEY。"
    return "ok", "AI API Key 已配置（本页不做网络探测）。"


async def run_checks(db: Database) -> dict[str, Any]:
    """执行全部本地检测、落台账并返回状态页负载。"""
    await db.migrate()
    results = [
        ("control_db", await _check_control_db(db)),
        ("freshrss", _check_freshrss()),
        ("rsshub", _check_rsshub()),
        ("ai", _check_ai()),
    ]
    now = utc_now()
    for surface, (status, detail) in results:
        await db.execute(
            "INSERT INTO service_status_checks (surface, status, detail, checked_at)"
            " VALUES (?, ?, ?, ?)",
            (surface, status, detail, now),
        )
        rows = await db.fetch_all(
            "SELECT id FROM service_status_checks WHERE surface = ?"
            " ORDER BY checked_at DESC, id DESC",
            (surface,),
        )
        stale = rows[_HISTORY_PER_SURFACE:]
        for row in stale:
            await db.execute(
                "DELETE FROM service_status_checks WHERE id = ?", (int(row["id"]),)
            )
    surfaces = [
        {
            "key": surface,
            "label": SURFACE_LABELS.get(surface, surface),
            "status": status,
            "detail": detail,
            "checkedAt": now,
        }
        for surface, (status, detail) in results
    ]
    return {
        "surfaces": surfaces,
        "notes": [
            "本页只报告本地真实检测结果与最近检测时间，不提供可用率百分比。",
            "unconfigured 表示配置字段缺失，不代表服务本身故障。",
        ],
    }


async def status_page(db: Database) -> dict[str, Any]:
    """读取台账最新状态 + 每面最近历史（不触发新检测）。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT * FROM service_status_checks ORDER BY checked_at DESC, id DESC"
    )
    latest: dict[str, Any] = {}
    history: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        surface = str(row["surface"])
        history.setdefault(surface, []).append(
            {"status": str(row["status"]), "checkedAt": str(row["checked_at"])}
        )
        if surface not in latest:
            latest[surface] = row
    known = list(SURFACE_LABELS)
    surfaces = [
        {
            "key": surface,
            "label": SURFACE_LABELS[surface],
            "status": str(latest[surface]["status"]) if surface in latest else "unknown",
            "detail": str(latest[surface]["detail"]) if surface in latest else "",
            "checkedAt": str(latest[surface]["checked_at"]) if surface in latest else None,
            "history": history.get(surface, [])[:_HISTORY_PER_SURFACE],
        }
        for surface in known
    ]
    return {
        "surfaces": surfaces,
        "notes": [
            "本页只报告本地真实检测结果与最近检测时间，不提供可用率百分比。",
            "unknown 表示该面尚未执行过检测。",
        ],
    }
