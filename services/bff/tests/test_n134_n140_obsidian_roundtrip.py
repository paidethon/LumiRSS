"""N134/N135/N137/N138/N139/N140 — Obsidian 交接闭环（块级回跳 / 重名
策略 / 增量批注导出 / 文件级诊断 / 导出侧校验 / 双向交接记录）。

约定：
- Vault 依旧只读（ADR 0004）——所有测试断言都不写 Vault；
- URI 模式无法探测同名笔记（官方 URI 限制）→ N135 是显式策略而非
  伪装的查重；
- N140 的 confirmed 只能来自显式确认动作：本套件断言被动事件
  （列表重读 = 页面重载）绝不改变状态。
"""

import asyncio

from lumirss.annotation_store import AnnotationStore
from lumirss.library_export import safe_filename
from lumirss.obsidian import ObsidianService
from lumirss.obsidian_backlinks import (
    _LUMI_BLOCK_ID_RE,
    block_refs_for,
    rebuild_block_refs,
)
from lumirss.obsidian_handoff import (
    BLOCK_ID_RE,
    build_projection_index,
    note_filename,
    prepare_handoff,
    validate_export_markdown,
)
from lumirss.obsidian_handoff_log import HandoffLogStore
from lumirss.storage import Database
from lumirss.user_scope import RoutingDatabase, user_context


def _run(coro):
    return asyncio.run(coro)


class _Detail:
    entryRef = "e1.a"
    title = "中文标题：N 系列交接"
    feedTitle = "示例源"
    url = "https://example.com/a"
    publishedAt = "2026-09-23T08:00:00Z"
    crawledAt = None
    contentText = "第一段。\n\n第二段。"


_PROFILE = {"label": "iPhone", "vault_name": "v", "platform": "ios"}


def _annotation(para_id: str, annotation_id: str = "a-1") -> dict:
    return {
        "id": annotation_id,
        "entry_ref": "e1.a",
        "anchor": {"paraId": para_id},
        "excerpt": "关键一句",
        "note": "",
    }


# ---------------------------------------------------------------------------
# N134 块级回跳：handoff markdown 内嵌块 id + 反链；投影侧索引 + 反查。
# ---------------------------------------------------------------------------


def test_handoff_markdown_embeds_block_id_and_backlink():
    prepared = prepare_handoff(
        profile=_PROFILE,
        detail=_Detail(),
        annotations=[_annotation("abcd1234-2")],
        template="{{annotations}}",
        public_url="https://rss.example.com/",
    )
    assert "^lumi-abcd1234-2" in prepared.content
    assert (
        "[→ LumiRSS 原文](https://rss.example.com/reader?entry=e1.a&para=abcd1234-2)"
        in prepared.content
    )
    # Obsidian 块 id 语法：块 id 必须是行内最后一个 token。
    line = next(
        line for line in prepared.content.splitlines() if "^lumi-" in line
    )
    assert line.rstrip().endswith("^lumi-abcd1234-2")
    # 导出侧与投影侧使用同一块 id 形状（round-trip 的前提）。
    assert BLOCK_ID_RE.pattern == _LUMI_BLOCK_ID_RE.pattern


def test_handoff_block_id_without_public_url_omits_backlink_honestly():
    prepared = prepare_handoff(
        profile=_PROFILE,
        detail=_Detail(),
        annotations=[_annotation("abcd1234-2")],
        template="{{annotations}}",
        public_url="",
    )
    assert "^lumi-abcd1234-2" in prepared.content
    assert "→ LumiRSS 原文" not in prepared.content  # 未配置 → 诚实省略
    # 无段落锚点的批注：不发明块 id。
    prepared_no_para = prepare_handoff(
        profile=_PROFILE,
        detail=_Detail(),
        annotations=[{"id": "a-2", "entry_ref": "e1.a", "anchor": {}, "excerpt": "无锚", "note": ""}],
        template="{{annotations}}",
        public_url="https://rss.example.com",
    )
    assert "lumi-" not in prepared_no_para.content.replace("LumiRSS", "")


def test_scan_indexes_block_ids_and_lookup_finds_note(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    service = ObsidianService(db)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "reading.md").write_text(
        "---\ntitle: 阅读摘录\n---\n\n- 「关键一句」 ^lumi-abcd1234-2\n- 普通条目 ^obsidian-plain\n",
        encoding="utf-8",
    )
    _run(service.set_vault_path(str(vault)))
    _run(service.rescan())

    assert _run(rebuild_block_refs(db)) >= 1
    refs = _run(block_refs_for(db, "abcd1234-2"))
    assert len(refs) == 1
    assert refs[0]["relPath"] == "reading.md"
    assert refs[0]["paraId"] == "abcd1234-2"
    # 非 lumi- 块 id 不入索引；带前缀查询同样命中。
    assert _run(block_refs_for(db, "obsidian-plain")) == []
    assert [r["paraId"] for r in _run(block_refs_for(db, "lumi-abcd1234-2"))] == [
        "abcd1234-2"
    ]


def test_block_refs_route_roundtrip(client):
    import tempfile
    from pathlib import Path

    from lumirss.main import app as lumi_app
    from lumirss.obsidian import ObsidianService as _Svc

    # conftest 把 app.state.db 换成纯 Database；lifespan 绑定的
    # obsidian_service 仍指向 owner 库 —— 显式重绑到同一个 db，让
    # rescan 落库与 block-refs 读取一致（deps 对显式注入最优先）。
    lumi_app.state.obsidian_service = _Svc(lumi_app.state.db)

    tmp = Path(tempfile.mkdtemp())
    vault_dir = tmp / "vault"
    vault_dir.mkdir()
    (vault_dir / "reading.md").write_text(
        "摘录内容 ^lumi-feed10-3\n", encoding="utf-8"
    )
    assert client.put(
        "/api/v1/obsidian/settings", json={"vaultPath": str(vault_dir)}
    ).status_code == 200
    rescanned = client.post("/api/v1/obsidian/rescan")
    assert rescanned.status_code == 200
    assert rescanned.json()["added"] == 1
    # rescan 已重建块 id 索引（rescan 内部调用 rebuild_block_refs）。
    found = client.get("/api/v1/obsidian/block-refs", params={"paraId": "feed10-3"})
    assert found.status_code == 200
    items = found.json()["items"]
    assert len(items) == 1 and items[0]["relPath"] == "reading.md"

    missing = client.get("/api/v1/obsidian/block-refs", params={"paraId": "nope"})
    assert missing.status_code == 200 and missing.json()["items"] == []
    blank = client.get("/api/v1/obsidian/block-refs")
    assert blank.status_code == 422


# ---------------------------------------------------------------------------
# N135 导出重名处理：显式命名策略（URI 无法探测同名笔记 → 不是查重）。
# ---------------------------------------------------------------------------


def test_note_filename_policies():
    stamped = note_filename("我的 笔记", policy="timestamp_suffix", now="2026-09-23T08:00:00+00:00")
    assert stamped == "我的 笔记-20260923-0800.md"
    exact = note_filename("我的 笔记", policy="exact", now="2026-09-23T08:00:00+00:00")
    assert exact == "我的 笔记.md"
    # 非法策略回退 exact 形状（策略合法性在 prepare/存档层兜底）；空标题有占位。
    assert note_filename("", policy="bogus", now="2026-09-23T08:00:00+00:00") == "文章.md"
    # 文件下载路径保持 uuid 后缀、从不覆盖（与 URI 命名策略无关）。
    download_name = safe_filename("我的 笔记", "0123456789abcdef")
    assert download_name.endswith("-01234567.md")


def test_export_template_policy_route_and_handoff_filename(client, monkeypatch):
    from lumirss import deps
    from lumirss.entryref import encode_entry_ref

    ref = encode_entry_ref("item-1")

    view = client.get("/api/v1/obsidian/export-template")
    assert view.status_code == 200
    assert view.json()["exportNamePolicy"] == "timestamp_suffix"  # 默认

    saved = client.put(
        "/api/v1/obsidian/export-template", json={"exportNamePolicy": "exact"}
    )
    assert saved.status_code == 200
    assert saved.json()["exportNamePolicy"] == "exact"
    # 模板单独更新不互相覆盖（None = 保持现状）。
    kept = client.put(
        "/api/v1/obsidian/export-template", json={"template": "{{title}}"}
    )
    assert kept.status_code == 200
    assert kept.json()["exportNamePolicy"] == "exact"
    assert kept.json()["template"] == "{{title}}"

    invalid = client.put(
        "/api/v1/obsidian/export-template", json={"exportNamePolicy": "overwrite"}
    )
    assert invalid.status_code == 422

    device = client.post(
        "/api/v1/obsidian/devices",
        json={"label": "d", "vaultName": "v", "platform": "ios"},
    ).json()

    class _FakeAdapter:
        async def get_entry(self, item_id):
            return _Detail()

    monkeypatch.setattr(deps, "_get_adapter", lambda request: _FakeAdapter())
    handoff = client.post(
        "/api/v1/obsidian/export-handoff",
        json={"entryRef": ref, "deviceId": device["id"]},
    )
    assert handoff.status_code == 200, handoff.text
    # exact 策略 → 纯标题文件名；timestamp_suffix → 追加 -YYYYMMDD-HHmm。
    assert handoff.json()["filename"] == "中文标题：N 系列交接.md"
    client.put(
        "/api/v1/obsidian/export-template", json={"exportNamePolicy": "timestamp_suffix"}
    )
    stamped = client.post(
        "/api/v1/obsidian/export-handoff",
        json={"entryRef": ref, "deviceId": device["id"]},
    ).json()["filename"]
    assert stamped.startswith("中文标题：N 系列交接-") and stamped.endswith(".md")


# ---------------------------------------------------------------------------
# N137 增量批注导出：水位 + 增量查询 + mark 幂等 + 交接后自动回标。
# ---------------------------------------------------------------------------


def test_annotation_delta_watermark_and_idempotent_mark(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    import lumirss.annotation_store as ann_mod

    # utc_now 秒级精度 → 注入可控时钟（分钟偏移）保证 > 水位比较确定。
    clock = {"offset_min": 0}
    real_now = ann_mod.utc_now

    def _fake_now():
        return (
            datetime.now(UTC) + timedelta(minutes=clock["offset_min"])
        ).isoformat(timespec="seconds")

    monkeypatch.setattr(ann_mod, "utc_now", _fake_now)

    db = Database(tmp_path / "lumi.sqlite")
    store = AnnotationStore(db)
    a1 = _run(store.create(entry_ref="e1.a", anchor={"paraId": "p1"}, excerpt="一", note=""))
    a2 = _run(store.create(entry_ref="e1.a", anchor={"paraId": "p2"}, excerpt="二", note=""))
    a3 = _run(store.create(entry_ref="e2.b", anchor={"paraId": "p3"}, excerpt="三", note=""))

    # 从未导出：全部计为新增。
    delta = _run(store.export_delta())
    assert delta["lastExportedAt"] is None
    assert delta["addedCount"] == 3 and delta["modifiedCount"] == 0

    clock["offset_min"] = 5
    marked = _run(store.mark_exported([a1["id"], a3["id"], "ghost-id"]))
    assert marked["count"] == 2  # 未知 id 静默跳过，诚实计数
    assert marked["entryRefs"] == ["e1.a", "e2.b"]

    # 水位之前创建且未变化的批注（含从未导出的 a2）不算增量 —— 增量 =
    # updated_at > 水位（规格语义）。
    delta = _run(store.export_delta())
    assert delta["lastExportedAt"] is not None
    assert delta["addedCount"] == 0 and delta["modifiedCount"] == 0
    assert _run(store.export_delta(entry_ref="e1.a"))["total"] == 0

    # 水位之后新建的批注 → 「新增」。
    clock["offset_min"] = 8
    a4 = _run(store.create(entry_ref="e1.a", anchor={"paraId": "p4"}, excerpt="四", note=""))
    delta = _run(store.export_delta())
    assert delta["addedCount"] == 1 and delta["modifiedCount"] == 0

    # 导出后修改 a1 → 出现在「修改」而非「新增」。
    clock["offset_min"] = 10
    _run(store.update(a1["id"], note="改过"))
    delta = _run(store.export_delta())
    assert delta["modifiedCount"] == 1 and delta["addedCount"] == 1

    # 幂等重试：重复 mark 无害（水位只前进，计数不重复）。
    clock["offset_min"] = 15
    _run(store.mark_exported([a1["id"], a2["id"], a4["id"]]))
    _run(store.mark_exported([a1["id"], a4["id"]]))
    delta = _run(store.export_delta())
    assert delta["addedCount"] == 0 and delta["modifiedCount"] == 0
    monkeypatch.setattr(ann_mod, "utc_now", real_now)


def test_annotation_delta_routes(client):
    created = client.post(
        "/api/v1/annotations",
        json={"entryRef": "e9.x", "anchor": {"paraId": "px"}, "excerpt": "增", "note": ""},
    )
    assert created.status_code == 201
    annotation_id = created.json()["id"]

    delta = client.get("/api/v1/annotations/export-delta", params={"entryRef": "e9.x"})
    assert delta.status_code == 200
    assert delta.json()["addedCount"] == 1
    assert delta.json()["lastExportedAt"] is None

    marked = client.post(
        "/api/v1/annotations/export-mark", json={"ids": [annotation_id]}
    )
    assert marked.status_code == 200
    body = marked.json()
    assert body["count"] == 1 and body["entryRefs"] == ["e9.x"]

    delta = client.get("/api/v1/annotations/export-delta", params={"entryRef": "e9.x"})
    assert delta.json()["addedCount"] == 0 and delta.json()["total"] == 0

    empty = client.post("/api/v1/annotations/export-mark", json={"ids": []})
    assert empty.status_code == 422


def test_export_handoff_marks_watermark_and_delta_mode(client, monkeypatch):
    from datetime import UTC, datetime, timedelta

    import lumirss.annotation_store as ann_mod
    from lumirss import deps
    from lumirss.entryref import encode_entry_ref

    ref = encode_entry_ref("item-1")
    device = client.post(
        "/api/v1/obsidian/devices",
        json={"label": "d", "vaultName": "v", "platform": "ios"},
    ).json()
    ann = client.post(
        "/api/v1/annotations",
        json={"entryRef": ref, "anchor": {"paraId": "p1"}, "excerpt": "关键", "note": ""},
    ).json()

    class _FakeAdapter:
        async def get_entry(self, item_id):
            return _Detail()

    monkeypatch.setattr(deps, "_get_adapter", lambda request: _FakeAdapter())

    first = client.post(
        "/api/v1/obsidian/export-handoff",
        json={"entryRef": ref, "deviceId": device["id"]},
    )
    assert first.status_code == 200
    assert first.json()["annotationCount"] == 1  # 全量模式带上批注并回标

    delta = client.get("/api/v1/annotations/export-delta", params={"entryRef": ref})
    assert delta.json()["total"] == 0  # 水位已推进

    # 增量模式：水位之后无变化 → 内容不含批注、annotationCount=0。
    second = client.post(
        "/api/v1/obsidian/export-handoff",
        json={
            "entryRef": ref,
            "deviceId": device["id"],
            "onlySinceLastExport": True,
        },
    )
    assert second.status_code == 200
    assert second.json()["annotationCount"] == 0
    assert "关键" not in second.json()["content"]

    # 修改批注后增量模式再次携带（updated_at > 水位；时间戳秒级精度 →
    # monkeypatch 前进 5 分钟保证确定性）。
    real_now = ann_mod.utc_now

    def _later_now():
        return (datetime.now(UTC) + timedelta(minutes=5)).isoformat(timespec="seconds")

    monkeypatch.setattr(ann_mod, "utc_now", _later_now)
    updated = client.patch(f"/api/v1/annotations/{ann['id']}", json={"note": "改"})
    monkeypatch.setattr(ann_mod, "utc_now", real_now)
    assert updated.status_code == 200
    third = client.post(
        "/api/v1/obsidian/export-handoff",
        json={
            "entryRef": ref,
            "deviceId": device["id"],
            "onlySinceLastExport": True,
        },
    )
    assert third.json()["annotationCount"] == 1


# ---------------------------------------------------------------------------
# N138 Vault 同步诊断（文件级）：rescan 报告 + 持久化 + 有界截断。
# ---------------------------------------------------------------------------


def _write_vault(tmp_path, files):
    for rel, content in files.items():
        target = tmp_path / "vault" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def test_scan_report_populates_file_lists(tmp_path):
    service, tmp = _obsidian_service(tmp_path)
    _write_vault(
        tmp,
        {
            "a.md": "---\ntitle: A\n---\nA",
            "b.md": "---\ntitle: B\n---\nB",
        },
    )
    report = _run(service.rescan())
    files = report["files"]
    assert sorted(files["added"]["items"]) == ["a.md", "b.md"]
    assert files["added"]["truncated"] is False

    # 更改 + 删除 + 跳过（二进制伪装 .md → 解析失败进 skipped）。
    (tmp / "vault" / "a.md").write_text("---\ntitle: A\n---\nA2", encoding="utf-8")
    (tmp / "vault" / "b.md").unlink()
    (tmp / "vault" / "bin.md").write_bytes(b"\x00\x01binary")
    report = _run(service.rescan())
    files = report["files"]
    assert files["changed"]["items"] == ["a.md"]
    assert files["removed"]["items"] == ["b.md"]
    assert files["skipped"]["items"] == ["bin.md"]
    assert files["skipped"]["truncated"] is False


def test_scan_file_lists_bounded_with_truncation_flag(tmp_path):
    service, tmp = _obsidian_service(tmp_path)
    _write_vault(tmp, {f"note-{i:03}.md": f"---\ntitle: N{i}\n---\n{i}" for i in range(55)})
    report = _run(service.rescan())
    added = report["files"]["added"]
    assert len(added["items"]) == 50
    assert added["truncated"] is True
    assert report["added"] == 55  # 计数仍是全量真值


def test_status_returns_last_scan_files_only_after_scan(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    service = ObsidianService(db)
    assert _run(service.get_status())["lastScanFiles"] is None  # 从未扫描 → 诚实 None

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("---\ntitle: A\n---\nA", encoding="utf-8")
    _run(service.set_vault_path(str(vault)))
    _run(service.rescan())
    status = _run(service.get_status())
    assert status["lastScanFiles"] is not None
    assert status["lastScanFiles"]["added"]["items"] == ["a.md"]
    # 第二次扫描覆盖（只保留最近一次：报告描述最近一次扫描本身）。
    (vault / "b.md").write_text("---\ntitle: B\n---\nB", encoding="utf-8")
    _run(service.rescan())
    status = _run(service.get_status())
    assert status["lastScanFiles"]["added"]["items"] == ["b.md"]
    assert status["lastScanFiles"]["changed"]["items"] == []  # a.md 未变不入最近报告
    assert status["noteCount"] == 2


def _obsidian_service(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    service = ObsidianService(db)
    vault = tmp_path / "vault"
    vault.mkdir()
    _run(service.set_vault_path(str(vault)))
    return service, tmp_path


# ---------------------------------------------------------------------------
# N139 导出侧链接校验：断链 wikilink / 缺失附件 / 重复块 id；只读报告。
# ---------------------------------------------------------------------------


def test_validate_flags_broken_wikilink_and_duplicate_block_id():
    index = build_projection_index(
        [
            {"rel_path": "notes/known.md", "title": "已知"},
        ]
    )
    markdown = (
        "# 标题\n\n参见 [[known]] 与 [[幽灵笔记]] 与 [[../逃逸]]。\n\n"
        "- 「摘」 ^lumi-p1\n- 「另」 ^lumi-p1\n"
    )
    issues = validate_export_markdown(markdown, projection_index=index, vault_exists=None)
    kinds = {issue["kind"] for issue in issues}
    assert "broken_wikilink" in kinds
    assert "duplicate_block_id" in kinds
    broken_details = " ".join(
        i["detail"] for i in issues if i["kind"] == "broken_wikilink"
    )
    assert "幽灵笔记" in broken_details and "逃逸" in broken_details
    assert "known" not in broken_details  # 已知笔记不误报
    # 每条问题都带 suggestion。
    assert all(issue["suggestion"] for issue in issues)


def test_validate_missing_attachment_only_with_vault(tmp_path):
    markdown = "![图](assets/pic.png)\n"
    index = build_projection_index([{"rel_path": "note.md", "title": "n"}])
    # Vault 不可用（vault_exists=None）：诚实跳过，不报假阳性。
    assert validate_export_markdown(markdown, projection_index=index) == []

    vault = tmp_path / "vault"
    vault.mkdir()

    def _exists(rel):
        target = vault / rel
        if not target.exists():
            return False
        return target.is_file()

    assert (
        validate_export_markdown(markdown, projection_index=index, vault_exists=_exists)[0][
            "kind"
        ]
        == "missing_attachment"
    )
    (vault / "assets").mkdir()
    (vault / "assets" / "pic.png").write_bytes(b"png")
    assert validate_export_markdown(markdown, projection_index=index, vault_exists=_exists) == []


def test_validate_clean_export_passes():
    index = build_projection_index([{"rel_path": "known.md", "title": "已知"}])
    markdown = "参见 [[known]]。\n\n- 「摘」 ^lumi-p1\n- 「另」 ^lumi-p2\n"
    assert validate_export_markdown(markdown, projection_index=index, vault_exists=lambda rel: True) == []


def test_validate_route_reports_issues_readonly(client, monkeypatch):
    from lumirss import deps
    from lumirss.entryref import encode_entry_ref

    ref = encode_entry_ref("item-1")
    device = client.post(
        "/api/v1/obsidian/devices",
        json={"label": "d", "vaultName": "v", "platform": "ios"},
    ).json()
    client.put(
        "/api/v1/obsidian/export-template",
        json={"template": "{{title}}\n\n参见 [[幽灵笔记]]。\n\n- 「摘」 ^lumi-p1\n- 「另」 ^lumi-p1\n"},
    )

    class _FakeAdapter:
        async def get_entry(self, item_id):
            return _Detail()

    monkeypatch.setattr(deps, "_get_adapter", lambda request: _FakeAdapter())

    validated = client.post(
        "/api/v1/obsidian/export-handoff/validate",
        json={"entryRef": ref, "deviceId": device["id"]},
    )
    assert validated.status_code == 200
    body = validated.json()
    assert body["vaultChecked"] is False  # 未配置 Vault：附件检查诚实未核对
    kinds = {issue["kind"] for issue in body["issues"]}
    assert "broken_wikilink" in kinds and "duplicate_block_id" in kinds

    # 校验是只读的：不落交接日志、不推进水位。
    log = client.get("/api/v1/obsidian/handoff-log")
    assert log.status_code == 200 and log.json()["items"] == []
    delta = client.get("/api/v1/annotations/export-delta")
    assert delta.json()["lastExportedAt"] is None


# ---------------------------------------------------------------------------
# N140 双向交接记录：pending 自动落库、显式确认、绝不自动确认、可清理。
# ---------------------------------------------------------------------------


def _make_device(client):
    return client.post(
        "/api/v1/obsidian/devices",
        json={"label": "d", "vaultName": "v", "platform": "ios"},
    ).json()


def _fake_adapter(monkeypatch):
    from lumirss import deps

    class _FakeAdapter:
        async def get_entry(self, item_id):
            return _Detail()

    monkeypatch.setattr(deps, "_get_adapter", lambda request: _FakeAdapter())


def test_handoff_log_export_pending_confirm_clear(client, monkeypatch):
    from lumirss.entryref import encode_entry_ref

    _fake_adapter(monkeypatch)
    device = _make_device(client)
    ref = encode_entry_ref("item-1")

    handoff = client.post(
        "/api/v1/obsidian/export-handoff",
        json={"entryRef": ref, "deviceId": device["id"]},
    )
    assert handoff.status_code == 200

    log = client.get("/api/v1/obsidian/handoff-log")
    assert log.status_code == 200
    items = log.json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["direction"] == "export"
    assert entry["status"] == "pending"
    assert entry["entryRef"] == ref
    assert entry["noteName"] == handoff.json()["filename"]
    assert entry["policy"] in ("timestamp_suffix", "exact")
    assert entry["confirmedAt"] is None

    # 被动事件（页面重载 = 重新拉取列表）绝不自动确认。
    reloaded = client.get("/api/v1/obsidian/handoff-log")
    assert reloaded.json()["items"][0]["status"] == "pending"

    confirmed = client.post(f"/api/v1/obsidian/handoff/{entry['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmedAt"] is not None

    # 显式重复确认幂等（confirmed_at 不被覆盖）；被动拉取仍是 confirmed。
    again = client.post(f"/api/v1/obsidian/handoff/{entry['id']}/confirm")
    assert again.status_code == 200
    assert again.json()["confirmedAt"] == confirmed.json()["confirmedAt"]

    missing = client.post("/api/v1/obsidian/handoff/no-such/confirm")
    assert missing.status_code == 404

    # 显式记录 import_confirm / open 方向。
    explicit = client.post(
        "/api/v1/obsidian/handoff-log",
        json={"direction": "import_confirm", "entryRef": "e1.a", "noteName": "手工导入.md"},
    )
    assert explicit.status_code == 201
    assert explicit.json()["direction"] == "import_confirm"
    assert explicit.json()["status"] == "pending"
    forged = client.post(
        "/api/v1/obsidian/handoff-log", json={"direction": "export"}
    )
    assert forged.status_code == 422  # export 只由 export-handoff 自动落库

    cleared = client.delete("/api/v1/obsidian/handoff-log")
    assert cleared.status_code == 200
    assert cleared.json()["cleared"] == 2
    assert client.get("/api/v1/obsidian/handoff-log").json()["items"] == []


def test_handoff_log_store_scoped_by_user_context(tmp_path):
    routed = RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users")
    with user_context("alice"):
        entry = _run(
            HandoffLogStore(routed).log_pending(
                direction="export", entry_ref="e1.a", note_name="n.md", policy="exact"
            )
        )
    with user_context("bob"):
        assert _run(HandoffLogStore(routed).list_entries()) == []
        assert _run(HandoffLogStore(routed).confirm(entry["id"])) is None
        assert _run(HandoffLogStore(routed).clear()) == 0
    with user_context("alice"):
        confirmed = _run(HandoffLogStore(routed).confirm(entry["id"]))
        assert confirmed is not None and confirmed["status"] == "confirmed"
        assert _run(HandoffLogStore(routed).clear()) == 1
