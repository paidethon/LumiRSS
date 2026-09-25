"""N151-N155 RAG 质量补位 —— 范围回显 / 覆盖分桶 / 分块预览 / 证据强弱 /
引用缺失拦截。

- N151：GET /rag/search?threadId= 服务端解析 F094 范围（结果过滤 +
  effectiveScope kind×refCount）；agent rag_search 结果带 effectiveScope；
  POST /agent/scope-preview 摘要卡（kind × refCount × toolCount）。
- N152：GET /rag/coverage 真实行/作业分桶（unsupported kind + stale）。
- N153：POST /rag/chunk-preview 与已索引行一致（ord/文本/坐标）；
  未知 ref 404。
- N154：agent 回答证据强弱 direct/partial/none（引用文本 vs 主张重叠，
  复用 quote 核验；绝无「置信度」措辞）。
- N155：有主张零有效引用 → unverifiable/no_valid_citations；捏造引用
  → 422 citation_invalid；越界引用 → 403 out_of_scope；摘录模式零
  provider 调用。
"""

import asyncio
import json
import secrets
import time
import uuid

import httpx
import pytest

from lumirss.agent import AgentLoop
from lumirss.agent_store import AgentStore, ToolRegistry
from lumirss.main import app
from lumirss.rag import MODEL_DIM, RagService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.workspaces import WorkspaceStore


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

    service._embedder.embed = fake_embed  # noqa: SLF001 — 测试缝


REF_A = f"library:{uuid.uuid4()}"
REF_B = f"library:{uuid.uuid4()}"
REF_C = f"library:{uuid.uuid4()}"
REF_D = f"library:{uuid.uuid4()}"
TITLE_A = "量子纠错"
BODY_A = "量子计算专题：量子纠错码的原理与Surface Code 的工程实现路径。"
BODY_B = "量子计算专题：量子退相干时间测量与超导比特的标定流程记录。"
BODY_C = "量子计算专题：量子门保真度基准与随机基准测试方法综述。"
BODY_D = "完全无关的博客：记录一次乡村骑行与咖啡冲煮的周末随笔。"


@pytest.fixture()
def rag_env(client, monkeypatch):
    """临时用户库 + 注入 rag_service（与 F100 测试同款装配）。"""
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    db = Database(f"{tmp.name}/lumi.sqlite")
    monkeypatch.setattr(app.state, "db", db, raising=False)
    service = RagService(db, db_path=db.path)
    _fake_embedder(service)
    app.state.rag_service = service
    # agent 缓存服务必须随新库重建（跨测试残留会指向已删除的旧库）。
    app.state.agent_store = None
    app.state.agent_loop = None

    async def seed():
        await db.migrate()
        writer = LibrarySearchWriter(db)
        for ref, title, body in (
            (REF_A, TITLE_A, BODY_A),
            (REF_B, "量子退相干", BODY_B),
            (REF_C, "量子门基准", BODY_C),
            (REF_D, "周末随笔", BODY_D),
        ):
            await writer.upsert(ref=ref, kind="clip", title=title, body=body, url=None)

    run(seed())
    try:
        yield {"db": db, "service": service}
    finally:
        deadline = time.time() + 15
        while getattr(app.state, "agent_tasks", None) and time.time() < deadline:
            time.sleep(0.05)
        app.state.rag_service = None
        service.close()
        tmp.cleanup()


def _create_thread(client) -> str:
    response = client.post("/api/v1/agent/threads")
    assert response.status_code == 201
    return response.json()["id"]


# ---------------------------------------------------------------------------
# N151 effectiveScope（检索范围回显 + 摘要卡）
# ---------------------------------------------------------------------------


def test_n151_scoped_rag_search_filters_and_reports_count(rag_env, client):
    service = rag_env["service"]
    run(service.index_refs([REF_A, REF_B, REF_C, REF_D]))
    thread_id = _create_thread(client)
    patched = client.patch(
        f"/api/v1/agent/threads/{thread_id}",
        json={"scope": {"entryRefs": [REF_A, REF_B]}},
    )
    assert patched.status_code == 200

    scoped = client.get(
        "/api/v1/rag/search",
        params={"q": "量子计算专题", "threadId": thread_id},
    )
    assert scoped.status_code == 200
    body = scoped.json()
    assert {item["ref"] for item in body["items"]} == {REF_A, REF_B}
    assert body["effectiveScope"] == {"kind": "entryRefs", "refCount": 2}

    # 未锁定：全库可见（D 不含查询词，不命中），effectiveScope 诚实 all/None。
    plain = client.get("/api/v1/rag/search", params={"q": "量子计算专题"})
    assert plain.status_code == 200
    plain_body = plain.json()
    assert {item["ref"] for item in plain_body["items"]} == {REF_A, REF_B, REF_C}
    assert plain_body["effectiveScope"] == {"kind": "all", "refCount": None}


def test_n151_scoped_rag_search_unknown_thread_is_404(rag_env, client):
    response = client.get(
        "/api/v1/rag/search", params={"q": "x", "threadId": "missing"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "thread_not_found"


def test_n151_agent_rag_search_reports_effective_scope(tmp_path):
    """agent rag_search 工具结果带 effectiveScope；范围外引用绝不出现。"""
    from lumirss.agent_tools import build_registry

    async def main():
        db = Database(tmp_path / "lumi.sqlite")

        async def seed():
            await db.migrate()
            await LibrarySearchWriter(db).upsert(
                ref=REF_A, kind="clip", title="范围内", body="范围内令牌IN。", url=None
            )
            await LibrarySearchWriter(db).upsert(
                ref=REF_B, kind="clip", title="范围外", body="范围外令牌OUT。", url=None
            )

        await seed()

        class _StubRag:
            def __init__(self) -> None:
                self.items: list[dict] = []

            async def search(self, query, k=6, kind=None):
                return {"items": list(self.items), "semanticUsed": False}

        rag = _StubRag()

        async def rss_search(query, limit=5):
            return []

        registry = build_registry(
            db=db,
            rss_search=rss_search,
            library_search=LibrarySearchWriter(db),
            rag=rag,
            adapter=None,
            library=None,
            workspaces=WorkspaceStore(db),
        )
        registry.set_context({"scope": {"entryRefs": [REF_A]}})

        rag.items = [
            {"ref": REF_B, "text": "范围外令牌OUT", "score": 0.9},
            {"ref": REF_A, "text": "范围内令牌IN", "score": 0.8},
        ]
        result = await registry.invoke_read("rag_search", {"query": "令牌"})
        assert [r["ref"] for r in result["results"]] == [REF_A]
        assert result["citations"] == [REF_A]
        assert result["effectiveScope"] == {"kind": "entryRefs", "refCount": 1}

        # 只剩范围外命中 → 诚实 scope_empty，且范围回显仍在。
        rag.items = [{"ref": REF_B, "text": "范围外令牌OUT", "score": 0.9}]
        empty = await registry.invoke_read("rag_search", {"query": "令牌"})
        assert empty["error"] == "scope_empty"
        assert empty["results"] == []
        assert empty["effectiveScope"] == {"kind": "entryRefs", "refCount": 1}

        # 未锁定 → kind=all。
        registry.set_context({})
        rag.items = [{"ref": REF_B, "text": "范围外令牌OUT", "score": 0.9}]
        unlocked = await registry.invoke_read("rag_search", {"query": "令牌"})
        assert unlocked["effectiveScope"] == {"kind": "all", "refCount": None}
        assert unlocked["citations"] == [REF_B]

    asyncio.run(main())


def test_n151_scope_preview_summary_card(rag_env, client):
    """授权范围摘要卡：kind × refCount × toolCount（服务端解析）。"""
    _create_thread(client)  # 触发 agent loop 装配
    all_scope = client.post("/api/v1/agent/scope-preview", json={})
    assert all_scope.status_code == 200
    all_body = all_scope.json()
    assert all_body["kind"] == "all"
    assert all_body["refCount"] is None
    assert all_body["toolCount"] >= 6

    entry_refs = client.post(
        "/api/v1/agent/scope-preview",
        json={"scope": {"entryRefs": [REF_A, REF_B]}},
    )
    assert entry_refs.status_code == 200
    assert entry_refs.json()["kind"] == "entryRefs"
    assert entry_refs.json()["refCount"] == 2

    missing_ws = client.post(
        "/api/v1/agent/scope-preview",
        json={"scope": {"workspaceId": "no-such-workspace"}},
    )
    assert missing_ws.status_code == 200
    assert missing_ws.json()["kind"] == "workspace"
    assert missing_ws.json()["refCount"] == 0

    readonly = client.post(
        "/api/v1/agent/scope-preview",
        json={
            "scope": {"entryRefs": [REF_A]},
            "toolPolicy": {"mode": "readonly"},
        },
    )
    assert readonly.status_code == 200
    assert readonly.json()["toolCount"] < all_body["toolCount"]


# ---------------------------------------------------------------------------
# N152 coverage 覆盖分桶
# ---------------------------------------------------------------------------


def test_n152_coverage_buckets_unsupported_and_stale(rag_env, client):
    db = rag_env["db"]
    service = rag_env["service"]
    run(service.index_refs([REF_A, REF_B]))

    async def mutate():
        # B 正文变更 → stale；一行空正文 → unsupported(empty_text)；
        # 一条真实作业 skipped 记录 → failed。
        await db.migrate()
        await db.execute(
            "UPDATE search_library SET body = '变更后的正文内容。' WHERE ref = ?",
            (REF_B,),
        )
        await db.execute(
            "INSERT INTO search_library (ref, kind, title, body, url, updated_at)"
            " VALUES (?, 'clip', '空正文', '', NULL, ?)",
            (f"library:{uuid.uuid4()}", "2026-01-01T00:00:00+00:00"),
        )
        await db.execute(
            "INSERT INTO rag_jobs (id, kind, status, cursor_json, stats_json, updated_at)"
            " VALUES (?, 'rebuild', 'done', NULL, ?, ?)",
            (
                f"job-{uuid.uuid4()}",
                json.dumps({"skipped": ["library:gone"]}),
                "2026-01-01T00:00:00+00:00",
            ),
        )

    run(mutate())
    response = client.get("/api/v1/rag/coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["modelId"]
    # 语料 6 行：4 篇种子（有正文）+ 变更 B 仍在 + 1 行空正文。
    # indexable = 有正文的语料（A、B、C、D）= 4；空正文行不可索引。
    assert body["indexable"] == 4
    assert body["indexed"] == 2  # A、B 有当前模型分块
    assert body["stale"] == 1  # B 正文已变更
    assert body["failed"] == 1  # 最近作业 skipped 的真实记录
    assert body["unsupported"]["count"] == 1
    assert body["unsupported"]["kinds"] == [
        {"kind": "clip", "reason": "empty_text"}
    ]


def test_n152_coverage_empty_index_is_honest(rag_env, client):
    response = client.get("/api/v1/rag/coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["indexable"] == 4  # 四篇种子文档均有正文
    assert body["indexed"] == 0
    assert body["stale"] == 0
    assert body["failed"] == 0
    assert body["unsupported"] == {"count": 0, "kinds": []}


# ---------------------------------------------------------------------------
# N153 chunk-preview 分块预览
# ---------------------------------------------------------------------------


async def _fetch_indexed(db, ref):
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT ord, text FROM rag_chunks WHERE ref = ? ORDER BY ord ASC",
        (ref,),
    )
    return [(int(r["ord"]), str(r["text"])) for r in rows]


def test_n153_chunk_preview_matches_indexed_rows(rag_env, client):
    db = rag_env["db"]
    service = rag_env["service"]
    run(service.index_refs([REF_A]))
    stored = run(_fetch_indexed(db, REF_A))
    assert stored, "index_refs should have produced chunks"

    response = client.post("/api/v1/rag/chunk-preview", json={"ref": REF_A})
    assert response.status_code == 200
    body = response.json()
    assert body["ref"] == REF_A
    assert body["kind"] == "clip"
    assert body["title"] == TITLE_A
    assert body["scheme"] == {"maxLen": 800, "overlap": 0}
    assert len(body["chunks"]) == len(stored)
    for i, (chunk, (ord_, text)) in enumerate(
        zip(body["chunks"], stored, strict=True)
    ):
        assert chunk["ord"] == ord_ == i
        assert chunk["text"] == text[:400]
        # 坐标落在原文内；片段规范化后 == 分块内容去掉标题前缀。
        assert 0 <= chunk["charStart"] < chunk["charEnd"] <= len(BODY_A)
        span = " ".join(BODY_A[chunk["charStart"] : chunk["charEnd"]].split())
        prefix = f"{TITLE_A} — "
        content = chunk["text"]
        if content.startswith(prefix):
            content = content[len(prefix) :]
        assert span == " ".join(content.split())


def test_n153_chunk_preview_unknown_ref_404(rag_env, client):
    response = client.post(
        "/api/v1/rag/chunk-preview", json={"ref": "library:nope"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "ref_not_found"


# ---------------------------------------------------------------------------
# N154 证据强弱（agent 回答）
# ---------------------------------------------------------------------------


class FakeProvider:
    def __init__(self, turns: list[dict]) -> None:
        self._turns = list(turns)

    async def chat_completion(self, *, messages, tools=None):
        if not self._turns:
            return {"content": "（脚本回合已用尽）"}
        return self._turns.pop(0)


EVIDENCE = {"lib:e1": "vLLM 量化部署需要十六GB显存，同时建议预留余量防止溢出。"}


@pytest.fixture()
def loop_env(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = AgentStore(db)
    registry = ToolRegistry()

    async def rag_search(args: dict) -> dict:
        return {
            "results": [{"ref": "lib:e1", "text": "证据文本", "score": 0.9}],
            "semanticUsed": False,
            "citations": ["lib:e1"],
        }

    registry.register_read(
        "rag_search",
        "rag tool",
        {"type": "object", "properties": {"query": {"type": "string"}}},
        rag_search,
    )
    return {"db": db, "store": store, "registry": registry}


def _build_loop(env: dict, provider, evidence: dict[str, str]) -> AgentLoop:
    async def evidence_lookup(refs: list[str]) -> dict[str, str]:
        return {ref: evidence.get(ref, "") for ref in refs}

    async def factory():
        return provider

    return AgentLoop(
        env["store"], env["registry"], factory, evidence_lookup=evidence_lookup
    )


def _rag_call(call_id: str) -> dict:
    return {
        "tool_calls": [
            {
                "id": call_id,
                "function": {"name": "rag_search", "arguments": '{"query": "q"}'},
            }
        ]
    }


def test_n154_evidence_strength_direct(loop_env):
    provider = FakeProvider([
        _rag_call("c1"),
        {"content": "vLLM 量化部署需要十六GB显存。"},
    ])
    loop = _build_loop(loop_env, provider, EVIDENCE)
    thread = run(loop_env["store"].create_thread())
    result = run(loop.run_turn(thread["id"], "问"))
    content = result["message"]["content"]
    assert content["evidenceStrength"] == "direct"
    assert "unverifiable" not in content


def test_n154_evidence_strength_partial(loop_env):
    provider = FakeProvider([
        _rag_call("c1"),
        {"content": "vLLM 量化部署需要十六GB显存。这是模型补充的无关想象内容。"},
    ])
    loop = _build_loop(loop_env, provider, EVIDENCE)
    thread = run(loop_env["store"].create_thread())
    result = run(loop.run_turn(thread["id"], "问"))
    content = result["message"]["content"]
    assert content["evidenceStrength"] == "partial"


def test_n154_evidence_strength_none_with_citations(loop_env):
    provider = FakeProvider([
        _rag_call("c1"),
        {"content": "完全无关的其他话题讨论内容。"},
    ])
    loop = _build_loop(loop_env, provider, EVIDENCE)
    thread = run(loop_env["store"].create_thread())
    result = run(loop.run_turn(thread["id"], "问"))
    content = result["message"]["content"]
    assert content["evidenceStrength"] == "none"
    assert content.get("unverifiable") is None


# ---------------------------------------------------------------------------
# N155 引用缺失拦截
# ---------------------------------------------------------------------------


def test_n155_unverifiable_when_zero_valid_citations(loop_env):
    """检索回合 + 文档事实主张 + 零有效引用 → unverifiable 标记。"""

    async def empty_citations(args: dict) -> dict:
        return {"results": [], "semanticUsed": False, "citations": []}

    loop_env["registry"].register_read(
        "rag_search",
        "rag tool",
        {"type": "object", "properties": {"query": {"type": "string"}}},
        empty_citations,
    )
    provider = FakeProvider([
        _rag_call("c1"),
        {"content": "完全无关的其他话题讨论内容。"},
    ])
    loop = _build_loop(loop_env, provider, EVIDENCE)
    thread = run(loop_env["store"].create_thread())
    result = run(loop.run_turn(thread["id"], "问"))
    content = result["message"]["content"]
    assert content["unverifiable"] is True
    assert content["unverifiableReason"] == "no_valid_citations"
    assert content["evidenceStrength"] == "none"


def test_n155_casual_chat_is_never_flagged(loop_env):
    """寒暄回答（无检索、无主张）不产生 unverifiable 误报。"""
    provider = FakeProvider([{"content": "你好呀，今天想聊点什么？"}])
    loop = _build_loop(loop_env, provider, EVIDENCE)
    thread = run(loop_env["store"].create_thread())
    result = run(loop.run_turn(thread["id"], "你好"))
    content = result["message"]["content"]
    assert "unverifiable" not in content
    assert "evidenceStrength" not in content


def test_n154_message_wire_carries_evidence_fields(rag_env, client):
    """assistant content 的新字段经 HTTP 读回原样（契约不丢字段）。"""
    store = AgentStore(rag_env["db"])
    thread_id = _create_thread(client)
    run(
        store.append_message(
            thread_id,
            role="assistant",
            content={
                "text": "部分支持。",
                "evidenceStrength": "partial",
                "unverifiable": True,
                "unverifiableReason": "no_valid_citations",
            },
            citations=[REF_A],
        )
    )
    items = client.get(f"/api/v1/agent/threads/{thread_id}/messages").json()["items"]
    content = items[-1]["content"]
    assert content["evidenceStrength"] == "partial"
    assert content["unverifiable"] is True
    assert content["unverifiableReason"] == "no_valid_citations"


# ---------------------------------------------------------------------------
# N155 同步问答（/api/v1/rag/ask）：422 / 403 / 摘录模式 / unverifiable
# ---------------------------------------------------------------------------


@pytest.fixture()
def ask_env(client, rag_env, monkeypatch):
    """HTTP 问答环境：httpx MockTransport 假 provider + AI 配置。"""
    monkeypatch.setenv("AI_API_KEY", secrets.token_urlsafe(16))
    state = {"answer": ""}
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": state["answer"]}}]},
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate

    async def _cfg():
        await AiSettingsStore(rag_env["db"]).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m-n155")
        )

    run(_cfg())
    try:
        yield {"captured": captured, "state": state, **rag_env}
    finally:
        run(app.state.http_client.aclose())


def test_n155_ask_direct_answer_with_valid_citation(ask_env, client):
    service = ask_env["service"]
    run(service.index_refs([REF_A]))
    thread_id = _create_thread(client)
    ask_env["state"]["answer"] = f"{BODY_A}[1]"
    response = client.post(
        "/api/v1/rag/ask",
        json={
            "question": "量子纠错讲了什么？",
            "refs": [REF_A],
            "threadId": thread_id,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["citations"] == [{"index": 1, "ref": REF_A}]
    assert body["evidenceStrength"] == "direct"
    assert body["unverifiable"] is False
    # 范围回显：threadId 锁定 → 服务端解析 effectiveScope。
    assert body["effectiveScope"] == {"kind": "all", "refCount": None}


def test_n155_ask_partial_and_none_strengths(ask_env, client):
    service = ask_env["service"]
    run(service.index_refs([REF_A]))
    ask_env["state"]["answer"] = f"{BODY_A}这是模型自由发挥的额外内容观点。[1]"
    partial = client.post(
        "/api/v1/rag/ask", json={"question": "问", "refs": [REF_A]}
    )
    assert partial.status_code == 200
    assert partial.json()["evidenceStrength"] == "partial"

    ask_env["state"]["answer"] = "这份材料讲的是另一个完全不同的话题内容。[1]"
    none = client.post(
        "/api/v1/rag/ask", json={"question": "问", "refs": [REF_A]}
    )
    assert none.status_code == 200
    assert none.json()["evidenceStrength"] == "none"
    assert none.json()["unverifiable"] is False


def test_n155_ask_unverifiable_no_valid_citations(ask_env, client):
    service = ask_env["service"]
    run(service.index_refs([REF_A]))
    ask_env["state"]["answer"] = "这份报告的结论是需要预留充足的显存与余量。"
    response = client.post(
        "/api/v1/rag/ask", json={"question": "问", "refs": [REF_A]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unverifiable"] is True
    assert body["reason"] == "no_valid_citations"
    assert body["evidenceStrength"] == "none"
    assert body["citations"] == []
    assert body["answer"]  # 回答仍诚实呈现（不静默丢弃）


def test_n155_ask_fabricated_ref_is_422(ask_env, client):
    response = client.post(
        "/api/v1/rag/ask",
        json={"question": "问", "refs": ["library:does-not-exist"]},
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "citation_invalid"
    assert ask_env["captured"] == []  # provider 零调用


def test_n155_ask_out_of_scope_ref_is_403(ask_env, client):
    thread_id = _create_thread(client)
    patched = client.patch(
        f"/api/v1/agent/threads/{thread_id}",
        json={"scope": {"entryRefs": [REF_A]}},
    )
    assert patched.status_code == 200
    response = client.post(
        "/api/v1/rag/ask",
        json={"question": "问", "refs": [REF_B], "threadId": thread_id},
    )
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "out_of_scope"
    assert ask_env["captured"] == []


def test_n155_ask_excerpt_mode_never_calls_provider(ask_env, client):
    service = ask_env["service"]
    run(service.index_refs([REF_A]))
    response = client.post(
        "/api/v1/rag/ask",
        json={"question": "问", "refs": [REF_A], "mode": "excerpt"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "excerpt"
    assert body["answer"] is None
    assert body["excerpts"], "摘录模式必须返回原文片段"
    assert all(excerpt["ref"] == REF_A for excerpt in body["excerpts"])
    assert ask_env["captured"] == []  # 零 provider 调用

    # 捏造引用在摘录模式下同样拦截（校验先于模式分支）。
    fabricated = client.post(
        "/api/v1/rag/ask",
        json={"question": "问", "refs": ["library:nope"], "mode": "excerpt"},
    )
    assert fabricated.status_code == 422
    assert fabricated.json()["error"]["type"] == "citation_invalid"
