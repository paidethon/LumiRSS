"""FIX-229 审计导出列序守卫 —— 廉价守卫测试（BASELINE_OK 证据）。

裁决：本代码库**不存在**「审计导出（CSV）」面——审计的唯一读取出口是
``GET /api/v1/admin/audit``（JSON），由 ``AccountsStore.audit_list`` 的
**显式 SELECT 列序**产出（``SELECT ts, actor, action, object_type,
object_id, outcome, detail``），不是 dict 迭代；服务端唯一的 CSV 构建
器（search_export.build_csv）吃显式 ``headers: list[str]`` + 位置行。
「字段顺序随字典变化」的前提在本库无从发生 → BASELINE_OK。

本守卫把「审计载荷形状固定」钉死，防止未来有人把审计出口改成
dict 迭代 / 动态列：
1. 审计行键集合恒等且顺序恒等（字典保持 SELECT 插入序），操作者、
   时间与结果列不会错位；
2. 不存在 /admin/audit/export 之类的 CSV 导出面（404，不静默出现）。

全部凭据为运行时生成的假值。
"""

import asyncio
import secrets

import pytest
from fastapi.testclient import TestClient

import lumirss.middleware as middleware
from lumirss.main import app

PASSWORD = "fx229-" + secrets.token_urlsafe(9)

# audit_list 显式 SELECT 的稳定列序（不是 dict 迭代的偶然序）。
AUDIT_COLUMN_ORDER = [
    "ts",
    "actor",
    "action",
    "object_type",
    "object_id",
    "outcome",
    "detail",
]


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def owner(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(tmp_path / "lumi.sqlite")
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": PASSWORD},
        )
        assert login.status_code == 200, login.text
        yield client, {"cookie": login.headers["set-cookie"].split(";")[0]}


def _set_owner_password(db_path) -> None:
    from lumirss.accounts_store import AccountsStore, hash_password
    from lumirss.storage import Database

    async def run():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return

    _run(run())


def test_audit_rows_have_fixed_column_order(owner):
    """审计行键集合与顺序恒等——显式 SELECT 列序，不随字典变化错位。"""
    client, headers = owner

    # 造几条形状各异的审计（detail/object 缺省各异），列序不受内容影响
    from lumirss.accounts_store import AccountsStore
    from lumirss.config import LumiSettings
    from lumirss.storage import Database

    db_path = LumiSettings().LUMIRSS_DB_PATH

    async def seed():
        database = Database(db_path)
        store = AccountsStore(database)
        await store.audit(actor="u1", action="fx229_probe_a")
        await store.audit(
            actor="u1",
            action="fx229_probe_b",
            object_type="invite",
            object_id="i9",
            outcome="error",
            detail="形状各异的行",
        )

    _run(seed())

    response = client.get("/api/v1/admin/audit?limit=50", headers=headers)
    assert response.status_code == 200, response.text
    entries = response.json()
    assert len(entries) >= 2
    for entry in entries:
        assert list(entry.keys()) == AUDIT_COLUMN_ORDER


def test_no_audit_csv_export_surface(owner):
    """不存在审计 CSV 导出面——「导出列序随字典变化」的前提无从发生。"""
    client, headers = owner
    for path in (
        "/api/v1/admin/audit/export",
        "/api/v1/admin/audit/csv",
        "/api/v1/admin/audit-export",
    ):
        assert client.get(path, headers=headers).status_code == 404, path
