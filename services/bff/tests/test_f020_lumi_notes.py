"""F020 本地 Markdown 批量入库 —— 校验边界、幂等与预览零写入。"""

import asyncio


def run(coroutine):
    return asyncio.run(coroutine)


def _import(client, files, workspace_id=None):
    payload = {"files": files}
    if workspace_id is not None:
        payload["workspaceId"] = workspace_id
    return client.post("/api/v1/library/notes/import", json=payload)


def test_f020_import_success_idempotent_and_coexist(client):
    first = _import(client, [
        {"name": "笔记一.md", "content": "# 第一篇\n\n正文内容。"},
        {"name": "重名.md", "content": "内容甲"},
        {"name": "重名.md", "content": "内容乙"},  # 重名不同内容共存
    ], workspace_id=None)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["imported"] == 3
    assert all(item["ok"] for item in body["items"])

    # 同内容再导 → skipped（content_hash 幂等）
    second = _import(client, [{"name": "重名.md", "content": "内容甲"}]).json()
    assert second["imported"] == 0
    assert second["skipped"] == 1
    assert second["items"][0]["reason"] == "duplicate"

    # 列表：标题取文件名去扩展名；摘要首行
    listing = client.get("/api/v1/library/notes").json()
    titles = {item["title"] for item in listing["items"]}
    assert {"笔记一", "重名"} <= titles
    note = next(item for item in listing["items"] if item["title"] == "笔记一")
    assert note["excerpt"].startswith("# 第一篇")

    # workspace 过滤
    _import(client, [{"name": "工作区笔记.md", "content": "独一内容"}], workspace_id="ws-1")
    scoped = client.get("/api/v1/library/notes", params={"workspace_id": "ws-1"}).json()
    assert [item["title"] for item in scoped["items"]] == ["工作区笔记"]


def test_f020_validation_boundaries(client):
    # 超过 50 文件/批 → 422 too_many_files
    too_many = _import(client, [
        {"name": f"f{i}.md", "content": f"内容 {i}"} for i in range(51)
    ])
    assert too_many.status_code == 422  # 模型约束先拒（invalid_request）；路由层兜底校验同在

    # 单文件 > 200KB → per-item too_large（其余正常导入）
    big = "x" * (200 * 1024 + 1)
    mixed = _import(client, [
        {"name": "big.md", "content": big},
        {"name": "ok.md", "content": "正常内容"},
    ])
    assert mixed.status_code == 200
    body = mixed.json()
    assert body["items"][0]["ok"] is False
    assert body["items"][0]["reason"] == "too_large"
    assert body["items"][1]["ok"] is True

    # 空文件名 → per-item invalid
    invalid = _import(client, [{"name": "   ", "content": "x"}]).json()
    assert invalid["items"][0]["reason"] == "invalid"

    # 空批 → 422（pydantic min_length）
    empty = _import(client, [])
    assert empty.status_code == 422


def test_f020_preview_is_client_side_zero_writes_before_import(client):
    """导入前无任何库写入：未调用 import 端点前 lumi_notes 为空。"""
    listing = client.get("/api/v1/library/notes").json()
    assert listing["items"] == []
