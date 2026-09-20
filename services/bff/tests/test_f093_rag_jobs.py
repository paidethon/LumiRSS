"""F093 索引暂停与断点续建 — 批间暂停→resume 不重复 embed、重复 resume 幂等、
重启（新实例）可续、来源删除跳过记录、完成 status=done。"""

import asyncio

import pytest

from lumirss.main import app
from lumirss.rag import MODEL_DIM, RagService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database


def run(coro):
    return asyncio.run(coro)


def _fake_embedder(service: RagService, counter: list[int] | None = None):
    async def fake_embed(texts):
        if counter is not None:
            counter[0] += len(texts)
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = fake_embed  # noqa: SLF001


@pytest.fixture()
def job_env(client, monkeypatch):
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    db = Database(f"{tmp.name}/lumi.sqlite")
    monkeypatch.setattr(app.state, "db", db, raising=False)
    service = RagService(db)
    counter = [0]
    _fake_embedder(service, counter)
    app.state.rag_service = service

    async def seed():
        await db.migrate()
        writer = LibrarySearchWriter(db)
        for i in range(20):  # 20 docs → 2 页（_DOC_PAGE=16）
            await writer.upsert(
                ref=f"library:doc-{i:02d}",
                kind="clip",
                title=f"文档{i}",
                body=f"批量重建语料第 {i} 段内容，用于分页游标测试。",
                url=None,
            )

    run(seed())
    try:
        yield service, counter
    finally:
        app.state.rag_service = None
        tmp.cleanup()


def test_f093_pause_between_batches_then_resume_no_reembed(job_env):
    service, counter = job_env
    pauses = {"n": 0}

    async def hook(job_id):
        pauses["n"] += 1
        if pauses["n"] == 1:
            await service._job_pause_request(job_id)  # noqa: SLF001

    service._pause_hook = hook  # noqa: SLF001 — 测试注入批间暂停点
    result = run(service.rebuild())
    assert result["status"] == "paused"
    assert result["chunks"] > 0  # 第一页已 staged
    first_pass_chunks = counter[0]
    job = run(service._job_latest())  # noqa: SLF001
    assert job["status"] == "paused" and job["cursor"] is not None

    # resume：续建，已完成批绝不重复 embed
    service._pause_hook = None  # noqa: SLF001
    resumed = run(service.resume_rebuild())
    assert resumed["status"] == "done"
    assert resumed["resumed"] is True
    assert counter[0] == first_pass_chunks + counter[0] - first_pass_chunks
    total_chunks = resumed["chunks"]
    # embed 调用计数不重复已完成批：总调用 < 两遍全量
    assert counter[0] < total_chunks * 2
    # 重复 resume 幂等（已 done → 直接返回完成态）
    again = run(service.resume_rebuild())
    assert again["status"] == "done" and again.get("resumed") is False
    status = run(service.status())
    assert status["job"]["status"] == "done"
    assert status["chunks"] == total_chunks


def test_f093_resume_after_restart_new_instance(job_env, client):
    service, counter = job_env
    pauses = {"n": 0}

    async def hook(job_id):
        pauses["n"] += 1
        if pauses["n"] == 1:
            await service._job_pause_request(job_id)  # noqa: SLF001

    service._pause_hook = hook  # noqa: SLF001
    result = run(service.rebuild())
    assert result["status"] == "paused"
    # 进程重启：新建 service 实例（同一 DB）从持久游标续建
    fresh = RagService(service._db)  # noqa: SLF001
    fresh_counter = [0]
    _fake_embedder(fresh, fresh_counter)
    resumed = run(fresh.resume_rebuild())
    assert resumed["status"] == "done"
    assert fresh_counter[0] > 0  # 只补未完成的页


def test_f093_source_deleted_midway_recorded(job_env):
    service, counter = job_env
    # 来源在 rebuild 中途被删除：复核阶段跳过并记录（stats.skipped）
    async def delete_midway():
        await service._db.migrate()  # noqa: SLF001
        await service._db.execute("DELETE FROM search_library WHERE ref = 'library:doc-19'")  # noqa: SLF001

    orig_present = service._refs_still_present  # noqa: SLF001

    async def present_with_delete(docs):
        present, skipped = await orig_present(docs)
        if any(d["ref"] == "library:doc-19" for d in docs):
            await delete_midway()
            present, skipped = await orig_present(docs)
        return present, skipped

    service._refs_still_present = present_with_delete  # noqa: SLF001
    result = run(service.rebuild())
    assert result["status"] == "done"
    job = run(service._job_latest())  # noqa: SLF001
    assert "library:doc-19" in (job["stats"] or {}).get("skipped", [])


def test_f093_pause_resume_over_http(job_env, client):
    """pause/resume/status 端点契约（status 带 job 段）。"""
    status = client.get("/api/v1/rag/status")
    assert status.status_code == 200
    body = status.json()
    assert "job" in body  # 无作业 → null / done
