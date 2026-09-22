"""F029 术语命中预览 —— 匹配规则、prompt 一致性、空表行为不变。"""

import asyncio
import json

from lumirss.ai_provider import AiUpstreamError
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.entryref import encode_entry_ref
from lumirss.glossary_hits import (
    compute_hits,
    format_glossary_prompt_block,
)
from lumirss.models import EntryDetail


def run(coroutine):
    return asyncio.run(coroutine)


TERMS = [
    {"term": "LLM", "translation": "大语言模型"},
    {"term": "LangModel", "translation": "语言模型"},
    {"term": "量子纠缠", "translation": "quantum entanglement"},
    {"term": "检索增强生成", "translation": "RAG"},
]


def test_f029_matching_rules():
    body = "本文介绍 LLM 与量子纠缠。文中还提到 LangModelX 不是 LLM 的子串问题。"
    hits = {h["term"]: h for h in compute_hits(body, TERMS)}
    # 大小写不敏感（拉丁词）：llm 命中 LLM
    plain = compute_hits("这是 llm 简介。", TERMS)
    assert any(h["term"] == "LLM" for h in plain)
    # 词边界不误中：LangModelX 不算 LangModel 命中
    hits2 = compute_hits("LangModelX 是另一个词。", TERMS)
    assert all(h["term"] != "LangModel" for h in hits2)
    # 中文子串命中
    assert "量子纠缠" in hits
    assert hits["量子纠缠"]["translation"] == "quantum entanglement"
    # 无命中 → 空表
    assert compute_hits("完全没有相关词。", TERMS) == []
    # 术语表为空 → 空表 + 空 prompt 块（行为不变）
    assert compute_hits(body, []) == []
    assert format_glossary_prompt_block([]) == ""
    # 重叠词取最长：两个术语共含前缀时，长词胜出
    overlap_terms = [
        {"term": "GPT", "translation": "生成式预训练"},
        {"term": "GPT-5", "translation": "第五代"},
    ]
    overlap_hits = compute_hits("GPT-5 发布了。GPT 也在。", overlap_terms)
    by_term = {h["term"]: h["count"] for h in overlap_hits}
    assert by_term.get("GPT-5") == 1 and by_term.get("GPT") == 1


def test_f029_prompt_block_matches_generation_request(tmp_path, monkeypatch):
    """prompt 附加内容与 preview 端点输出一致（mock provider 记录请求）。"""
    from fastapi.testclient import TestClient

    from lumirss.main import app

    db_path = tmp_path / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))

    REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000f2f")
    BODY = "本文讨论 LLM 与量子纠缠。"

    class FakeAdapter:
        async def get_entry(self, item_id):
            return EntryDetail(
                entryRef=REF,
                title="T",
                feedTitle="F",
                contentText=BODY,
                contentHtml=f"<p>{BODY}</p>",
                read=False,
                starred=False,
            )

    captured: list[str] = []

    class RecordingProvider:
        async def complete(self, *, messages):
            captured.append(json.dumps(messages, ensure_ascii=False))
            raise AiUpstreamError("stop after capture")

    async def factory(base_url: str, model: str):
        return RecordingProvider()

    with TestClient(app) as client:
        # 0067： lifespan 绑定的是 RoutingDatabase（按请求身份路由）；
        # 直连 DB 断言按 conftest 同款约定覆盖为普通 Database
        #（= LUMIRSS_DB_PATH 控制库文件），无需用户上下文。
        from lumirss.storage import Database as _Database

        app.state.db = _Database(db_path)
        app.state.freshrss_adapter = FakeAdapter()
        from lumirss.ai_translation import TranslationService

        run(AiSettingsStore(app.state.db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m")
        ))
        service = TranslationService(
            db=app.state.db,
            adapter=FakeAdapter(),
            settings_store=AiSettingsStore(app.state.db),
            provider_factory=factory,
        )
        app.state.translation_service = service

        # 现役术语表（写入 Lumi 库）
        run(app.state.db.migrate())
        for item in TERMS:
            run(app.state.db.execute(
                "INSERT INTO glossary_terms (id, term, definition, source_ref, created_at, updated_at) VALUES (?, ?, ?, NULL, '2026-09-19T00:00:00Z', '2026-09-19T00:00:00Z')",
                (f't-{item["term"]}', item["term"], item["translation"]),
            ))

        # 预览端点
        preview = client.post(f"/api/v1/entries/{REF}/glossary-hits")
        assert preview.status_code == 200, preview.text
        preview_body = preview.json()
        assert any(h["term"] == "LLM" for h in preview_body["hits"])
        preview_block = preview_body["promptBlock"]
        assert "术语表：" in preview_block
        assert "LLM→大语言模型" in preview_block

        # 生成端点（provider 捕获请求后抛稳定错误）
        with__ = client.post(f"/api/v1/entries/{REF}/translation")
        assert with__.status_code == 502
        assert captured, "provider 未被调用"
        sent = captured[0].replace('\\n', '\n')
        # prompt 附加内容与 preview 端点同一函数产出：逐字一致
        assert preview_block in sent
