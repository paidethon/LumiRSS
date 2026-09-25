"""N157 索引版本切换测试 —— 模型可配置 + 原子换模型 swap。

- 切换（set_model）只写 settings：live 模型不变，旧索引继续可查；
- rebuild 在新模型下 staging（staged 行带 NEW model_id），swap 原子
  替换（含 vec 表维度重建）；旧索引在 swap 前全程可读；
- 查询恒按 LIVE 模型过滤 + 维度校验：rebuild 中途绝无混合结果；
- GET index-version：{modelId, dim, rowCounts, configuredModel}。
"""

import asyncio
import tempfile

import pytest

from lumirss.rag import (
    DEFAULT_MODEL_DIM,
    DEFAULT_MODEL_ID,
    MODEL_CATALOG,
    RagService,
    _promote_staged_index,
    _stage_rows,
)
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database

_NEW_MODEL = "intfloat/multilingual-e5-small"
_NEW_DIM = MODEL_CATALOG[_NEW_MODEL]


def run(coro):
    return asyncio.run(coro)


def _install_fake_embedders(monkeypatch) -> None:
    """按模型声明维度产出确定性向量的类级 fake（所有实例生效）。"""
    from lumirss.rag import EmbeddingService

    async def fake_embed(self, texts):
        dim = self._expected_dim
        vectors = []
        for text in texts:
            vector = [0.0] * dim
            vector[len(text) % dim] = 1.0
            vectors.append(vector)
        return vectors

    monkeypatch.setattr(EmbeddingService, "embed", fake_embed)


async def _seed(db: Database, count: int = 2) -> None:
    await db.migrate()
    writer = LibrarySearchWriter(db)
    for i in range(count):
        await writer.upsert(
            ref=f"library:2a8df3e0-1f2a-4c3d-9e4f-{i:012d}",
            kind="clip",
            title=f"文档{i}",
            body=f"第{i}篇正文内容，足够分块。",
            url=None,
        )


def _make_service(monkeypatch) -> tuple[RagService, Database, tempfile.TemporaryDirectory]:
    _install_fake_embedders(monkeypatch)
    tmp = tempfile.TemporaryDirectory()
    db = Database(f"{tmp.name}/lumi.sqlite")
    run(_seed(db))
    service = RagService(db, db_path=f"{tmp.name}/lumi.sqlite")
    run(service._set_setting("rag_enabled", "1"))  # noqa: SLF001 — 测试接缝
    return service, db, tmp


def _teardown(handle) -> None:
    handle.cleanup()


def test_switch_then_rebuild_swaps_model_atomically(monkeypatch):
    service, db, handle = _make_service(monkeypatch)
    try:
        built = run(service.rebuild())
        assert built["status"] == "done"

        version = run(service.index_version())
        assert version["modelId"] == DEFAULT_MODEL_ID
        assert version["dim"] == DEFAULT_MODEL_DIM
        assert version["rowCounts"] == {DEFAULT_MODEL_ID: version["rowCounts"][DEFAULT_MODEL_ID]}

        # 切换：只写 settings，live 模型不变。
        switched = run(service.set_model(_NEW_MODEL))
        assert switched == {"modelId": _NEW_MODEL, "dim": _NEW_DIM}
        version = run(service.index_version())
        assert version["modelId"] == DEFAULT_MODEL_ID  # 旧索引仍 live
        assert version["configuredModel"] == _NEW_MODEL

        # 未知模型诚实拒绝。
        from lumirss.rag import RagModelUnknown

        with pytest.raises(RagModelUnknown):
            run(service.set_model("acme/nonexistent-model"))

        # rebuild：新模型 staging → 原子 swap。
        rebuilt = run(service.rebuild())
        assert rebuilt["status"] == "done"
        assert rebuilt["modelId"] == _NEW_MODEL

        version = run(service.index_version())
        assert version["modelId"] == _NEW_MODEL
        assert version["dim"] == _NEW_DIM
        assert set(version["rowCounts"]) == {_NEW_MODEL}

        async def _check():
            rows = await db.fetch_all(
                "SELECT DISTINCT model_id FROM rag_chunks"
            )
            return {str(r["model_id"]) for r in rows}

        assert run(_check()) == {_NEW_MODEL}
        # vec 表已按新维度重建。
        assert service._stored_vec_dim() == _NEW_DIM
        # 搜索按新模型工作（语义可用，fake embedder 产出 384 维）。
        result = run(service.search("文档"))
        assert result["modelId"] == _NEW_MODEL
        assert result["semanticUsed"] is True
    finally:
        _teardown(handle)


def test_old_index_readable_during_rebuild_and_no_mixing(monkeypatch):
    service, db, handle = _make_service(monkeypatch)
    try:
        run(_seed(db, count=20))  # 20 docs → 至少两个 staging 安全点
        assert run(service.rebuild())["status"] == "done"

        # 切换 + 在第二个安全点暂停（第一页 staged 后触发）。
        run(service.set_model(_NEW_MODEL))
        paused_once = {"done": False}

        async def hook(job_id):
            if paused_once["done"]:
                return
            paused_once["done"] = True
            await service._job_pause_request(job_id)

        service._pause_hook = hook  # noqa: SLF001 — 测试接缝
        result = run(service.rebuild())
        assert result["status"] == "paused"

        async def _models():
            live = await db.fetch_all("SELECT DISTINCT model_id FROM rag_chunks")
            staged = await db.fetch_all(
                "SELECT DISTINCT model_id FROM rag_rebuild_stage"
            )
            return (
                {str(r["model_id"]) for r in live},
                {str(r["model_id"]) for r in staged},
            )

        live_models, staged_models = run(_models())
        assert live_models == {DEFAULT_MODEL_ID}  # 旧索引原封不动
        assert staged_models == {_NEW_MODEL}  # staged 行带 NEW model_id

        # rebuild 中途：查询按 LIVE（旧）模型；绝不混入 staged 的新行。
        search = run(service.search("正文"))
        assert search["modelId"] == DEFAULT_MODEL_ID
        assert {item["model_id"] for item in search["items"]} <= {DEFAULT_MODEL_ID}
        version = run(service.index_version())
        assert version["modelId"] == DEFAULT_MODEL_ID

        # resume 从游标继续（同目标模型），完成后 live 切到新模型。
        service._pause_hook = None  # noqa: SLF001
        resumed = run(service.resume_rebuild())
        assert resumed["status"] == "done"
        version = run(service.index_version())
        assert version["modelId"] == _NEW_MODEL
        assert set(version["rowCounts"]) == {_NEW_MODEL}
    finally:
        _teardown(handle)


def test_dim_mismatch_query_degrades_without_mixed_results(monkeypatch):
    service, db, handle = _make_service(monkeypatch)
    try:
        run(service.rebuild())  # 默认 512 维索引

        # 直接以 NEW 模型 staged + swap（384 维）：vec 表随之重建。
        async def _stage_new():
            from lumirss.rag import _stage_ensure

            await db.migrate()
            await asyncio.to_thread(_stage_ensure, service)
            _stage_rows(
                service,
                [("library:2a8df3e0-1f2a-4c3d-9e4f-000000000000", "clip", "文档0", "新维度正文", "hash")],
                [[0.5] * _NEW_DIM],
                {},
                _NEW_MODEL,
            )

        run(_stage_new())
        run(asyncio.to_thread(_promote_staged_index, service, _NEW_MODEL, _NEW_DIM))
        assert service._stored_vec_dim() == _NEW_DIM

        # 查询向量维度不符（fake 512 维 vs 索引 384 维）→ 语义腿诚实降级，
        # 词法腿只取 live 模型 → 结果集单一模型，绝无混合。
        from lumirss.rag import EmbeddingService

        async def stale_dim_embed(self, texts):
            return [[0.0] * DEFAULT_MODEL_DIM for _ in texts]

        monkeypatch.setattr(EmbeddingService, "embed", stale_dim_embed)
        result = run(service.search("正文"))
        assert result["modelId"] == _NEW_MODEL
        assert result["semanticUsed"] is False
        assert {item["model_id"] for item in result["items"]} <= {_NEW_MODEL}
    finally:
        _teardown(handle)


def test_env_override_pins_model(monkeypatch):
    monkeypatch.setenv("LUMI_RAG_MODEL_ID", _NEW_MODEL)
    _install_fake_embedders(monkeypatch)
    handle = tempfile.TemporaryDirectory()
    try:
        db = Database(f"{handle.name}/lumi.sqlite")
        run(_seed(db, count=1))
        service = RagService(db, db_path=f"{handle.name}/lumi.sqlite")
        model_id, dim = run(service.configured_model())
        assert (model_id, dim) == (_NEW_MODEL, _NEW_DIM)
        version = run(service.index_version())
        assert version["configuredModel"] == _NEW_MODEL
    finally:
        handle.cleanup()
