"""F19 稍后读延后 — 延后/取消延后/到期回归。

- 加入稍后读 → snooze 明天 → 时间线隐藏；
- 取消延后 → 立即回时间线；
- snoozed_until 过期（<= now）→ 自动回时间线（无人工介入）；
- 延后不影响成员关系：snoozed 列表可见、原项目保留；
- 非成员 ref → 404 类错误；过去时刻 → 400。
"""

import asyncio
from datetime import UTC, datetime, timedelta

from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


def _join(client, entry_ref: str, title: str = "延后测试条目"):
    response = client.post(
        "/api/v1/workspaces/read-later/items",
        json={"itemRef": f"rss:{entry_ref}"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_f19_snooze_hides_until_cancelled(client):
    joined = _join(client, "e1.MDAwNjU5ZTA3YWFlZTI0ZA")
    assert joined["itemRef"].startswith("rss:")
    timeline = client.get("/api/v1/workspaces/read-later/timeline").json()
    assert any(item["itemRef"] == joined["itemRef"] for item in timeline["items"])

    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    snoozed = client.post(
        f"/api/v1/workspaces/read-later/items/{joined['itemRef']}/snooze",
        json={"until": future},
    )
    assert snoozed.status_code == 200, snoozed.text
    timeline = client.get("/api/v1/workspaces/read-later/timeline").json()
    assert all(item["itemRef"] != joined["itemRef"] for item in timeline["items"])
    # 行保留：延后列表可见
    snoozed_list = client.get("/api/v1/workspaces/read-later/snoozed").json()
    assert any(item["itemRef"] == joined["itemRef"] for item in snoozed_list["items"])

    # 取消延后 → 立即回时间线
    unsnooze = client.delete(
        f"/api/v1/workspaces/read-later/items/{joined['itemRef']}/snooze"
    )
    assert unsnooze.status_code == 204
    timeline = client.get("/api/v1/workspaces/read-later/timeline").json()
    assert any(item["itemRef"] == joined["itemRef"] for item in timeline["items"])


def test_f19_expired_snooze_returns_automatically(client):
    entry_ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"
    joined = _join(client, entry_ref)
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    # 用 store 直接写入过去时刻（路由拒绝过去值——防「延后到过去」假消失）
    from lumirss.workspaces import WorkspaceStore

    store = WorkspaceStore(app.state.db)
    ok = run(store.snooze_item("read-later", joined["itemRef"], past))
    assert ok is True
    timeline = client.get("/api/v1/workspaces/read-later/timeline").json()
    assert any(item["itemRef"] == joined["itemRef"] for item in timeline["items"])


def test_f19_rejects_past_and_nonmember(client):
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    response = client.post(
        "/api/v1/workspaces/read-later/items/rss%3Ae1.MDAwNjU5ZTA3YWFlZTI0ZA/snooze",
        json={"until": past},
    )
    assert response.status_code == 400
    response = client.post(
        "/api/v1/workspaces/read-later/items/rss%3Ae1.notamember/snooze",
        json={"until": "2099-01-01T00:00:00Z"},
    )
    assert response.status_code == 404
