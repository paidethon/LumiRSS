"""N194 探针时效与延迟展示 — GET /api/v1/admin/system per-probe fields.

- 每个 service 条目都带 checkedAt（探针完成的服务端时刻，ISO 可解析）
  与 stale（早于 5 分钟 → True；服务端在响应内即时计算）；
- _probe_freshness 单元：fresh / stale / 无时间戳 / 不可解析四种输入；
- 端到端：operations 探针返回旧的 lastCheckedAt → 对应服务 stale=True；
  现跑探针（默认 client 环境）→ 恒 fresh。
"""

import asyncio
from datetime import UTC, datetime, timedelta


def run(coro):
    return asyncio.run(coro)


# ---- 单元：_probe_freshness -------------------------------------------------


def test_probe_freshness_units():
    from lumirss.routers.admin import _probe_freshness

    now = datetime.now(UTC).timestamp()
    # 刚跑完的探针 → fresh
    fresh_iso = datetime.now(UTC).isoformat(timespec="seconds")
    checked, stale = _probe_freshness(fresh_iso, now_epoch=now)
    assert checked == fresh_iso
    assert stale is False
    # 6 分钟前的探针 → 过期
    old_iso = (datetime.now(UTC) - timedelta(minutes=6)).isoformat(timespec="seconds")
    checked, stale = _probe_freshness(old_iso, now_epoch=now)
    assert checked == old_iso
    assert stale is True
    # 无时间戳（presence-only 服务 / 本响应内现跑）→ 服务端当前时刻 + fresh
    checked, stale = _probe_freshness(None, now_epoch=now)
    assert checked is not None
    assert "T" in checked
    datetime.fromisoformat(checked)  # 可解析
    assert stale is False
    # 不可解析 → 诚实降级（不宣称过期），时间戳回落为当前时刻
    checked, stale = _probe_freshness("not-a-timestamp", now_epoch=now)
    assert checked is not None and checked != "not-a-timestamp"
    assert stale is False


# ---- 端到端：/admin/system 的 services 均带 checkedAt + stale ---------------


def test_system_services_carry_checked_at_and_stale(client):
    response = client.get("/api/v1/admin/system")
    assert response.status_code == 200, response.text
    services = response.json()["services"]
    assert services, "system endpoint must report the service probes"
    for service in services:
        assert set(service) >= {"name", "status", "latencyMs", "checkedAt", "stale"}
        # checkedAt 存在且可解析（探针完成的服务端时刻）
        assert isinstance(service["checkedAt"], str) and service["checkedAt"] != ""
        datetime.fromisoformat(service["checkedAt"])
        # 探针在本响应内现跑 → 不可能过期
        assert service["stale"] is False


class _OldProbeService:
    """stub：freshrss 探针返回 10 分钟前的 lastCheckedAt（延迟也如实）。"""

    def __init__(self, old_iso: str) -> None:
        self._old_iso = old_iso

    async def sqlite_status(self) -> dict:
        return {"status": "healthy", "schemaVersion": 1}

    async def freshrss_status(self) -> dict:
        return {
            "status": "healthy",
            "latencyMs": 123,
            "lastCheckedAt": self._old_iso,
            "error": None,
        }

    async def rsshub_status(self) -> dict:
        return {
            "status": "unavailable",
            "latencyMs": 45,
            "lastCheckedAt": self._old_iso,
            "error": {"type": "connection_error"},
        }


def test_stale_flag_computed_from_probe_age(client):
    old_iso = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(
        timespec="seconds"
    )
    client.app.state.operations_service = _OldProbeService(old_iso)
    response = client.get("/api/v1/admin/system")
    assert response.status_code == 200, response.text
    services = {s["name"]: s for s in response.json()["services"]}
    # 带旧时间戳的探针 → stale=True（且延迟如实透传）
    assert services["freshrss"]["stale"] is True
    assert services["freshrss"]["checkedAt"] == old_iso
    assert services["freshrss"]["latencyMs"] == 123
    assert services["rsshub"]["stale"] is True
    # sqlite 探针不带自身时间戳 → 按响应内现跑处理（fresh + 当前时刻）
    assert services["sqlite"]["stale"] is False
    assert services["sqlite"]["checkedAt"] is not None
    # presence-only 服务同样带 checkedAt / stale
    for name in ("obsidian", "webdav", "ai", "imap"):
        assert services[name]["checkedAt"] is not None
        assert services[name]["stale"] is False
