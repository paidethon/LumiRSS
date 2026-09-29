"""NEW-326 附件引用可移植打包 — 相对链接重写、越界校验、A/B 隔离。"""

import io
import zipfile

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new321_vault import write_vault

NOTE_WITH_ASSETS = """---
title: 打包笔记
---
正文开头。

![图片](assets/pic.png)

![缺失](assets/nope.png)

![越界](../../outside.png)

![远程](https://img.example/remote.png)
"""


def _setup(client, owner, tmp_path):
    vault = write_vault(
        tmp_path,
        {
            "notes/打包笔记.md": NOTE_WITH_ASSETS,
            "notes/assets/pic.png": "\x89PNG-fake-bytes",
        },
    )
    # Vault 外的越界目标（打包必须拒绝收录）
    outside = tmp_path / "outside.png"
    outside.write_text("secret", encoding="utf-8")
    created = client.put(
        "/api/v1/obsidian/settings", json={"vaultPath": str(vault)}, headers=owner
    )
    assert created.status_code == 200, created.text
    assert (
        client.post("/api/v1/obsidian/rescan", headers=owner).status_code == 200
    )
    from new321_vault import note_uuids

    return note_uuids(client, owner)


def _download_zip(client, owner, note_uuid):
    created = client.post(
        "/api/v1/obsidian/bundles", json={"noteRefs": [note_uuid]}, headers=owner
    )
    assert created.status_code == 200, created.text
    manifest = created.json()
    bundle_id = manifest["id"]
    download = client.get(f"/api/v1/obsidian/bundles/{bundle_id}/download", headers=owner)
    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    return manifest, archive


def test_new326_bundle_rewrites_links_and_flags_violations(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    uuids = _setup(client, owner, tmp_path)
    note_uuid = uuids["notes/打包笔记.md"]

    manifest, archive = _download_zip(client, owner, note_uuid)
    bundle_id = manifest["id"]
    # 附件收录：允许扩展名 + Vault 内 + 存在
    assert manifest["attachmentCount"] == 1
    assert manifest["attachments"][0]["archivePath"] == "attachments/pic.png"
    names = archive.namelist()
    assert "attachments/pic.png" in names
    assert "manifest.json" in names
    note_arc = next(name for name in names if name.startswith("notes/"))
    bundled_text = archive.read(note_arc).decode("utf-8")
    # 相对链接重写
    assert "](../attachments/pic.png)" in bundled_text
    # 越界/缺失引用被移除并逐条记录（不残留包外文件引用）
    assert "../../outside.png" not in bundled_text
    assert "assets/nope.png" not in bundled_text
    assert "<!-- LumiRSS" in bundled_text
    kinds = {v["kind"] for v in manifest["violations"]}
    assert "escaped_vault" in kinds and "missing" in kinds
    # 远程图片链接保留（不是文件引用，不属于越界）
    assert "https://img.example/remote.png" in bundled_text
    # 终检：无越界引用残留
    assert not any(
        v["kind"] == "out_of_bounds_reference" for v in manifest["violations"]
    )

    # 台账可查
    listing = client.get("/api/v1/obsidian/bundles", headers=owner).json()
    assert listing["bundles"][0]["id"] == bundle_id
    detail = client.get(f"/api/v1/obsidian/bundles/{bundle_id}", headers=owner)
    assert detail.status_code == 200
    assert detail.json()["violationCount"] == len(manifest["violations"])
    missing_download = client.get(
        "/api/v1/obsidian/bundles/no-such/download", headers=owner
    )
    assert missing_download.status_code == 404


def test_new326_bundle_validation_rejected_400(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _setup(client, owner, tmp_path)
    empty = client.post("/api/v1/obsidian/bundles", json={"noteRefs": []}, headers=owner)
    assert empty.status_code == 400
    unknown = client.post(
        "/api/v1/obsidian/bundles", json={"noteRefs": ["no-such-uuid"]}, headers=owner
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["type"] == "invalid_bundle"


def test_new326_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    uuids = _setup(client, owner, tmp_path)
    created = client.post(
        "/api/v1/obsidian/bundles",
        json={"noteRefs": [uuids["notes/打包笔记.md"]]},
        headers=owner,
    )
    assert created.status_code == 200
    bundle_id = created.json()["id"]
    # B：组包 / 台账 / 下载全部 403
    assert (
        client.post(
            "/api/v1/obsidian/bundles",
            json={"noteRefs": [uuids["notes/打包笔记.md"]]},
            headers=b,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/obsidian/bundles", headers=b).status_code == 403
    assert (
        client.get(f"/api/v1/obsidian/bundles/{bundle_id}/download", headers=b).status_code
        == 403
    )
    # owner 台账仍只有自己的一条
    listing = client.get("/api/v1/obsidian/bundles", headers=owner).json()
    assert len(listing["bundles"]) == 1 and listing["bundles"][0]["id"] == bundle_id
