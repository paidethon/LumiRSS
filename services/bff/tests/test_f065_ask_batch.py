"""F065 多篇共同问答 — 范围强制（prompt 只含所选条目）、越界引用过滤、
缺失条目诚实跳过、长度截断、空范围 422。上游走 httpx MockTransport，
prompt 可断言，绝不真实调用。"""

import json as _json

import httpx

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.storage import Database


def _ref(item_id: str) -> str:
    return encode_entry_ref(f"tag:google.com,2005:reader/item/{item_id}")


REF_A = _ref("00000000000000a1")
REF_B = _ref("00000000000000b2")
REF_C = _ref("00000000000000c3")

CONTENT_A = "内容甲" * 100
CONTENT_B = "内容乙" * 100
CONTENT_C = "内容丙" * 100


class MultiAdapter:
    def __init__(self, entries: dict[str, EntryDetail], errors: set[str] | None = None):
        self.entries = entries
        self.errors = errors or set()

    async def get_entry(self, item_id: str) -> EntryDetail:
        for ref, detail in self.entries.items():
            from lumirss.entryref import decode_entry_ref

            if decode_entry_ref(ref) == item_id:
                if ref in self.errors:
                    raise RuntimeError("upstream boom")
                return detail
        from lumirss.adapters.freshrss import EntryNotFound

        raise EntryNotFound("nope")


def _detail(title: str, text: str) -> EntryDetail:
    return EntryDetail(
        entryRef="irrelevant",
        title=title,
        feedTitle="源",
        contentText=text,
        contentHtml=f"<p>{text}</p>",
        read=False,
        starred=False,
    )


def _wire(tmp_path, captured: list, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "test-key-f065")
    import asyncio

    from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate

    db = Database(tmp_path / "lumi.sqlite")

    async def _cfg():
        await AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m-f065")
        )

    asyncio.run(_cfg())

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "共同点是 [1] 与 [2]；另外 [99] 不存在。"}}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    app.state.http_client = httpx.AsyncClient(transport=transport)
    return db


def test_f065_scope_enforced_citations_filtered_and_skips(client, tmp_path, monkeypatch):
    captured: list = []
    db = _wire(tmp_path, captured, monkeypatch)
    entries = {
        REF_A: _detail("文章甲", CONTENT_A),
        REF_B: _detail("文章乙", CONTENT_B),
        REF_C: _detail("文章丙", CONTENT_C),
    }
    errors = {REF_C}  # 条目丙上游不可用 → 诚实 skipped
    app.state.db = db
    app.state.freshrss_adapter = MultiAdapter(entries, errors)

    resp = client.post(
        "/api/v1/entries/ask-batch",
        json={"entryRefs": [REF_A, REF_B, REF_C], "question": "这两篇的共同点？"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 越界引用 [99] 被过滤；citations 恒为 refs 子集
    assert [c["index"] for c in body["citations"]] == [1, 2]
    assert {c["entryRef"] for c in body["citations"]} == {REF_A, REF_B}
    # 缺失条目诚实跳过
    assert body["skipped"] == [{"entryRef": REF_C, "reason": "entry_unavailable"}]

    # 范围强制：prompt 只含所选且可用的条目（甲、乙），不含丙
    user_prompt = captured[0]["messages"][-1]["content"]
    assert "[1] 标题：文章甲" in user_prompt
    assert "[2] 标题：文章乙" in user_prompt
    assert "文章丙" not in user_prompt
    assert "内容甲" in user_prompt and "内容乙" in user_prompt
    assert "这两篇的共同点？" in user_prompt
    # 明确分隔
    assert "（[1] 结束）" in user_prompt and "（[2] 结束）" in user_prompt
    assert "（[3] 结束）" not in user_prompt


def test_f065_truncation_bounds_and_validation(client, tmp_path, monkeypatch):
    captured: list = []
    db = _wire(tmp_path, captured, monkeypatch)
    long_text = "很长" * 10000  # 20000 字
    app.state.db = db
    app.state.freshrss_adapter = MultiAdapter({REF_A: _detail("长文", long_text)})

    # 长度截断：maxCharsPerEntry=400 → prompt 中该条目正文 ≤400+上限标记
    resp = client.post(
        "/api/v1/entries/ask-batch",
        json={"entryRefs": [REF_A], "question": "总结", "maxCharsPerEntry": 400},
    )
    assert resp.status_code == 200
    user_prompt = captured[0]["messages"][-1]["content"]
    body_section = user_prompt.split("正文：\n", 1)[1].split("（[1] 结束）", 1)[0]
    assert len(body_section.strip()) <= 400
    assert long_text not in user_prompt  # 被截断，不是全文

    # 空范围（空列表）→ 422（pydantic min_length=1）
    empty = client.post(
        "/api/v1/entries/ask-batch", json={"entryRefs": [], "question": "q"}
    )
    assert empty.status_code == 422

    # 超过 5 篇 → 422
    too_many = client.post(
        "/api/v1/entries/ask-batch",
        json={"entryRefs": [REF_A] * 6, "question": "q"},
    )
    assert too_many.status_code == 422

    # 全部条目不可用 → 422 no_usable_entries
    app.state.freshrss_adapter = MultiAdapter({}, set())
    missing = client.post(
        "/api/v1/entries/ask-batch", json={"entryRefs": [REF_B], "question": "q"}
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "no_usable_entries"
