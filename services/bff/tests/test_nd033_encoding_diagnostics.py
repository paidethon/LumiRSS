"""N033 编码乱码诊断 — 声明/检测/乱码风险、reparse 覆盖与诚实边界。

内嵌小字节夹具（UTF-8 与 GBK），不依赖任何网络：
- 检测启发式（BOM / XML 声明 / meta / UTF-8 严格校验）正确识别两类夹具；
- 错误的手动覆盖（utf-8 强解码 GBK）如实显示乱码掩码样本；
- encoding_override 只影响 Lumi 自己的解码点（预览/reparse），
  已投影的历史数据绝不回写。
"""

import asyncio

from lumirss.encoding_diag import (
    decode_sample,
    inspect_encoding,
    resolve_override_codec,
)
from lumirss.feed_preview import parse_feed_document
from lumirss.main import app
from lumirss.source_overrides import SourceOverrideStore

# -- 内嵌字节夹具 ------------------------------------------------------------

UTF8_DOC = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    "<rss><channel><title>科技新闻周刊</title>"
    "<item><title>中文标题正常显示</title></item></channel></rss>"
).encode()

GBK_DOC = (
    '<?xml version="1.0" encoding="gbk"?>\n'
    "<rss><channel><title>科技新闻周刊</title>"
    "<item><title>中文标题正常显示</title></item></channel></rss>"
).encode("gbk")

GBK_UNDECLARED = (
    "<rss><channel><title>科技新闻周刊</title></channel></rss>"
).encode("gbk")


# -- 检测启发式 ---------------------------------------------------------------


def test_utf8_fixture_detected_correctly():
    info = inspect_encoding(UTF8_DOC, "application/xml; charset=utf-8")
    assert info["declared"] == "utf-8"
    assert info["declaredMethod"] == "xml_declaration"
    assert info["detected"] == "utf-8"
    assert info["utf8Valid"] is True
    assert info["mojibakeRisk"] is False
    assert info["sample"] is None


def test_gbk_fixture_detected_correctly():
    info = inspect_encoding(GBK_DOC, "application/xml")  # header 未声明 → 文档声明生效
    assert info["declared"] == "gbk"
    assert info["declaredMethod"] == "xml_declaration"
    assert info["detected"] == "gbk", "声明 GBK 且可干净解码 → detected=gbk"
    assert info["utf8Valid"] is False
    assert info["mojibakeRisk"] is False, "声明与检测一致且解码干净 → 无乱码风险"
    assert info["sample"] is None


def test_undeclared_gbk_flags_mojibake_risk_with_masked_sample():
    info = inspect_encoding(GBK_UNDECLARED, "application/xml")
    assert info["declared"] is None
    assert info["detected"] == "unknown"
    assert info["mojibakeRisk"] is True
    assert info["sample"] is not None
    assert "\ufffd" in info["sample"], "首个无效字节附近以替换符掩码"
    assert len(info["sample"]) <= 200


def test_declared_vs_detected_mismatch_flags_risk():
    # Content-Type 声明 latin-1，但字节是干净 UTF-8 中文 → 声明/检测冲突
    body = "<rss><title>中文标题</title></rss>".encode()
    info = inspect_encoding(body, "application/xml; charset=iso-8859-1")
    assert info["detected"] == "utf-8"
    assert info["mojibakeRisk"] is True


def test_bom_takes_priority():
    body = b"\xef\xbb\xbf" + UTF8_DOC
    info = inspect_encoding(body, None)
    assert info["declared"] == "utf-8-sig"
    assert info["declaredMethod"] == "bom"
    assert info["detected"] == "utf-8-sig"


# -- 覆盖选择与解码路径 --------------------------------------------------------


def test_wrong_manual_override_shows_mojibake_sample():
    info = inspect_encoding(GBK_DOC, "application/xml")
    assert resolve_override_codec("utf-8", info) == "utf-8"
    sample = decode_sample(GBK_DOC, "utf-8")
    assert "\ufffd" in sample, "错误覆盖（utf-8 解 GBK）必须如实显示乱码"
    good = decode_sample(GBK_DOC, "gbk")
    assert "科技新闻周刊" in good


def test_parse_feed_document_honors_override():
    # declared 覆盖 → GBK 正确解码出中文标题
    title, *_ = parse_feed_document(GBK_DOC, "application/xml", encoding_override="declared")
    assert title == "科技新闻周刊"
    # utf-8 覆盖 → 乱码标题（诚实呈现，不修饰）
    bad_title, *_ = parse_feed_document(GBK_DOC, "application/xml", encoding_override="utf-8")
    assert bad_title != "科技新闻周刊"
    # 无覆盖 → feedparser 自行解码 GBK 声明（基线不回归）
    baseline, *_ = parse_feed_document(GBK_DOC, "application/xml")
    assert baseline == "科技新闻周刊"


# -- reparse 路由 + source_overrides 保存 -------------------------------------


class FakePreviewService:
    def __init__(self):
        self.preview_overrides: list[str | None] = []

    async def preview(self, feed_url, *, encoding_override=None):
        self.preview_overrides.append(encoding_override)
        from lumirss.feed_preview import FeedPreview

        return FeedPreview(
            title="科技新闻周刊",
            feed_url=feed_url,
            site_url=None,
            description=None,
            format="rss",
            already_subscribed=False,
            encoding_info=inspect_encoding(GBK_DOC, "application/xml"),
        )

    async def reparse(self, feed_url, *, encoding_override=None):
        info = inspect_encoding(GBK_DOC, "application/xml")
        choices = []
        for choice in ("utf-8", "declared", "detected"):
            codec = resolve_override_codec(choice, info)
            sample = decode_sample(GBK_DOC, codec)
            choices.append(
                {
                    "encoding": choice,
                    "resolvedCodec": codec,
                    "title": "科技新闻周刊" if codec == "gbk" else None,
                    "sample": sample,
                    "mojibakeRisk": "\ufffd" in sample,
                }
            )
        return None, info, choices


def _wire_service(service):
    app.state.feed_preview_service = service


def test_reparse_route_choices_and_save_override(client):
    service = FakePreviewService()
    _wire_service(service)
    try:
        response = client.post(
            "/api/v1/feed-preview/reparse",
            json={"feedUrl": "https://feed.example/rss", "encoding": "declared", "save": True},
        )
    finally:
        app.state.feed_preview_service = None
    assert response.status_code == 200
    body = response.json()
    assert [c["encoding"] for c in body["choices"]] == ["utf-8", "declared", "detected"]
    declared_choice = body["choices"][1]
    assert declared_choice["mojibakeRisk"] is False
    utf8_choice = body["choices"][0]
    assert utf8_choice["mojibakeRisk"] is True, "错误选择的乱码如实呈现"
    assert body["applied"] == "declared"
    assert body["savedOverride"] == "declared"

    async def _stored():
        return await SourceOverrideStore(app.state.db).get_encoding_override(
            "https://feed.example/rss"
        )

    assert asyncio.run(_stored()) == "declared"
    # 后续预览按保存的覆盖解码（服务收到 encoding_override）
    _wire_service(service)
    try:
        client.post("/api/v1/feed-preview", json={"feedUrl": "https://feed.example/rss"})
    finally:
        app.state.feed_preview_service = None
    assert service.preview_overrides[-1] == "declared"


def test_override_never_rewrites_projected_history(client):
    """覆盖只影响未来抓取/解码；已投影历史数据保持原样（不静默回写）。"""

    async def _seed():
        db = app.state.db
        await db.migrate()
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES ('h1','e1.hDE','https://feed.example/rss','源','乱码标题历史','','','乱码正文历史','2026-09-01T00:00:00Z',0,0,100)"
        )
        await SourceOverrideStore(db).set_encoding_override(
            "https://feed.example/rss", "utf-8"
        )

    asyncio.run(_seed())

    async def _row():
        return await app.state.db.fetch_one(
            "SELECT title, content_text, fetched_at FROM search_entries WHERE item_id = 'h1'"
        )

    row = asyncio.run(_row())
    assert row["title"] == "乱码标题历史", "历史投影标题不被回写"
    assert row["content_text"] == "乱码正文历史", "历史投影正文不被回写"
    assert row["fetched_at"] == 100, "历史投影时间戳不被回写"


def test_reparse_rejects_unknown_encoding(client):
    app.state.feed_preview_service = FakePreviewService()
    try:
        response = client.post(
            "/api/v1/feed-preview/reparse",
            json={"feedUrl": "https://feed.example/rss", "encoding": "latin-5"},
        )
    finally:
        app.state.feed_preview_service = None
    assert response.status_code == 422, "契约外的编码选择被校验拒绝"


def test_source_overrides_roundtrip_encoding_override(client):
    async def _roundtrip():
        store = SourceOverrideStore(app.state.db)
        await store.set_encoding_override("https://x.example/rss", "detected")
        assert await store.get_encoding_override("https://x.example/rss") == "detected"
        override = await store.get_override("https://x.example/rss")
        assert override is not None and override["encodingOverride"] == "detected"
        await store.set_encoding_override("https://x.example/rss", None)
        assert await store.get_encoding_override("https://x.example/rss") is None

    asyncio.run(_roundtrip())
