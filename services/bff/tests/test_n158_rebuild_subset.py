"""N158 局部索引重建测试 —— 只重嵌所选 refs（绝不全量 wipe）。

- subset 重建：指定 refs 的分块被真实重写（进度 job 行 done/total）；
- 其余 refs 的分块原封不动（chunk_id + text 双重断言）；
- 投影缺失的 ref 诚实进 missing；
- 取消 = 暂停：批间安全点翻作业行 → status=paused + pending 持久化，
  resume 从游标继续；无全量 staging wipe。
"""

import asyncio
import tempfile

import pytest

from lumirss.main import app
from lumirss.rag import MODEL_DIM, MODEL_ID, RagService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database

_REF_A = "library:1a8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
_REF_B = "library:1b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"


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
def indexed_world(client):
    """构造独立 RagService（注入 app.state 的 legacy 句柄）+ 两个投影
    文档，先全量索引一次。"""
    tmp = tempfile.TemporaryDirectory()
    db = Database(f"{tmp.name}/lumi.sqlite")
    run(_seed(db))
    service = RagService(db, db_path=f"{tmp.name}/lumi.sqlite")
    _fake_embedder(service)
    previous = app.state.rag_service
    app.state.rag_service = service
    built = run(service.rebuild())
    assert built["chunks"] >= 2
    yield service, db
    app.state.rag_service = previous
    tmp.cleanup()


async def _seed(db: Database) -> None:
    await db.migrate()
    writer = LibrarySearchWriter(db)
    await writer.upsert(
        ref=_REF_A, kind="clip", title="向量检索", body="旧内容甲。", url=None
    )
    await writer.upsert(
        ref=_REF_B, kind="clip", title="推理优化", body="内容乙保持稳定。", url=None
    )


def _chunks(db: Database, ref: str) -> list[tuple[int, str]]:
    async def _query():
        await db.migrate()
        rows = await db.fetch_all(
            "SELECT chunk_id, text FROM rag_chunks WHERE ref = ? AND model_id = ? ORDER BY ord ASC",
            (ref, MODEL_ID),
        )
        return [(int(r["chunk_id"]), str(r["text"])) for r in rows]

    return run(_query())


def test_subset_rebuild_replaces_only_selected_refs(indexed_world):
    service, db = indexed_world
    before_b = _chunks(db, _REF_B)
    assert before_b

    # 变更 A 的投影正文，然后只重建 A。
    async def _mutate():
        writer = LibrarySearchWriter(db)
        await writer.upsert(
            ref=_REF_A,
            kind="clip",
            title="向量检索",
            body="全新内容甲，已被更新。",
            url=None,
        )

    run(_mutate())
    result = run(service.rebuild_subset([_REF_A]))
    assert result["status"] == "done"
    assert result["total"] == 1
    assert result["updated"] == 1
    assert result["missing"] == []

    chunks_a = _chunks(db, _REF_A)
    assert any("全新内容甲" in text for _cid, text in chunks_a)
    # 其余 refs 的分块原封不动（chunk_id + text 均不变）。
    assert _chunks(db, _REF_B) == before_b


def test_subset_reports_missing_refs_honestly(indexed_world):
    service, db = indexed_world
    before = _chunks(db, _REF_A), _chunks(db, _REF_B)
    result = run(service.rebuild_subset(["library:does-not-exist"]))
    assert result["updated"] == 0
    assert result["missing"] == ["library:does-not-exist"]
    assert (_chunks(db, _REF_A), _chunks(db, _REF_B)) == before


def test_subset_pause_and_resume_via_cursor(indexed_world, monkeypatch):
    service, db = indexed_world
    # 每页 1 个 ref：首页完成后的第二个安全点请求暂停。
    monkeypatch.setattr("lumirss.rag._SUBSET_PAGE", 1)
    checkpoints = {"n": 0}

    async def _pause_hook(_job_id):
        checkpoints["n"] += 1
        if checkpoints["n"] >= 2:
            await service._job_pause_latest_running()  # noqa: SLF001 — 测试注入

    service._pause_hook = _pause_hook  # noqa: SLF001 — 测试注入
    paused = run(service.rebuild_subset([_REF_A, _REF_B]))
    assert paused["status"] == "paused"
    assert paused["jobId"]
    service._pause_hook = None

    job = run(service.job_get(paused["jobId"]))
    assert job["kind"] == "rebuild_subset"
    assert job["status"] == "paused"
    assert job["cursor"]["pending"] == [_REF_B]  # A 已完成，B 待续
    assert job["stats"]["done"] == 1

    resumed = run(service.resume_subset(paused["jobId"]))
    assert resumed["status"] == "done"
    job = run(service.job_get(paused["jobId"]))
    assert job["status"] == "done"
    assert job["stats"]["done"] == 2
    assert not (job["cursor"] or {}).get("pending")  # 游标耗尽
    # 两个 ref 的内容都在索引中（分块真实重建）。
    assert any("旧内容甲" in text for _cid, text in _chunks(db, _REF_A))
    assert any("内容乙保持稳定" in text for _cid, text in _chunks(db, _REF_B))


def test_subset_over_http(indexed_world, client):
    service, db = indexed_world
    before_b = _chunks(db, _REF_B)
    created = client.post("/api/v1/rag/rebuild/refs", json={"refs": [_REF_A]})
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "done"
    job_id = body["jobId"]
    status = client.get(f"/api/v1/rag/rebuild/refs/{job_id}")
    assert status.status_code == 200
    view = status.json()
    assert view["kind"] == "rebuild_subset"
    assert view["done"] == 1
    assert view["total"] == 1
    assert _chunks(db, _REF_B) == before_b
    # 未知作业 → 404。
    assert client.get("/api/v1/rag/rebuild/refs/job-none").status_code == 404
    # 暂停已完成的作业：诚实 paused=false（无可暂停的 running 行）。
    done_pause = client.post(f"/api/v1/rag/rebuild/refs/{job_id}/pause")
    assert done_pause.status_code == 200
    assert done_pause.json()["paused"] is False
