"""F088 资料包导出增强 — manifest 计数/sha256、路径穿越拒绝（负向）、
超限 413、缺失资产诚实跳过、快照去重。"""

import asyncio
import hashlib
import io
import json
import zipfile

import pytest

from lumirss.main import app
from lumirss.research_pack_zip import (
    ResearchPackZipBuilder,
    ZipInvalid,
    ZipTooLarge,
    safe_member_path,
)

TMP_ROOT = None


def run(coro):
    return asyncio.run(coro)


def _builder(client, tmp_path, assets: dict[str, bytes]):
    async def _seed_asset(name: str, data: bytes):
        await app.state.db.migrate()
        parent = f"00000000-0000-4000-8000-0000000008{abs(hash(name)) % 100:02d}"
        await app.state.db.execute(
            "INSERT OR IGNORE INTO library_items (uuid, kind, created_at) VALUES (?, 'snapshot', '2026-01-01T00:00:00Z')",
            (parent,),
        )
        await app.state.db.execute(
            "INSERT INTO library_assets (uuid, item_uuid, path, bytes, sha256, mime, created_at) VALUES (?, ?, ?, ?, ?, 'text/html', '2026-01-01T00:00:00Z')",
            (f"ast-{name}", parent, f"raw/{name}", len(data), hashlib.sha256(data).hexdigest()),
        )

    for name, data in assets.items():
        p = tmp_path / "raw" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        run(_seed_asset(name, data))
    return ResearchPackZipBuilder(app.state.db, tmp_path)


def _cleanup_assets():
    async def _wipe():
        await app.state.db.execute("DELETE FROM library_assets")

    run(_wipe())


def test_f088_manifest_counts_and_sha256(client, tmp_path):
    builder = _builder(client, tmp_path, {"a.html": b"hello world", "b.html": b"xxxx"})
    try:
        payload, manifest = builder and run(
            builder.build_zip(
                markdown="# 研究包",
                entry_count=3,
                missing_count=0,
                include_snapshots=["ast-a.html", "ast-b.html"],
            )
        )
        zf = zipfile.ZipFile(io.BytesIO(payload))
        names = zf.namelist()
        assert manifest["fileCount"] == len(names)
        assert manifest["fileCount"] == 4  # md + 2 快照 + manifest.json
        # manifest 计数 == 包内文件
        assert sorted(n for n in names if n != "manifest.json") == sorted(
            f["path"] for f in manifest["files"] if f["path"] != "manifest.json"
        )
        # sha256 校验匹配
        for f in manifest["files"]:
            assert hashlib.sha256(zf.read(f["path"])).hexdigest() == f["sha256"]
        # 同一资产引用两次只打包一份（快照去重）
        payload2, manifest2 = run(
            builder.build_zip(
                markdown="# 研究包",
                entry_count=3,
                missing_count=0,
                include_snapshots=["ast-a.html", "ast-a.html"],
            )
        )
        assert manifest2["snapshots"] == ["ast-a.html"]
        assert manifest2["fileCount"] == 3  # md + 1 快照 + manifest.json
    finally:
        _cleanup_assets()


def test_f088_missing_asset_recorded_in_manifest(client, tmp_path):
    builder = _builder(client, tmp_path, {"present.html": b"data"})
    try:
        payload, manifest = run(
            builder.build_zip(
                markdown="# 研究包",
                entry_count=1,
                missing_count=0,
                include_snapshots=["ast-present.html", "ast-ghost.html"],
            )
        )
        assert "ast-ghost.html" in manifest["missing"]
        manifest_doc = json.loads(
            zipfile.ZipFile(io.BytesIO(payload)).read("manifest.json")
        )
        assert manifest_doc["missing"] == manifest["missing"]
    finally:
        _cleanup_assets()


def test_f088_path_traversal_rejected(client, tmp_path):
    # 负向：构造路径穿越成员被拒
    with pytest.raises(ZipInvalid):
        safe_member_path("../evil.txt")
    with pytest.raises(ZipInvalid):
        safe_member_path("snapshots/../../etc/passwd")
    with pytest.raises(ZipInvalid):
        safe_member_path("/absolute/path")


def test_f088_size_cap_413(client, tmp_path, monkeypatch):
    from lumirss import research_pack_zip as mod

    builder = _builder(client, tmp_path, {})
    monkeypatch.setattr(mod, "MAX_ZIP_BYTES", 64)
    with pytest.raises(ZipTooLarge):
        run(
            builder.build_zip(
                markdown="x" * 200,
                entry_count=0,
                missing_count=0,
                include_snapshots=[],
            )
        )


def test_f088_preview_route_counts(client, tmp_path, monkeypatch):

    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path))
    # 直接构造 builder 预览（路由层数据目录按 env 即时读取）
    builder = ResearchPackZipBuilder(app.state.db, tmp_path)
    preview = run(builder.preview(entry_count=2, missing_count=1, include_snapshots=[]))
    assert preview["entryCount"] == 2
    assert preview["missingCount"] == 1
    assert preview["snapshots"] == []
    assert preview["estBytes"] > 0
