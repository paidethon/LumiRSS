"""F049 收尾 — MD 笔记导入写批次（kind="md_notes"）与失败项重试幂等。

- 批次计数如实（imported/skipped/failed），失败项进 retry_payload
  （name/content/workspaceId 足以重放）；
- 批次记录失败不影响导入本身；
- retry 仅重试失败项；content_hash 幂等（已存在 → skipped）。
"""

import asyncio

from lumirss.import_batch_store import ImportBatchStore
from lumirss.main import app


def _import(client, files, workspace_id=None):
    payload = {"files": files}
    if workspace_id is not None:
        payload["workspaceId"] = workspace_id
    return client.post("/api/v1/library/notes/import", json=payload)


def _latest_batch(client, kind="md_notes"):
    items = client.get("/api/v1/library/import-batches").json()["items"]
    return next(item for item in items if item["kind"] == kind)


def test_f049_md_notes_import_records_batch(client):
    """导入写批次：计数如实；失败项（空名）进 errors + retry_payload。"""
    resp = _import(client, [
        {"name": "好笔记.md", "content": "# 正文\n\n内容。"},
        {"name": "   ", "content": "空名内容"},
    ])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 1

    batch = _latest_batch(client)
    assert batch["kind"] == "md_notes"
    assert batch["counts"] == {"imported": 1, "skipped": 0, "failed": 1}
    assert batch["errors"]["items"] == [{"url": "   ", "reason": "invalid"}]
    # retry_payload 保存失败文件的最小重放载荷（含内容与工作区）
    assert len(batch["retryPayload"]) == 1
    item = batch["retryPayload"][0]
    assert item["name"] == "   "
    assert item["content"] == "空名内容"
    assert item["workspaceId"] is None

    # 全部成功 → failed=0、retryPayload 为空
    _import(client, [{"name": "另一篇.md", "content": "另一篇内容"}])
    batch2 = _latest_batch(client)
    assert batch2["counts"] == {"imported": 1, "skipped": 0, "failed": 0}
    assert batch2["retryPayload"] == []


def test_f049_md_notes_retry_idempotent(client):
    """重试失败项：可导入的成功项 imported；重放再试 → skipped（幂等）；
    原批次记录不变（审计）。"""
    # 直接落一条失败批次（模拟历史上某次导入的失败项：一个仍会失败
    # 的空白名项 + 一个内容合法、重试即可成功的项）。
    store = ImportBatchStore(app.state.db)
    batch_id = asyncio.run(
        store.record(
            kind="md_notes",
            counts={"imported": 0, "skipped": 0, "failed": 2},
            errors=[
                {"url": "   ", "reason": "invalid"},
                {"url": "捡回.md", "reason": "too_large"},
            ],
            retry_payload=[
                {"name": "   ", "content": "空名", "workspaceId": None},
                {"name": "捡回.md", "content": "重试导入的内容", "workspaceId": "ws-r"},
            ],
        )
    )
    original = asyncio.run(store.get(batch_id))

    first = client.post(f"/api/v1/library/import-batches/{batch_id}/retry")
    assert first.status_code == 200, first.text
    body = first.json()
    # 空白名仍失败；合法项导入成功
    assert body["imported"] == 1
    assert body["skipped"] == 0
    assert body["failed"] == 1
    assert {"url": "   ", "reason": "invalid"} in body["errors"]

    # 已存在（幂等）：再试同一批次 → skipped，不重复创建
    second = client.post(f"/api/v1/library/import-batches/{batch_id}/retry").json()
    assert second["imported"] == 0
    assert second["skipped"] == 1
    assert second["failed"] == 1

    listing = client.get(
        "/api/v1/library/notes", params={"workspace_id": "ws-r"}
    ).json()
    assert [item["title"] for item in listing["items"]] == ["捡回"]

    # 原批次记录不变（审计保留）；重试新建批次
    assert asyncio.run(store.get(batch_id)) == original
    retry_batches = client.get("/api/v1/library/import-batches").json()["items"]
    assert any(b["id"] != batch_id and b["kind"] == "md_notes" for b in retry_batches)

    # 不存在的批次 → 404
    assert (
        client.post("/api/v1/library/import-batches/does-not-exist/retry").status_code
        == 404
    )
