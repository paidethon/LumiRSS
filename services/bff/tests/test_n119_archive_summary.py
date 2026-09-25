"""N119 归档摘要卡测试 —— 归档列表逐工作区摘要（真实行派生）。

- summary 字段：itemCount / doneCount（看板 done）/ goalProgress
  （target_count vs done）/ archivedAt / daysActive（created → archived
  整天数）；
- 摘要数学来自 fixture：3 成员、看板 done 2、目标 target 5 →
  {3, 2, {5, 2}}；
- 非归档工作区不出现在归档列表。
"""

from datetime import datetime, timedelta

import pytest

from lumirss.main import app


@pytest.fixture()
def archived_world(client):
    created = client.post("/api/v1/workspaces", json={"name": "研究项目"})
    workspace_id = created.json()["id"]
    refs = []
    for index in range(3):
        ref = client.post(
            "/api/v1/library/bookmarks",
            json={
                "url": f"https://example.com/n119-{index}",
                "title": f"条目{index}",
            },
        ).json()["ref"]
        client.post(f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": ref})
        refs.append(ref)
    # 看板：2 个 done、1 个 reading。
    for ref, status in [(refs[0], "done"), (refs[1], "done"), (refs[2], "reading")]:
        put = client.put(
            f"/api/v1/workspaces/{workspace_id}/board",
            json={"itemRef": ref, "status": status},
        )
        assert put.status_code in (200, 201)
    # 目标：target 5。
    goal = client.put(
        f"/api/v1/workspaces/{workspace_id}/goal", json={"targetCount": 5}
    )
    assert goal.status_code == 200
    # 把 created_at 拨回 3 天前（daysActive 可断言）。
    db = app.state.db
    old = datetime.now() - timedelta(days=3)

    async def _backdate():
        await db.migrate()
        await db.execute(
            "UPDATE workspaces SET created_at = ? WHERE id = ?",
            (old.strftime("%Y-%m-%dT%H:%M:%S+00:00"), workspace_id),
        )

    import asyncio

    asyncio.run(_backdate())
    archive = client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"archived": True},
    )
    assert archive.status_code == 200
    return workspace_id


def test_archive_list_carries_summary(client, archived_world):
    response = client.get("/api/v1/workspace-archive")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) >= 1
    entry = next(e for e in entries if e["id"] == archived_world)
    assert entry["archived"] is True
    assert entry["archivedAt"]
    summary = entry["summary"]
    assert summary["itemCount"] == 3
    assert summary["doneCount"] == 2
    assert summary["goalProgress"] == {"targetCount": 5, "doneCount": 2}
    assert summary["archivedAt"] == entry["archivedAt"]
    assert summary["daysActive"] >= 2  # 3 天前回拨（整日下取差的诚实下限）


def test_active_workspaces_not_in_archive_list(client, archived_world):
    entries = client.get("/api/v1/workspace-archive").json()
    assert all(e["id"] != "read-later" or e["archived"] for e in entries)
    # 恢复后从归档列表消失。
    client.patch(
        f"/api/v1/workspaces/{archived_world}", json={"archived": False}
    )
    entries = client.get("/api/v1/workspace-archive").json()
    assert all(e["id"] != archived_world for e in entries)
