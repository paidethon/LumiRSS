"""F067 多文观点对照 — schema 失败 502、正常渲染、quote 核验
（不存在 → verified:false，负向：不能全 verified）、缺失条目跳过、
材料不足 422。上游走 httpx MockTransport，可断言 prompt。"""

import asyncio
import json as _json

import httpx

from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.storage import Database


def _ref(n: int) -> str:
    return encode_entry_ref(f"tag:google.com,2005:reader/item/00000000000000{n:02x}")


REF_A, REF_B, REF_C = _ref(0xA1), _ref(0xB2), _ref(0xC3)
TEXT_A = "观点甲认为开放标准更重要。" * 10
TEXT_B = "观点乙认为商业生态更重要。" * 10
TEXT_C = "观点丙认为两者可以兼容。" * 10

VALID_JSON = _json.dumps(
    {
        "common_points": ["两者都谈到了标准"],
        "differences": [
            {
                "topic": "路线",
                "positions": [
                    {"entry": 1, "claim": "甲支持开放标准"},
                    {"entry": 2, "claim": "乙支持商业生态"},
                    {"entry": 9, "claim": "越界编号应被丢弃"},
                ],
            }
        ],
        "evidence": [
            {"entry": 1, "quote": "观点甲认为开放标准更重要"},
            {"entry": 2, "quote": "这句引文在原文中并不存在"},
        ],
        "uncertainties": ["样本有限"],
    },
    ensure_ascii=False,
)


class CmpAdapter:
    def __init__(self, entries: dict[str, str]):
        self.entries = entries  # ref → (title, text)

    async def get_entry(self, item_id: str):
        from lumirss.entryref import decode_entry_ref

        for ref, (title, text) in self.entries.items():
            if decode_entry_ref(ref) == item_id:
                return EntryDetail(
                    entryRef=ref,
                    title=title,
                    feedTitle="源",
                    contentText=text,
                    contentHtml=f"<p>{text}</p>",
                    read=False,
                    starred=False,
                )
        from lumirss.adapters.freshrss import EntryNotFound

        raise EntryNotFound("nope")


def _wire(tmp_path, monkeypatch, reply: str):
    monkeypatch.setenv("AI_API_KEY", "test-key-f067")
    db = Database(tmp_path / "lumi.sqlite")

    async def _cfg():
        from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate

        await AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m-f067")
        )

    asyncio.run(_cfg())
    app.state.db = db
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": reply}}]},
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return db, captured


def _entries(with_c: bool = False):
    entries = {REF_A: ("文章甲", TEXT_A), REF_B: ("文章乙", TEXT_B)}
    if with_c:
        entries[REF_C] = ("文章丙", TEXT_C)
    return CmpAdapter(entries)


def test_f067_compare_success_quote_verification_and_citation_filter(
    client, tmp_path, monkeypatch
):
    db, captured = _wire(tmp_path, monkeypatch, VALID_JSON)
    app.state.freshrss_adapter = _entries()

    resp = client.post("/api/v1/entries/compare", json={"entryRefs": [REF_A, REF_B]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 材料映射（编号 → ref/标题）
    assert body["materials"][0] == {"index": 1, "entryRef": REF_A, "title": "文章甲"}
    # 越界 position（entry=9）被服务端丢弃
    positions = body["differences"][0]["positions"]
    assert [p["entry"] for p in positions] == [1, 2]
    # quote 核验：存在的 → verified:true；不存在的 → verified:false
    verified = {e["quote"]: e["verified"] for e in body["evidence"]}
    assert verified["观点甲认为开放标准更重要"] is True
    assert verified["这句引文在原文中并不存在"] is False
    # 负向：不是全部 verified
    assert not all(e["verified"] for e in body["evidence"])

    # prompt 只含所选材料（甲、乙），有编号分隔
    user_prompt = captured[0]["messages"][-1]["content"]
    assert "文章甲" in user_prompt and "文章乙" in user_prompt
    assert "（[2] 结束）" in user_prompt

    # 缺失条目诚实跳过：第三篇不在 adapter 中
    resp2 = client.post(
        "/api/v1/entries/compare", json={"entryRefs": [REF_A, REF_B, REF_C]}
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["skipped"] == [{"entryRef": REF_C, "reason": "entry_not_found"}]
    assert [m["index"] for m in body2["materials"]] == [1, 2]


def test_f067_invalid_schema_502_and_material_insufficient(client, tmp_path, monkeypatch):
    # 1) 模型输出不是 JSON → 502 comparison_invalid
    db, _captured = _wire(tmp_path, monkeypatch, "抱歉，我无法以 JSON 输出。")
    app.state.freshrss_adapter = _entries()
    resp = client.post("/api/v1/entries/compare", json={"entryRefs": [REF_A, REF_B]})
    assert resp.status_code == 502
    assert resp.json()["error"]["type"] == "comparison_invalid"

    # 2) JSON 结构缺字段（common_points 是对象不是数组）→ 502
    bad = _json.dumps({"common_points": {"a": 1}}, ensure_ascii=False)
    _db2, _c2 = _wire(tmp_path, monkeypatch, bad)
    app.state.freshrss_adapter = _entries()
    resp2 = client.post("/api/v1/entries/compare", json={"entryRefs": [REF_A, REF_B]})
    assert resp2.status_code == 502
    assert resp2.json()["error"]["type"] == "comparison_invalid"

    # 3) 材料不足：两篇都极短（<50 字）→ 422 material_insufficient
    short_adapter = CmpAdapter(
        {
            REF_A: ("短甲", "太短"),
            REF_B: ("短乙", "也很短"),
        }
    )
    app.state.freshrss_adapter = short_adapter
    resp3 = client.post("/api/v1/entries/compare", json={"entryRefs": [REF_A, REF_B]})
    assert resp3.status_code == 422
    assert resp3.json()["error"]["type"] == "material_insufficient"

    # 4) 边界：1 篇 → 422（min_length=2）
    resp4 = client.post("/api/v1/entries/compare", json={"entryRefs": [REF_A]})
    assert resp4.status_code == 422
