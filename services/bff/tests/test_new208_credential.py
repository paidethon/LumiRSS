"""NEW-208 来源认证到期提醒 —— 登记/分桶/续期/dismiss + 无凭据契约。

验收问题对照：
- 谁登记：用户为自己的来源登记「凭据哪天到期」（到期日语义，
  不是凭据本体）；
- 入口：POST /api/v1/new208/reminders（表单无凭据字段，extra=forbid
  让客户端无法走私 secret 键）；
- 之前/之后：登记前 reminders 为空；登记后列表按到期日升序并分桶
  （overdue / due_soon / later，today 注入验证三个桶）；
- 谁能操作：创建者本人（A 看不到/续不了 B 的提醒——per-user 库）；
- 持久化：SQLite 行；renew 更新到期日并重新激活 dismissed 行；
- 失败/恢复：非法日期 422；未知 id 404 稳定信封。

安全负向契约：schema 无凭据列；响应永不回显凭据形态数据；更新引导
只给受控入口坐标（rsshub-credentials / freshrss-native）。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.new208_credential import classify_expiry
from lumirss.routers import new208_credential as reminder_router
from new201_210_harness import feature_app

FEED = "https://rsshub.example/github/starred_repos/DIYgod"


@pytest.fixture()
def make_client(tmp_path):
    clients = []

    def _make(*routers):
        app = feature_app(tmp_path, *routers)
        client = TestClient(app)
        clients.append(client)
        return client, app

    yield _make
    for client in clients:
        client.close()


def _create(client, expires_on="2030-01-01", **overrides):
    body = {"feedUrl": FEED, "expiresOn": expires_on, "note": "找站务续期"}
    body.update(overrides)
    return client.post("/api/v1/new208/reminders", json=body)


def test_new208_create_list_buckets_and_renew(make_client):
    client, _app = make_client(reminder_router.router)
    assert client.get("/api/v1/new208/reminders").json()["items"] == []

    created = _create(client)
    assert created.status_code == 201, created.text
    reminder = created.json()
    assert reminder["status"] == "active" and reminder["renewedCount"] == 0

    # 分桶（today 注入）：overdue / due_soon / later 三桶齐全
    _create(client, expires_on="2026-01-01", feedUrl="https://a.example/f1")
    _create(client, expires_on="2026-10-05", feedUrl="https://a.example/f2")
    listing = client.get(
        "/api/v1/new208/reminders", params={"today": "2026-09-28"}
    ).json()
    by_expires = {item["expiresOn"]: item for item in listing["items"]}
    assert by_expires["2026-01-01"]["bucket"] == "overdue"
    assert by_expires["2026-10-05"]["bucket"] == "due_soon"
    assert by_expires["2030-01-01"]["bucket"] == "later"
    assert listing["today"] == "2026-09-28"
    assert "凭据" in listing["note"]

    # renew：到期日更新 + 计数 + dismissed 复原
    dismissed = client.post(f"/api/v1/new208/reminders/{reminder['id']}/dismiss")
    assert dismissed.json()["status"] == "dismissed"
    hidden = client.get("/api/v1/new208/reminders").json()["items"]
    assert all(item["id"] != reminder["id"] for item in hidden)
    renewed = client.post(
        f"/api/v1/new208/reminders/{reminder['id']}/renew",
        json={"expiresOn": "2031-06-01"},
    )
    assert renewed.status_code == 200
    body = renewed.json()
    assert body["expiresOn"] == "2031-06-01"
    assert body["renewedCount"] == 1
    assert body["status"] == "active", "续期后提醒应重新可见"

    # 校验错误：非法日期 422 / 未知字段 422 / 未知 id 404
    assert _create(client, expires_on="01/02/2030").status_code == 422
    smuggle = client.post(
        "/api/v1/new208/reminders",
        json={"feedUrl": FEED, "expiresOn": "2030-01-01", "password": "hunter2"},
    )
    assert smuggle.status_code == 422, "extra=forbid：凭据形态字段无法走私"
    missing = client.post(
        "/api/v1/new208/reminders/nope/renew", json={"expiresOn": "2031-01-01"}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "credential_reminder_not_found"


def test_new208_no_secret_store_and_update_entry_guidance(make_client, tmp_path):
    """无凭据契约：DB 里只有到期日语义；更新引导指向受控入口。"""
    import sqlite3

    client, app = make_client(reminder_router.router)
    rsshub_feed = "https://rsshub.example/github/starred_repos/DIYgod"
    plain_feed = "https://example.com/feed.xml"
    created = client.post(
        "/api/v1/new208/reminders",
        json={"feedUrl": rsshub_feed, "expiresOn": "2030-01-01"},
    ).json()
    listing = client.get("/api/v1/new208/reminders").json()["items"]
    entry = next(item for item in listing if item["id"] == created["id"])
    assert entry["updateEntry"] == "rsshub-credentials"

    client.post(
        "/api/v1/new208/reminders",
        json={"feedUrl": plain_feed, "expiresOn": "2030-02-01"},
    )
    listing = client.get("/api/v1/new208/reminders").json()["items"]
    other = next(item for item in listing if item["feedUrl"] == plain_feed)
    assert other["updateEntry"] == "freshrss-native"

    # per-user 库逐字节检查：任何行都没有「值」形态的列
    db_path = tmp_path / "users" / "owner" / "lumi.sqlite"
    conn = sqlite3.connect(str(db_path))
    cols = [
        row[1]
        for row in conn.execute("PRAGMA table_info(new208_credential_reminders)")
    ]
    conn.close()
    assert not any("secret" in c or "credential_value" in c or "token" in c for c in cols)
    assert "expires_on" in cols and "note" in cols
    assert classify_expiry("2026-01-01", today="2026-09-28") == "overdue"


def test_new208_per_user_isolation(make_client):
    client, _app = make_client(reminder_router.router)
    alice = {"x-test-user": "alice"}
    bob = {"x-test-user": "bob"}
    created = client.post(
        "/api/v1/new208/reminders",
        json={"feedUrl": FEED, "expiresOn": "2030-01-01"},
        headers=bob,
    )
    assert created.status_code == 201
    reminder_id = created.json()["id"]

    assert client.get("/api/v1/new208/reminders", headers=alice).json()["items"] == []
    assert (
        client.post(
            f"/api/v1/new208/reminders/{reminder_id}/renew",
            json={"expiresOn": "2031-01-01"},
            headers=alice,
        ).status_code
        == 404
    )
    mine = client.get("/api/v1/new208/reminders", headers=bob).json()["items"]
    assert [item["id"] for item in mine] == [reminder_id]
