"""NEW-383 离线 HTML 资料集 — 只含选中内容、包内链接自洽、越界引用
拦截、A/B 隔离。"""

import io
import zipfile

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import ZOTERO_RDF, new_uuid, seed_clip


def _import_bib(client, who):
    created = client.post(
        "/api/v1/preservation/zotero/import",
        content=ZOTERO_RDF.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )
    assert created.status_code == 201, created.text
    records = client.get("/api/v1/preservation/records", headers=who).json()["records"]
    return {record["title"]: record["id"] for record in records}


def _build(client, who, bib_ids, clip_refs):
    return client.post(
        "/api/v1/preservation/offline-sites",
        json={"bibIds": bib_ids, "clipRefs": [f"library:{ref}" for ref in clip_refs]},
        headers=who,
    )


def test_new383_package_contains_only_selected(ab_env, tmp_path):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    bib = _import_bib(client, a)
    clip_a = seed_clip(
        ab_env, "a",
        url="https://clip.example/a",
        title="剪藏甲",
        html="<p>甲的正文段落。</p>",
    )
    # 同一用户库里另一条未选剪藏——绝不能进包
    seed_clip(
        ab_env, "a",
        url="https://clip.example/private",
        title="私人未选剪藏",
        html="<p>不应出现的私人内容。</p>",
    )
    bib_id = bib["长期保存的格式迁移研究"]
    created = _build(client, a, [bib_id], [clip_a])
    assert created.status_code == 200, created.text
    manifest = created.json()
    site_id = manifest["id"]
    assert manifest["itemCount"] == 2  # 1 书目 + 1 剪藏
    # 未选内容不进包（索引与 manifest 都不含）
    download = client.get(
        f"/api/v1/preservation/offline-sites/{site_id}/download", headers=a
    )
    assert download.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(download.content))
    blob = b"".join(archive.read(name) for name in archive.namelist())
    assert "私人未选剪藏".encode() not in blob
    assert "不应出现的私人内容".encode() not in blob
    assert "剪藏甲".encode() in blob
    assert "长期保存的格式迁移研究".encode() in blob
    assert "index.html" in archive.namelist()
    assert "manifest.json" in archive.namelist()
    # 台账
    sites = client.get("/api/v1/preservation/offline-sites", headers=a).json()
    assert sites["sites"][0]["id"] == site_id


def test_new383_external_links_recorded_violations_blocked(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    clip = seed_clip(
        ab_env, "a",
        url="https://clip.example/links",
        title="外链剪藏",
        html='<p><a href="https://out.example/x">外链</a>'
        '<a href="../../../escape">越界</a>'
        '<a href="file:///etc/passwd">file</a></p>',
    )
    created = _build(client, a, [], [clip])
    assert created.status_code == 200
    manifest = created.json()
    targets = {v["target"] for v in manifest["violations"]}
    # 越界相对链接被终检拦下并如实记账
    assert any(target.startswith("../../../") for target in targets)
    # http(s) 外链保留为普通外链（记入 externalLinks，非违规）
    assert "https://out.example/x" in manifest["externalLinks"]
    assert not any("https://out.example/x" in target for target in targets)
    # file: 危险链接在净化边界就被移除——包里连 href 都不存在
    site_id = manifest["id"]
    download = client.get(
        f"/api/v1/preservation/offline-sites/{site_id}/download", headers=a
    )
    import io as _io
    import zipfile as _zipfile

    archive = _zipfile.ZipFile(_io.BytesIO(download.content))
    blob = b"".join(archive.read(name) for name in archive.namelist())
    assert b"file:" not in blob
    # 越界目标只能以「违规台账记录」的形式出现（如实记账），
    # 绝不能以任何链接属性的形式残留
    assert b'href="../../../escape"' not in blob
    assert b'href="file:' not in blob


def test_new383_validation_and_missing(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    empty = _build(client, a, [], [])
    assert empty.status_code == 400
    unknown = _build(client, a, [f"bib-{new_uuid()}"], [])
    assert unknown.status_code == 200  # 缺失如实进 manifest.missing
    assert unknown.json()["missing"]


def test_new383_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    clip_a = seed_clip(
        ab_env, "a",
        url="https://clip.example/only-a",
        title="甲的独有剪藏",
        html="<p>甲的内容。</p>",
    )
    created = _build(client, a, [], [clip_a])
    site_id = created.json()["id"]
    # B 查不到 A 的台账/manifest，也下载不了 A 的包
    assert client.get(
        f"/api/v1/preservation/offline-sites/{site_id}", headers=b
    ).status_code == 404
    assert client.get(
        f"/api/v1/preservation/offline-sites/{site_id}/download", headers=b
    ).status_code == 404
    assert client.get("/api/v1/preservation/offline-sites", headers=b).json()[
        "sites"
    ] == []
