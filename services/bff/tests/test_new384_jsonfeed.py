"""NEW-384 JSON Feed 个人导出 — 标准 1.1 结构、字段与授权范围说明、
A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import ZOTERO_RDF, seed_clip


def _feed(client, who, scopes):
    return client.post(
        "/api/v1/preservation/json-feed", json={"scopes": scopes}, headers=who
    )


def test_new384_standard_jsonfeed_structure(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    created = client.post(
        "/api/v1/preservation/zotero/import",
        content=ZOTERO_RDF.encode("utf-8"),
        headers={**a, "content-type": "application/octet-stream"},
    )
    assert created.status_code == 201
    seed_clip(ab_env, "a", url="https://clip.example/f1", title="剪藏一",
              html="<p>内容一</p>")
    response = _feed(client, a, ["clips", "bib"])
    assert response.status_code == 200, response.text
    feed = response.json()
    # JSON Feed 1.1 标准字段
    assert feed["version"] == "https://jsonfeed.org/version/1.1"
    assert feed["title"]
    assert len(feed["items"]) == 3  # 1 剪藏 + 2 书目
    ids = {item["id"] for item in feed["items"]}
    assert "lumi-clip:" in "".join(ids) and "lumi-bib:" in "".join(ids)
    clip_item = next(item for item in feed["items"] if item["id"].startswith("lumi-clip:"))
    assert clip_item["url"] == "https://clip.example/f1"
    assert clip_item["content_html"] == "<p>内容一</p>"
    # externalId 进了 id（lumi-bib:<record id> 不一定含 externalId，
    # 但书目条目的 title 必须在）
    assert any("长期保存" in item["title"] for item in feed["items"])
    # 字段清单与授权范围如实说明（description + _lumi 扩展）
    assert "fieldsIncluded" in feed["_lumi"]
    assert "authorizationScope" in feed["_lumi"]
    assert "本人" in feed["_lumi"]["authorizationScope"]
    assert "本人" in feed["description"]



def test_new384_scope_validation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    bad = _feed(client, a, ["clips", "not-a-scope"])
    assert bad.status_code == 400
    empty = _feed(client, a, [])
    assert empty.status_code == 400
    nothing = _feed(client, a, ["bib"])  # 范围合法但没有数据
    assert nothing.status_code == 400
    assert "没有可导出" in nothing.json()["error"]["message"]


def test_new384_download_and_ledger(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    seed_clip(ab_env, "a", url="https://clip.example/dl", title="剪藏二",
              html="<p>内容二</p>")
    download = client.post(
        "/api/v1/preservation/json-feed/download",
        params={"scopes": ["clips"]},
        headers=a,
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    feed = download.json()
    assert feed["version"].endswith("1.1")
    assert len(feed["items"]) == 1
    exports = client.get("/api/v1/preservation/json-feed/exports", headers=a).json()
    assert exports["exports"][0]["clipCount"] == 1
    assert exports["exports"][0]["scope"] == "clips"


def test_new384_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    seed_clip(ab_env, "a", url="https://clip.example/only-a", title="甲独有",
              html="<p>甲</p>")
    feed_a = _feed(client, a, ["clips"]).json()
    assert len(feed_a["items"]) == 1
    # B 的 feed 不含 A 的剪藏
    empty_b = _feed(client, b, ["clips"])
    assert empty_b.status_code == 400  # B 范围内没有数据
    seed_clip(ab_env, "b", url="https://clip.example/only-b", title="乙独有",
              html="<p>乙</p>")
    feed_b = _feed(client, b, ["clips"]).json()
    titles = {item["title"] for item in feed_b["items"]}
    assert "乙独有" in titles and "甲独有" not in titles
    # 台账隔离
    b_exports = client.get("/api/v1/preservation/json-feed/exports", headers=b).json()
    assert all(entry["clipCount"] == 1 for entry in b_exports["exports"])
