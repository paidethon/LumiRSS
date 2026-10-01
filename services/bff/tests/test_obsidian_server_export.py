"""R07 服务端受限写入导出 — 受限写入适配器 / 幂等 / 路径防线 / 渲染。

直接对 :mod:`lumirss.obsidian_export` 做单元测试（tmp_path 假 vault，
无需真 Obsidian、无上游网络）；路由层另有一条轻量 HTTP 冒烟
（client 夹具，basic 模式隐式 owner）。

覆盖：正常导出 + frontmatter 完整性、重复导出幂等（exists 不重写）、
路径穿越拒绝、symlink 逃逸拒绝、绝不覆盖已有文件（-2 后缀）、无正文
书签（未抓取全文）、批量/每日配额有界、导出未配置的诚实降级。
"""

import asyncio

import frontmatter as fm_module
import pytest

from lumirss.obsidian_export import (
    DEFAULT_EXPORT_SUBDIR,
    ExportBatchTooLarge,
    ExportPayload,
    ExportSubdirInvalid,
    ObsidianExportService,
    content_id_for,
    normalize_export_subdir,
    render_note,
    slug_stem,
    validate_export_subdir,
)
from lumirss.storage import Database

REF = "rss:e1.YQ"  # 任意合法形状（本文件直接喂 payload，不走收集）


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "lumi.sqlite")

    async def _migrate():
        await database.migrate()

    asyncio.run(_migrate())
    return database


@pytest.fixture()
def vault(tmp_path):
    root = tmp_path / "vault-export"
    root.mkdir()
    return root


def _service(db: Database, vault) -> ObsidianExportService:
    return ObsidianExportService(db, export_dir=str(vault))


def _payload(**overrides) -> ExportPayload:
    base = {
        "ref": REF,
        "source_type": "rss",
        "title": "一篇测试文章",
        "source_name": "示例订阅源",
        "url": "https://example.com/article",
        "author": "作者甲",
        "published": "2026-09-23T08:00:00Z",
        "body_text": "正文第一段。\n\n正文第二段。",
        "tags": ("阅读", "测试"),
    }
    base.update(overrides)
    return ExportPayload(**base)


def _run(coro):
    return asyncio.run(coro)


# ---- 正常导出 + frontmatter 完整性 ------------------------------------


def test_export_writes_note_with_complete_frontmatter(db, vault, tmp_path):
    service = _service(db, vault)
    results = _run(service.export_batch([_payload()], user_id="owner"))
    assert len(results) == 1
    assert results[0]["status"] == "written"
    target = vault / results[0]["path"]
    assert target.is_file()
    post = fm_module.loads(target.read_text(encoding="utf-8"))
    meta = post.metadata
    assert meta["title"] == "一篇测试文章"
    assert meta["url"] == "https://example.com/article"
    assert meta["source-type"] == "rss"
    assert meta["source-name"] == "示例订阅源"
    assert meta["author"] == "作者甲"
    assert meta["published"] == "2026-09-23T08:00:00Z"
    assert meta["exported"]  # 剪藏（导出）时间总在
    assert meta["content-id"] == content_id_for(REF)
    assert meta["lumirss-ref"] == REF
    assert "lumirss" in meta["tags"]
    assert "rss" in meta["tags"]
    assert "阅读" in meta["tags"]
    assert "正文第一段" in post.content
    # 目录结构 = <subdir>/<user_id>/（per-user 隔离）。
    assert results[0]["path"].startswith(f"{DEFAULT_EXPORT_SUBDIR}/owner/")
    # 相对路径里没有 ..（containment 的正向断言）。
    assert ".." not in results[0]["path"]


def test_frontmatter_omits_absent_optional_fields(db, vault):
    service = _service(db, vault)
    results = _run(
        service.export_batch([_payload(author=None, published=None)], user_id="owner")
    )
    assert results[0]["status"] == "written"
    target = vault / results[0]["path"]
    post = fm_module.loads(target.read_text(encoding="utf-8"))
    assert "author" not in post.metadata  # 存在才写，缺失诚实省略
    assert "published" not in post.metadata


def test_include_sections_render_when_present(db, vault):
    payload = _payload(
        summary="这是摘要。",
        translation_title="A translated title",
        translation_text="这是译文正文。",
        annotations=({"quote": "摘录一句", "note": "我的批注", "link": "/reader?entry=x"},),
    )
    rendered = render_note(payload)
    assert "## AI 摘要" in rendered["markdown"]
    assert "这是摘要。" in rendered["markdown"]
    assert "## 译文：A translated title" in rendered["markdown"]
    assert "## 批注" in rendered["markdown"]
    assert "摘录一句" in rendered["markdown"]
    assert "[→ LumiRSS 原文](/reader?entry=x)" in rendered["markdown"]
    # 未请求的分区不出现（收集端置 None/空）。
    plain = render_note(_payload())["markdown"]
    assert "## AI 摘要" not in plain
    assert "## 批注" not in plain


# ---- 幂等 / 绝不覆盖 ---------------------------------------------------


def test_reexport_same_content_is_idempotent(db, vault):
    service = _service(db, vault)
    first = _run(service.export_batch([_payload()], user_id="owner"))
    second = _run(service.export_batch([_payload()], user_id="owner"))
    assert first[0]["status"] == "written"
    assert second[0]["status"] == "exists"
    assert second[0]["path"] == first[0]["path"]
    # 文件系统里仍然只有一份。
    notes = list((vault / DEFAULT_EXPORT_SUBDIR / "owner").glob("*.md"))
    assert len(notes) == 1


def test_existing_file_with_different_content_is_never_overwritten(db, vault):
    service = _service(db, vault)
    rendered = render_note(_payload())
    expected_stem = rendered["stem"]
    user_dir = vault / DEFAULT_EXPORT_SUBDIR / "owner"
    user_dir.mkdir(parents=True)
    handwritten = user_dir / f"{expected_stem}.md"
    handwritten.write_text("---\ntitle: 手写笔记\n---\n用户自己的内容", encoding="utf-8")
    results = _run(service.export_batch([_payload()], user_id="owner"))
    assert results[0]["status"] == "written"
    assert results[0]["path"] != f"{DEFAULT_EXPORT_SUBDIR}/owner/{expected_stem}.md"
    assert results[0]["path"].endswith("-2.md")  # 同名不同内容 → -2 新文件
    assert "手写笔记" in handwritten.read_text(encoding="utf-8")  # 原文件原样保留


def test_changed_content_for_same_ref_gets_new_file(db, vault):
    service = _service(db, vault)
    first = _run(service.export_batch([_payload()], user_id="owner"))
    second = _run(
        service.export_batch([_payload(body_text="内容升级后的新正文")], user_id="owner")
    )
    assert first[0]["status"] == "written"
    assert second[0]["status"] == "written"
    assert second[0]["path"] != first[0]["path"]
    assert (vault / first[0]["path"]).is_file()
    assert (vault / second[0]["path"]).is_file()


# ---- 路径防线 ----------------------------------------------------------


def test_subdir_traversal_is_rejected(db):
    # set_subdir 只落库、不碰文件系统：export_dir 取什么值都行。
    with pytest.raises(ExportSubdirInvalid):
        _run(ObsidianExportService(db, export_dir="/unused").set_subdir("../escape"))
    with pytest.raises(ExportSubdirInvalid):
        _run(ObsidianExportService(db, export_dir="/unused").set_subdir("a/../../b"))
    with pytest.raises(ExportSubdirInvalid):
        _run(ObsidianExportService(db, export_dir="/unused").set_subdir("/abs/path"))
    assert normalize_export_subdir("a/../b") is None
    assert normalize_export_subdir(".hidden") is None
    assert normalize_export_subdir("a\\b") is None
    # 读路径宽容回退默认（绝不抛给批量导出）。
    assert validate_export_subdir("../escape") == DEFAULT_EXPORT_SUBDIR
    assert validate_export_subdir("我的剪藏/订阅") == "我的剪藏/订阅"


def test_symlink_escape_is_refused(db, vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / DEFAULT_EXPORT_SUBDIR).mkdir(parents=True)
    (vault / DEFAULT_EXPORT_SUBDIR / "owner").symlink_to(outside)
    service = _service(db, vault)
    results = _run(service.export_batch([_payload()], user_id="owner"))
    assert results[0]["status"] == "failed"
    assert results[0]["reason"] == "export_path_rejected"
    assert list(outside.iterdir()) == []  # 外部目录一个字节都没落


def test_symlinked_subdir_escape_is_refused(db, vault, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / DEFAULT_EXPORT_SUBDIR).symlink_to(outside, target_is_directory=True)
    service = _service(db, vault)
    results = _run(service.export_batch([_payload()], user_id="owner"))
    assert results[0]["status"] == "failed"
    assert results[0]["reason"] == "export_path_rejected"
    assert list(outside.iterdir()) == []


# ---- 无正文书签 --------------------------------------------------------


def test_bookmark_without_body_notes_unfetched(db, vault):
    service = _service(db, vault)
    payload = _payload(
        ref="library:00000000-0000-4000-8000-000000000001",
        source_type="bookmark",
        title="一个链接收藏",
        source_name="书签",
        url="https://example.com/link",
        body_text=None,
    )
    results = _run(service.export_batch([payload], user_id="owner"))
    assert results[0]["status"] == "written"
    post = fm_module.loads((vault / results[0]["path"]).read_text(encoding="utf-8"))
    assert post.metadata["source-type"] == "bookmark"
    assert post.metadata["url"] == "https://example.com/link"
    assert "未抓取全文" in post.content
    assert "https://example.com/link" in post.content


def test_bookmark_note_becomes_body(db, vault):
    service = _service(db, vault)
    payload = _payload(
        source_type="bookmark",
        source_name="书签",
        body_text="我的书签笔记。",
    )
    results = _run(service.export_batch([payload], user_id="owner"))
    post = fm_module.loads((vault / results[0]["path"]).read_text(encoding="utf-8"))
    assert "我的书签笔记。" in post.content
    assert "未抓取全文" not in post.content


# ---- 有界：批量 / 每日配额 / 单文件 ------------------------------------


def test_batch_over_limit_is_rejected(db, vault):
    service = _service(db, vault)
    payloads = [_payload(ref=f"rss:e1.{index}", title=f"t{index}") for index in range(51)]
    with pytest.raises(ExportBatchTooLarge):
        _run(service.export_batch(payloads, user_id="owner"))


def test_daily_quota_marks_remaining_items_failed(db, vault, monkeypatch):
    import lumirss.obsidian_export as module

    service = _service(db, vault)

    async def _at_cap(_day_prefix: str) -> int:
        # 模拟「今日已写满」：任意内容都会撞每日上限。
        return module._MAX_DAILY_BYTES

    monkeypatch.setattr(service, "_written_bytes_since", _at_cap)
    results = _run(service.export_batch([_payload(ref="rss:e1.a", title="a")], user_id="owner"))
    assert results[0]["status"] == "failed"
    assert results[0]["reason"] == "quota_exceeded"


def test_body_truncation_is_marked(db):
    rendered = render_note(_payload(body_text="词" * 300_000))
    assert "truncated: true" in rendered["markdown"]


# ---- content-id / 状态 -------------------------------------------------


def test_content_id_is_stable_per_ref_and_differs_across_refs():
    assert content_id_for("rss:e1.A") == content_id_for("rss:e1.A")
    assert content_id_for("rss:e1.A") != content_id_for("library:x")
    assert len(content_id_for("rss:e1.A")) == 16


def test_slug_stem_is_filename_safe_and_deterministic():
    stem = slug_stem("标题: 带/非法*字符", "abcdef1234567890")
    assert "/" not in stem and ":" not in stem and "*" not in stem
    assert stem.endswith("-abcdef12")
    assert slug_stem("标题: 带/非法*字符", "abcdef1234567890") == stem


def test_unconfigured_export_dir_fails_honestly(db):
    service = ObsidianExportService(db, export_dir="")
    results = _run(service.export_batch([_payload()], user_id="owner"))
    assert results[0]["status"] == "failed"
    assert results[0]["reason"] == "export_unconfigured"


def test_status_reports_usage_and_recent(db, vault):
    service = _service(db, vault)
    _run(service.export_batch([_payload()], user_id="owner"))
    status = _run(service.status(user_id="owner"))
    assert status["configured"] is True
    assert status["subdir"] == DEFAULT_EXPORT_SUBDIR
    assert status["userDir"] == f"{DEFAULT_EXPORT_SUBDIR}/owner"
    assert status["todayBytes"] > 0
    assert status["dailyLimitBytes"] > 0
    assert len(status["recent"]) == 1
    assert status["recent"][0]["outcome"] == "written"


def test_subdir_setting_roundtrip_and_isolation(db, vault):
    service = _service(db, vault)
    assert _run(service.set_subdir("我的剪藏/订阅")) == "我的剪藏/订阅"
    assert _run(service.get_subdir()) == "我的剪藏/订阅"
    results = _run(service.export_batch([_payload()], user_id="owner"))
    assert results[0]["path"].startswith("我的剪藏/订阅/owner/")
    # 另一账户在自己的目录里（内容同 ref 同内容 → exists 也指向各自目录）。
    other = _run(service.export_batch([_payload()], user_id="member1"))
    assert other[0]["path"].startswith("我的剪藏/订阅/member1/")
    assert other[0]["status"] == "written"  # 各用户目录独立，互不判等
    assert (vault / other[0]["path"]).is_file()


# ---- 路由冒烟（new201_210_harness：真 RoutingDatabase + 绑定测试用户，
# 不打上游、不起 main.py 全量中间件；include 由主 Agent 接线） ---------


@pytest.fixture()
def make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from lumirss.routers import obsidian_export as export_router
    from new201_210_harness import feature_app

    clients = []

    def _make(*, export_dir: str | None = None):
        if export_dir is None:
            monkeypatch.delenv("LUMIRSS_OBSIDIAN_EXPORT_DIR", raising=False)
        else:
            monkeypatch.setenv("LUMIRSS_OBSIDIAN_EXPORT_DIR", export_dir)
        app = feature_app(tmp_path, export_router.router)
        client = TestClient(app)
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.close()


def test_route_status_honest_when_unconfigured(make_client):
    client = make_client()
    resp = client.get("/api/v1/obsidian/export/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["subdir"] == "LumiRSS"


def test_route_export_reports_unconfigured_per_item(make_client):
    from lumirss.entryref import encode_entry_ref

    client = make_client()
    resp = client.post(
        "/api/v1/obsidian/export",
        json={"refs": [f"rss:{encode_entry_ref('item-1')}"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 1
    assert body["items"][0]["status"] == "failed"


def test_route_invalid_ref_is_per_item_failed_not_batch_abort(make_client):
    client = make_client()
    resp = client.post(
        "/api/v1/obsidian/export",
        json={"refs": ["not-a-ref", "also bad"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 2
    assert all(item["reason"] == "invalid_ref" for item in body["items"])


def test_route_subdir_settings_rejects_traversal(make_client):
    client = make_client()
    resp = client.put(
        "/api/v1/obsidian/export/settings",
        json={"subdir": "../evil"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["type"] == "invalid_export_subdir"
    resp = client.put(
        "/api/v1/obsidian/export/settings",
        json={"subdir": "我的剪藏"},
    )
    assert resp.status_code == 200
    assert resp.json()["subdir"] == "我的剪藏"


def test_route_export_writes_into_configured_root(make_client, tmp_path):
    from lumirss.itemref import library_item_ref

    vault = tmp_path / "vault-export"
    vault.mkdir()
    client = make_client(export_dir=str(vault))
    # 一个不存在的 library ref → 收集失败（not_found），绝不写文件。
    ref = library_item_ref("00000000-0000-4000-8000-00000000dead")
    resp = client.post("/api/v1/obsidian/export", json={"refs": [ref]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["failed"] == 1
    assert body["items"][0]["reason"] == "not_found"
    # 导出根保持干净（没有可导出的内容就没有文件）。
    assert list(vault.rglob("*.md")) == []
