"""N159 检索质量收藏测试 —— 私有评测样例（保存时捕获真实命中）。

- 保存：服务端立即检索并捕获实际命中（不是裸期望）；
- rerun：重放查询并差分（hitExpected / missed / newHits）；
- 隔离：样例在每用户库——其他账户结构上不可见；
- local-only：绝不进入分享包，也绝不出现在备份 manifest 组件里
  （backup_scope 组件→表映射刻意不含 rag_eval_samples）。
"""

import asyncio
import tempfile

import pytest

from lumirss.main import app
from lumirss.rag import MODEL_DIM, RagService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database

_REF_A = "library:2a8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
_REF_B = "library:2b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"


def run(coro):
    return asyncio.run(coro)


def _fake_embedder(service: RagService) -> None:
    async def fake_embed(texts):
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = fake_embed  # noqa: SLF001 — test seam


@pytest.fixture()
def rag_world(client):
    """注入带假嵌入器的 RagService + 两个投影文档。"""
    tmp = tempfile.TemporaryDirectory()
    db = Database(f"{tmp.name}/lumi.sqlite")
    run(_seed(db))
    service = RagService(db, db_path=f"{tmp.name}/lumi.sqlite")
    _fake_embedder(service)
    previous = app.state.rag_service
    app.state.rag_service = service
    run(service.rebuild())
    yield service, db
    app.state.rag_service = previous
    tmp.cleanup()


async def _seed(db: Database) -> None:
    await db.migrate()
    writer = LibrarySearchWriter(db)
    await writer.upsert(
        ref=_REF_A, kind="clip", title="检索增强笔记", body="检索增强的部署记录。", url=None
    )
    await writer.upsert(
        ref=_REF_B, kind="clip", title="无关文档", body="完全不同的主题内容。", url=None
    )


def _save_sample(client, **overrides) -> dict:
    payload = {"query": "检索增强", "expectedRefs": [_REF_A]}
    payload.update(overrides)
    response = client.post("/api/v1/rag/eval-samples", json=payload)
    assert response.status_code == 201
    return response.json()


def test_save_captures_actual_hits_at_save_time(client, rag_world):
    sample = _save_sample(client)
    assert sample["query"] == "检索增强"
    assert sample["expectedRefs"] == [_REF_A]
    # 保存时的真实命中被服务端捕获（假嵌入器下可稳定命中）。
    assert _REF_A in sample["actualRefs"]
    assert sample["kind"] is None
    listed = client.get("/api/v1/rag/eval-samples").json()
    assert listed["cap"] == 50
    assert [s["id"] for s in listed["items"]] == [sample["id"]]


def test_rerun_diff_tracks_drift(client, rag_world):
    service, db = rag_world
    sample = _save_sample(client, expectedRefs=[_REF_A, _REF_B])
    # 索引变化：新增一个「检索增强」相关文档 → newHits。
    async def _add():
        writer = LibrarySearchWriter(db)
        await writer.upsert(
            ref="library:2c8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f",
            kind="clip",
            title="检索增强第二篇",
            body="更多检索增强内容。",
            url=None,
        )

    run(_add())
    run(service.rebuild())
    rerun = client.post(f"/api/v1/rag/eval-samples/{sample['id']}/rerun")
    assert rerun.status_code == 200
    diff = rerun.json()
    assert diff["sampleId"] == sample["id"]
    assert diff["storedActualRefs"] == sample["actualRefs"]
    assert _REF_A in diff["hitExpected"]
    assert diff["newHits"], "新增的相关文档应作为漂移信号出现"
    # missed = 期望 − 现在实际。
    now_set = set(diff["nowActualRefs"])
    assert diff["missed"] == [
        ref for ref in sample["expectedRefs"] if ref not in now_set
    ]


def test_rerun_unknown_sample_404(client, rag_world):
    response = client.post("/api/v1/rag/eval-samples/eval-none/rerun")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "eval_sample_not_found"


def test_cap_50_enforced_not_silently_evicted(client, rag_world):
    for index in range(50):
        _save_sample(client, query=f"查询{index}")
    full = client.post(
        "/api/v1/rag/eval-samples", json={"query": "第 51 条"}
    )
    assert full.status_code == 409
    assert full.json()["error"]["type"] == "eval_sample_limit"
    listed = client.get("/api/v1/rag/eval-samples").json()["items"]
    assert len(listed) == 50


def test_samples_local_only_never_exported(client, rag_world):
    """绝不进分享包、绝不在备份 manifest 组件/范围表映射里。"""
    from lumirss.backup_scope import _COMPONENT_TABLES

    for tables in _COMPONENT_TABLES.values():
        assert "rag_eval_samples" not in tables
    assert not any("rag_eval" in c for c in _COMPONENT_TABLES)
    # 备份 manifest 的组件只可能是文件级（lumi.sqlite 等），绝无评测组件。
    # （结构断言：build_manifest 的 components 来自 file component 集合。）
    from lumirss.backup import build_manifest

    manifest = build_manifest(
        db_schema_version=1,
        files=[
            {
                "path": "lumi.sqlite",
                "component": "lumi.sqlite",
                "size": 1,
                "sha256": "0" * 64,
            }
        ],
        secret_configured=False,
    )
    assert manifest["components"] == ["lumi.sqlite"]
    assert not any("eval" in c for c in manifest["components"])


def test_delete_sample(client, rag_world):
    sample = _save_sample(client)
    deleted = client.delete(f"/api/v1/rag/eval-samples/{sample['id']}")
    assert deleted.status_code == 204
    assert (
        client.delete(f"/api/v1/rag/eval-samples/{sample['id']}").status_code == 404
    )
