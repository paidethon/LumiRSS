"""N124 快照资源预算 + 选择性清理 — GET /storage 与 POST /cleanup。

- sizes computed：totalBytes = 磁盘文件真实大小；breakdown 按内联
  data: URI 的 MIME 类别拆分（images 计数、styles/attachments 字节）；
- cleanup 只删除选中类别：条目本体（HTML 文本/标题/library 行）保留；
  被清理的子资源在既有完整性清单（resources）中如实标记 missing；
- 共享文件（sha256 去重）清理互不串扰：本行迁移私有新文件，他人内容
  一字不动；条目在清理后仍然存活可读。
"""

import asyncio
import base64
import hashlib

from lumirss.library_assets import AssetStore


def run(coro):
    return asyncio.run(coro)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _crafted_html() -> tuple[bytes, dict[str, int]]:
    """2 张内联图片 + 1 个内联样式 + 1 个内联附件；附带远程 URL 子资源
    （进入 resources 清单，用于验证 missing 标记）。"""
    sizes = {"img1": 300, "img2": 45, "css": 120, "attach": 77}
    html = (
        "<html><head>"
        f'<link href="data:text/css;base64,{_b64(b"c" * sizes["css"])}" rel="stylesheet">'
        '<link href="https://cdn.example/style.css" rel="stylesheet">'
        "</head><body><h1>正文标题</h1><p>快照正文保持不动。</p>"
        f'<img src="data:image/png;base64,{_b64(b"a" * sizes["img1"])}" alt="1">'
        f'<img src="data:image/jpeg;base64,{_b64(b"b" * sizes["img2"])}" alt="2">'
        '<img src="https://cdn.example/pic.png" alt="r">'
        f'<audio src="data:application/octet-stream;base64,{_b64(b"d" * sizes["attach"])}"></audio>'
        "</body></html>"
    )
    return html.encode(), sizes


def _wire_runner(client, body: bytes):
    # 先发一次列表请求：basic 模式会把真实（按用户目录的）asset_store
    # 镜像到 app.state —— 测试的 stub runner 必须写进同一个根目录。
    warmed = client.get("/api/v1/library/snapshots")
    assert warmed.status_code == 200, warmed.text
    assets = AssetStore(client.app.state.db, client.app.state.asset_store.root)

    class _FixedRunner:
        async def run(self, url: str) -> dict:
            from lumirss.snapshot_versions import extract_resource_urls

            record, deduped = await assets.save_snapshot(
                data=body, mime="text/html", url=url
            )
            diag = extract_resource_urls(body.decode(), url)
            return {
                "asset": record.to_dict(),
                "deduplicated": deduped,
                "capturedAt": "2026-09-25T00:00:00Z",
                "url": url,
                "resources": diag["resources"],
                "resourcesTruncated": diag["truncated"],
                "_data": body,
            }

    runner = _FixedRunner()
    client.app.state.snapshot_runner = runner
    return assets


def _create_snapshot(client, url: str) -> str:
    created = client.post("/api/v1/library/snapshots", json={"url": url})
    assert created.status_code == 201, created.text
    return created.json()["uuid"]


def _rewrite_file(client, assets: AssetStore, uuid: str, data: bytes) -> None:
    async def _write():
        row = await client.app.state.db.fetch_one(
            "SELECT path FROM library_assets WHERE uuid = ?", (uuid,)
        )
        assert row is not None
        (assets.root / str(row["path"])).write_bytes(data)

    run(_write())


def _decoded_len(raw: bytes) -> int:
    payload = base64.b64encode(raw).decode()
    stripped = payload.rstrip("=")
    return len(stripped) * 3 // 4


def test_base64_len_arithmetic_is_exact():
    for raw in (b"", b"1", b"12", b"123", b"1234", b"12345", b"x" * 999):
        assert _decoded_len(raw) == len(base64.b64decode(_b64(raw) + "==="))


def test_storage_sizes_computed(client):
    data, sizes = _crafted_html()
    assets = _wire_runner(client, data)
    uuid = _create_snapshot(client, "https://example.test/page-a")
    _rewrite_file(client, assets, uuid, data)

    body = client.get(f"/api/v1/library/snapshots/{uuid}/storage").json()
    assert body["uuid"] == uuid
    assert body["totalBytes"] == len(data)
    assert body["breakdown"]["images"]["count"] == 2
    assert body["breakdown"]["images"]["bytes"] == _decoded_len(b"a" * sizes["img1"]) + _decoded_len(b"b" * sizes["img2"])
    assert body["breakdown"]["styles"]["bytes"] == _decoded_len(b"c" * sizes["css"])
    assert body["breakdown"]["attachments"]["bytes"] == _decoded_len(b"d" * sizes["attach"])

    # 未知快照 → 404
    assert client.get("/api/v1/library/snapshots/library:none/storage").status_code == 404


def test_cleanup_removes_only_selected_kind_and_marks_missing(client):
    data, sizes = _crafted_html()
    assets = _wire_runner(client, data)
    uuid = _create_snapshot(client, "https://example.test/page-b")
    _rewrite_file(client, assets, uuid, data)

    # 清理清单里的远程子资源（skipped）先就位
    detail = client.get(f"/api/v1/library/snapshots/{uuid}").json()
    assert any(r["status"] == "skipped" and r["url"].endswith(".png") for r in detail["resources"])
    assert any(r["status"] == "skipped" and r["url"].endswith(".css") for r in detail["resources"])

    resp = client.post(f"/api/v1/library/snapshots/{uuid}/cleanup", json={"kinds": ["images"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cleaned"] == {"images": 2}

    # 只删了图片：styles/attachments 原样；totalBytes 相应缩小
    storage = body["storage"]
    assert storage["breakdown"]["images"] == {"count": 0, "bytes": 0}
    assert storage["breakdown"]["styles"]["bytes"] == _decoded_len(b"c" * sizes["css"])
    assert storage["breakdown"]["attachments"]["bytes"] == _decoded_len(b"d" * sizes["attach"])

    # 条目本体保留：标题与正文一字不动
    kept = client.get(f"/api/v1/library/snapshots/{uuid}")
    assert kept.status_code == 200
    page = client.get(f"/api/v1/library/assets/{uuid}/page.html")
    assert page.status_code == 200
    assert "正文标题" in page.text and "快照正文保持不动" in page.text
    assert "data:image" not in page.text

    # 完整性清单：远程图片标记 missing；远程样式仍是 skipped
    detail = client.get(f"/api/v1/library/snapshots/{uuid}").json()
    by_url = {r["url"]: r["status"] for r in detail["resources"]}
    assert by_url["https://cdn.example/pic.png"] == "missing"
    assert by_url["https://cdn.example/style.css"] == "skipped"

    # 再次清理 → 幂等 no-op（如实回 0）
    again = client.post(f"/api/v1/library/snapshots/{uuid}/cleanup", json={"kinds": ["images"]}).json()
    assert again["cleaned"]["images"] == 0

    # 白名单外/空 kinds → 422；未知快照 → 404
    assert client.post(f"/api/v1/library/snapshots/{uuid}/cleanup", json={"kinds": []}).status_code == 422
    assert client.post(
        f"/api/v1/library/snapshots/{uuid}/cleanup", json={"kinds": ["videos"]}
    ).status_code == 422
    assert client.post(
        "/api/v1/library/snapshots/library:none/cleanup", json={"kinds": ["images"]}
    ).status_code == 404


def test_cleanup_entry_survives_and_shared_file_isolated(client):
    data, sizes = _crafted_html()
    _assets = _wire_runner(client, data)
    uuid_a = _create_snapshot(client, "https://example.test/shared-a")
    uuid_b = _create_snapshot(client, "https://example.test/shared-b")  # 同内容 → 去重共享
    row = run(
        client.app.state.db.fetch_one(
            "SELECT COUNT(*) AS n FROM library_assets WHERE sha256 = ?",
            (hashlib.sha256(data).hexdigest(),),
        )
    )
    assert int(row["n"]) == 2  # 确为共享字节

    resp = client.post(f"/api/v1/library/snapshots/{uuid_a}/cleanup", json={"kinds": ["styles"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["cleaned"]["styles"] == 1

    # A 已清理；B 的内容一字不动（共享文件没有被改写）
    page_b = client.get(f"/api/v1/library/assets/{uuid_b}/page.html")
    assert page_b.status_code == 200
    assert f'base64,{_b64(b"c" * sizes["css"])}' in page_b.text
    assert client.get(f"/api/v1/library/snapshots/{uuid_b}/storage").json()["totalBytes"] == len(data)
    page_a = client.get(f"/api/v1/library/assets/{uuid_a}/page.html")
    assert "data:text/css" not in page_a.text
    # 两个条目都存活（library 行未删）
    assert client.get(f"/api/v1/library/snapshots/{uuid_a}").status_code == 200
    assert client.get(f"/api/v1/library/snapshots/{uuid_b}").status_code == 200
