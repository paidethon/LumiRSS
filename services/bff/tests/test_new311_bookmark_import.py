"""NEW-311 浏览器书签目录导入 — 预览目录映射/重复链接、确认形成集合、A/B 隔离。"""

import pytest

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

NETSCAPE = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
  <DT><H3>技术</H3>
  <DL><p>
    <DT><A HREF="https://a.example/one">文章一</A>
    <DT><A HREF="https://a.example/one">文章一副本</A>
    <DT><A HREF="https://b.example/two">文章二</A>
    <DT><A HREF="not-a-url">坏链接</A>
  </DL><p>
  <DT><H3>设计</H3>
  <DL><p>
    <DT><A HREF="https://c.example/three">文章三</A>
  </DL><p>
</DL><p>
"""


def _preview(client, headers):
    return client.post(
        "/api/v1/library/bookmarks/import/preview",
        content=NETSCAPE.encode("utf-8"),
        headers={**headers, "content-type": "text/html"},
    )


def _confirm(client, headers, *, folders=(), include_duplicates=False, name="浏览器书签"):
    params = [("sourceName", name)]
    for f in folders:
        params.append(("folder", f))
    if include_duplicates:
        params.append(("includeDuplicates", "true"))
    return client.post(
        "/api/v1/library/bookmarks/import/sets",
        content=NETSCAPE.encode("utf-8"),
        params=params,
        headers={**headers, "content-type": "text/html"},
    )


def test_new311_preview_maps_folders_and_duplicates_without_writes(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    # 库里已有 文章二 → inLibrary 重复；文件内 文章一 出现两次 → inFile 重复
    created = client.post(
        "/api/v1/library/bookmarks",
        json={"title": "文章二（已存）", "url": "https://b.example/two"},
        headers=a,
    )
    assert created.status_code == 201, created.text

    preview = _preview(client, a)
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total"] == 5
    assert body["validTotal"] == 4
    paths = {f["path"]: f["count"] for f in body["folderMap"]}
    assert paths == {"技术": 4, "设计": 1}

    dup_urls = {d["url"]: d for d in body["duplicates"]}
    assert dup_urls["https://a.example/one"]["inFile"] is True
    assert dup_urls["https://a.example/one"]["inLibrary"] is False
    assert dup_urls["https://b.example/two"]["inLibrary"] is True
    assert dup_urls["https://b.example/two"]["inFile"] is False

    assert len(body["invalid"]) == 1
    assert body["invalid"][0]["url"] == "not-a-url"

    # 预览零写入：书签数不变（仍只有预置的 1 条）
    listing = client.get("/api/v1/library/bookmarks", headers=a).json()
    assert len(listing["items"]) == 1


def test_new311_confirm_respects_folder_selection_and_counts_honestly(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    result = _confirm(client, a, folders=["技术"], name="技术目录导入")
    assert result.status_code == 201, result.text
    body = result.json()
    # 技术目录 4 条：一条文件内重复跳过、一条坏链接 invalid、两条 imported
    assert body["total"] == 5
    assert body["imported"] == 2
    assert body["skipped"] == 3
    assert body["statuses"] == {
        "imported": 2,
        "duplicate": 1,
        "invalid": 1,
        "excluded": 1,
    }
    assert body["folders"] == ["技术"]

    # 台账可查：集合行 + 逐条状态
    sets = client.get("/api/v1/library/bookmarks/import/sets", headers=a).json()["sets"]
    assert len(sets) == 1 and sets[0]["id"] == body["id"]
    detail = client.get(
        f"/api/v1/library/bookmarks/import/sets/{body['id']}", headers=a
    )
    assert detail.status_code == 200
    items = detail.json()["items"]
    assert len(items) == 5
    by_status = {}
    for item in items:
        by_status.setdefault(item["status"], []).append(item["url"])
    assert sorted(by_status["imported"]) == [
        "https://a.example/one",
        "https://b.example/two",
    ]
    # excluded = 设计目录（未勾选）里的有效链接
    assert by_status["excluded"] == ["https://c.example/three"]
    # imported 的书签真实存在（Library 域）
    listing = client.get("/api/v1/library/bookmarks", headers=a).json()
    urls = {b["url"] for b in listing["items"]}
    assert "https://a.example/one" in urls
    assert "https://b.example/two" in urls

    # 幂等重放同一文件 → 全部 duplicate，诚实计数
    replay = _confirm(client, a, folders=["技术"], name="重放")
    assert replay.status_code == 201
    assert replay.json()["imported"] == 0
    assert replay.json()["statuses"]["duplicate"] >= 1

    detail_404 = client.get(
        "/api/v1/library/bookmarks/import/sets/no-such-set", headers=a
    )
    assert detail_404.status_code == 404


def test_new311_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    # B 先存 文章三
    assert (
        client.post(
            "/api/v1/library/bookmarks",
            json={"title": "B 的书签", "url": "https://c.example/three"},
            headers=b,
        ).status_code
        == 201
    )
    # A 的预览：不得把 B 的书签判为 inLibrary 重复
    body = _preview(client, a).json()
    dup_urls = {d["url"] for d in body["duplicates"]}
    assert "https://c.example/three" not in dup_urls

    # A 形成集合后，B 的台账为空；B 查 A 的集合 → 404
    created = _confirm(client, a, folders=["设计"])
    assert created.status_code == 201
    assert client.get("/api/v1/library/bookmarks/import/sets", headers=b).json()[
        "sets"
    ] == []
    other = client.get(
        f"/api/v1/library/bookmarks/import/sets/{created.json()['id']}", headers=b
    )
    assert other.status_code == 404

    # B 的书签列表不受 A 导入影响（A 只导入设计目录 → c.example/three 已被
    # B 占用；A 侧该条收敛为 duplicate，B 的标题不变）
    b_titles = [
        b_["title"]
        for b_ in client.get("/api/v1/library/bookmarks", headers=b).json()["items"]
    ]
    assert b_titles == ["B 的书签"]


@pytest.mark.parametrize("payload", [b"", b"<html>no bookmarks here</html>"])
def test_new311_invalid_file_rejected_400(ab_env, payload):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    bad = client.post(
        "/api/v1/library/bookmarks/import/preview",
        content=payload,
        headers={**a, "content-type": "text/html"},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "invalid_import_file"
