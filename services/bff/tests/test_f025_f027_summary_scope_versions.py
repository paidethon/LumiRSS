"""F025 AI 输入范围控制 + F027 摘要版本。

Fake adapter + 记录型 fake provider：断言收到的正文长度（诚实口径，
不估算 token）与版本保留/切换语义。
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.ai_provider import AiUpstreamError
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_summary import SummaryService
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.storage import Database

LONG_PARAGRAPH = "这是一段足够长的正文内容，用于验证截断。" * 400


def run(coroutine):
    return asyncio.run(coroutine)


class FakeAdapter:
    def __init__(self, detail) -> None:
        self.detail = detail

    async def get_entry(self, item_id) -> EntryDetail:
        return self.detail


class RecordingProvider:
    def __init__(self, summary="摘要结果。") -> None:
        self.summary = summary
        self.received_lengths: list[int] = []
        self.received_texts: list[str] = []
        self.calls = 0

    async def summarize(self, *, text: str, language: str) -> str:
        self.calls += 1
        self.received_lengths.append(len(text))
        self.received_texts.append(text)
        return self.summary + str(self.calls)

    async def complete(self, *, messages):
        return "回答。"


def _detail(text: str) -> EntryDetail:
    ref = encode_entry_ref("tag:google.com,2005:reader/item/00000000000000f1")
    return EntryDetail(
        entryRef=ref,
        title="测试文章",
        feedTitle="测试源",
        contentText=text,
        contentHtml=f"<p>{text}</p>",
        read=False,
        starred=False,
    )


def wire(tmp_path, detail):
    db = Database(tmp_path / "lumi.sqlite")
    provider = RecordingProvider()
    service = SummaryService(
        db=db,
        adapter=FakeAdapter(detail),
        settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    run(AiSettingsStore(db).save(
        AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")
    ))
    return db, provider, service


def _factory(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


def test_f025_max_chars_scopes_provider_input_and_reports_honestly(tmp_path):
    detail = _detail(LONG_PARAGRAPH)
    db, provider, service = wire(tmp_path, detail)
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        scoped = client.post(
            f"/api/v1/entries/{detail.entryRef}/summary", json={"maxChars": 2000}
        )
        assert scoped.status_code == 200, scoped.text
        body = scoped.json()
        assert provider.received_lengths[-1] == 2000  # mock provider 断言收到的正文长度
        assert body["inputChars"] == 2000
        assert body["truncated"] is True

        # 缓存命中：不再调用 provider，但范围口径照常回显
        hit = client.post(
            f"/api/v1/entries/{detail.entryRef}/summary", json={"maxChars": 2000}
        )
        assert hit.status_code == 200
        assert hit.json()["cached"] is True
        assert hit.json()["inputChars"] == 2000
        assert provider.calls == 1

        # None = 现行为（全文 12000 上界）
        full = client.post(f"/api/v1/entries/{detail.entryRef}/summary")
        assert full.status_code == 200
        assert full.json()["truncated"] is True  # 正文 > 12000
        assert full.json()["inputChars"] == len(provider.received_texts[-1])



def test_f025_out_of_bounds_rejected_and_unconfigured_maps_503(tmp_path):
    detail = _detail("短文。")
    db, provider, service = wire(tmp_path, detail)
    # 未配置 provider（删掉设置）→ 显式 503 ai_not_configured
    run(AiSettingsStore(db).save(AiSettingsUpdate(baseUrl="", model="")))
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        out_of_bounds = client.post(
            f"/api/v1/entries/{detail.entryRef}/summary", json={"maxChars": 100}
        )
        assert out_of_bounds.status_code == 422
        upper = client.post(
            f"/api/v1/entries/{detail.entryRef}/summary", json={"maxChars": 50001}
        )
        assert upper.status_code == 422
        unconfigured = client.post(f"/api/v1/entries/{detail.entryRef}/summary")
        assert unconfigured.status_code == 503
        assert unconfigured.json()["error"]["type"] == "ai_not_configured"
        assert provider.calls == 0
        # 取消不发请求（不传 body 也不触发，除非显式 POST 生成——此处全部未配置拦截）
        assert client.get(
            f"/api/v1/entries/{detail.entryRef}/summary"
        ).json()["status"] == "not_generated"


def test_f027_regeneration_keeps_versions_and_activates(tmp_path):
    detail = _detail("版本测试正文。" * 50)
    db, provider, service = wire(tmp_path, detail)
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        first = client.post(f"/api/v1/entries/{detail.entryRef}/summary").json()
        assert first["status"] == "success"
        assert len(first["versions"]) == 1

        # 强制重生成（把成功行置失败 = 现实中的重新生成路径）
        run(db.execute(
            "UPDATE ai_summaries SET status = 'failed' WHERE entry_ref = ?",
            (detail.entryRef,),
        ))
        second = client.post(f"/api/v1/entries/{detail.entryRef}/summary").json()
        assert second["status"] == "success"
        assert len(second["versions"]) == 2  # 重生成保留旧版
        assert second["versions"][0]["summary"] != second["versions"][1]["summary"]

        # 失败不产生新版本
        class ExplodingProvider(RecordingProvider):
            async def summarize(self, *, text, language):
                self.calls += 1
                raise AiUpstreamError("upstream down")

        app.state.summary_service = SummaryService(
            db=db,
            adapter=FakeAdapter(detail),
            settings_store=AiSettingsStore(db),
            provider_factory=_factory(ExplodingProvider()),
        )
        run(db.execute(
            "UPDATE ai_summaries SET status = 'failed' WHERE entry_ref = ?",
            (detail.entryRef,),
        ))
        failed = client.post(f"/api/v1/entries/{detail.entryRef}/summary")
        assert failed.status_code == 502
        after = client.get(f"/api/v1/entries/{detail.entryRef}/summary").json()
        assert len(after["versions"]) == 2  # 失败不覆盖、不新增

        # 第 4 版淘汰最旧（FIFO 3 版上限）
        app.state.summary_service = service
        for _ in range(2):
            run(db.execute(
                "UPDATE ai_summaries SET status = 'failed' WHERE entry_ref = ?",
                (detail.entryRef,),
            ))
            client.post(f"/api/v1/entries/{detail.entryRef}/summary")
        final = client.get(f"/api/v1/entries/{detail.entryRef}/summary").json()
        assert len(final["versions"]) == 3
        assert all(v["summary"] != first["versions"][0]["summary"] for v in final["versions"])

        # activate 切换展示版本
        target = final["versions"][0]
        activated = client.post(
            f"/api/v1/entries/{detail.entryRef}/summary/versions/{target['versionId']}/activate"
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["summary"] == target["summary"]
        assert activated.json()["activeVersionId"] == target["versionId"]
        # 不存在的版本 → 404
        missing = client.post(
            f"/api/v1/entries/{detail.entryRef}/summary/versions/sv-nope/activate"
        )
        assert missing.status_code == 404

    # 重启后版本仍在（同一 db 重新打开 store）
    from lumirss.ai_summary_versions import SummaryVersionStore

    rows = run(
        SummaryVersionStore(db).list_versions(
            detail.entryRef,
            __import__("hashlib").sha256(
                __import__("re").sub(r"\s+", " ", detail.contentText).strip().encode()
            ).hexdigest(),
        )
    )
    assert len(rows) == 3
