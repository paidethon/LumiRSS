"""F069 文章阅读自测 — 题目响应无答案（负向）、评分正确/错误、
evidence 失配丢题、过短 422、过期会话 404、条目删除后会话残留无害。
上游走 httpx MockTransport。"""

import asyncio
import json as _json

import httpx

from lumirss.ai_quiz import QuizSessionStore
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.storage import Database

REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000069")
CONTENT = "自测用的长正文。" * 80  # > 400 字

VALID_QUIZ = _json.dumps(
    {
        "questions": [
            {
                "question": "文章的核心主题是什么？",
                "options": ["自测", "烹饪", "旅行", "音乐"],
                "answer_index": 0,
                "explanation": "全文围绕自测展开。",
                "evidence_quote": "自测用的长正文。自测用的长正文。",
            },
            {
                "question": "这篇文章的文体更接近？",
                "options": ["说明文", "菜谱", "游记", "乐评"],
                "answer_index": 1,
                "explanation": "无关干扰项说明。",
                "evidence_quote": "这句话在正文里根本不存在",
            },
        ]
    },
    ensure_ascii=False,
)


def _wire(tmp_path, monkeypatch, reply: str):
    monkeypatch.setenv("AI_API_KEY", "test-key-f069")
    db = Database(tmp_path / "lumi.sqlite")

    async def _cfg():
        from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate

        await AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="m-f069")
        )

    asyncio.run(_cfg())
    app.state.db = db
    captured: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(_json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    from lumirss.models import EntryDetail

    class Adapter:
        async def get_entry(self, item_id: str):
            return EntryDetail(
                entryRef=REF,
                title="自测文章",
                feedTitle="源",
                contentText=CONTENT,
                contentHtml=f"<p>{CONTENT}</p>",
                read=False,
                starred=False,
            )

    app.state.freshrss_adapter = Adapter()
    return db, captured


def test_f069_generate_response_has_no_answers_and_drops_bad_evidence(
    client, tmp_path, monkeypatch
):
    db, _captured = _wire(tmp_path, monkeypatch, VALID_QUIZ)
    resp = client.post(f"/api/v1/entries/{REF}/quiz", json={"count": 3})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 第 2 题证据核验失败 → 整题丢弃；第 1 题保留
    assert len(body["questions"]) == 1
    question = body["questions"][0]
    # 负向契约：响应绝不含答案/解析/证据字段
    assert set(question.keys()) == {"index", "question", "options"}
    assert "answer" not in _json.dumps(body).lower() or "answerIndex" not in _json.dumps(body)
    assert "answerIndex" not in _json.dumps(body)
    assert "explanation" not in _json.dumps(body)
    assert "evidenceQuote" not in _json.dumps(body)

    # 评分：答对 + 答错
    quiz_id = body["quizId"]
    grade = client.post(f"/api/v1/quiz/{quiz_id}/grade", json={"answers": [1]})
    assert grade.status_code == 200, grade.text
    item = grade.json()["items"][0]
    assert item["correct"] is False
    assert item["answerIndex"] == 0
    assert item["explanation"] == "全文围绕自测展开。"
    assert item["evidenceQuote"] == "自测用的长正文。自测用的长正文。"
    grade2 = client.post(f"/api/v1/quiz/{quiz_id}/grade", json={"answers": [0]})
    assert grade2.json()["items"][0]["correct"] is True

    # 条目删除后会话残留无害：评分不触达 FreshRSS，仍可判分
    async def _wipe_entries():
        await db.execute("DELETE FROM search_entries")

    asyncio.run(_wipe_entries())
    grade3 = client.post(f"/api/v1/quiz/{quiz_id}/grade", json={"answers": [0]})
    assert grade3.status_code == 200
    assert grade3.json()["items"][0]["correct"] is True


def test_f069_too_short_422_all_dropped_422_and_expired_404(client, tmp_path, monkeypatch):
    db, _captured = _wire(tmp_path, monkeypatch, VALID_QUIZ)

    # 1) 正文过短（<400 字）→ 422 material_insufficient
    from lumirss.models import EntryDetail

    class ShortAdapter:
        async def get_entry(self, item_id: str):
            return EntryDetail(
                entryRef=REF,
                title="短文",
                feedTitle="源",
                contentText="太短了。",
                contentHtml="<p>太短了。</p>",
                read=False,
                starred=False,
            )

    app.state.freshrss_adapter = ShortAdapter()
    short = client.post(f"/api/v1/entries/{REF}/quiz", json={"count": 3})
    assert short.status_code == 422
    assert short.json()["error"]["type"] == "material_insufficient"

    # 2) 全部题目证据核验失败 → 422 quiz_invalid
    app.state.freshrss_adapter = _long_adapter()
    all_bad = _json.dumps(
        {
            "questions": [
                {
                    "question": "q?",
                    "options": ["a", "b"],
                    "answer_index": 0,
                    "explanation": "e",
                    "evidence_quote": "不存在的证据文字内容",
                }
            ]
        },
        ensure_ascii=False,
    )
    _patch_transport(all_bad)
    invalid = client.post(f"/api/v1/entries/{REF}/quiz", json={"count": 3})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["type"] == "quiz_invalid"

    # 3) count 越界 → 422
    assert (
        client.post(f"/api/v1/entries/{REF}/quiz", json={"count": 2}).status_code
        == 422
    )

    # 4) 过期/不存在的会话评分 → 404；直删行模拟过期清理
    app.state.freshrss_adapter = _long_adapter()
    _patch_transport(VALID_QUIZ)
    ok = client.post(f"/api/v1/entries/{REF}/quiz", json={"count": 3})
    quiz_id = ok.json()["quizId"]
    store = QuizSessionStore(db)

    async def _expire():
        await db.execute("DELETE FROM quiz_sessions")

    asyncio.run(_expire())
    assert asyncio.run(store.get(quiz_id)) is None
    gone = client.post(f"/api/v1/quiz/{quiz_id}/grade", json={"answers": [0]})
    assert gone.status_code == 404
    assert gone.json()["error"]["type"] == "quiz_not_found"


def _long_adapter():
    from lumirss.models import EntryDetail

    class LongAdapter:
        async def get_entry(self, item_id: str):
            return EntryDetail(
                entryRef=REF,
                title="自测文章",
                feedTitle="源",
                contentText=CONTENT,
                contentHtml=f"<p>{CONTENT}</p>",
                read=False,
                starred=False,
            )

    return LongAdapter()


def _patch_transport(reply: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": reply}}]}
        )

    app.state.http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
