"""NEW-381 Zotero RDF 导入 — 字段映射预览、原始引用标识保留、重复
资料识别、A/B 隔离、敌意输入上限。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import ZOTERO_RDF, new_uuid


def _preview(client, who, text=ZOTERO_RDF):
    return client.post(
        "/api/v1/preservation/zotero/preview",
        content=text.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )


def _import(client, who, text=ZOTERO_RDF, **params):
    return client.post(
        "/api/v1/preservation/zotero/import",
        params=params or None,
        content=text.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )


def test_new381_preview_maps_fields_and_keeps_external_id(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    response = _preview(client, a)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["format"] == "zotero_rdf"
    assert preview["total"] == 2
    first = preview["items"][0]
    # 原始引用标识：rdf:about 末段 item key 原样保留
    assert first["externalId"] == "ABCD1234"
    assert first["title"] == "长期保存的格式迁移研究"
    assert first["creators"] == ["陈, 静"]  # 间接 foaf 引用解析
    assert first["pubYear"] == "2024"
    assert first["publication"] == "档案学刊"
    assert first["publisher"] == "档案出版社"
    assert first["doi"] == "10.1000/pres.2024"
    assert first["itemType"] == "journalArticle"
    assert "数字保存" in first["tags"]
    # 不支持字段如实列出（bibo:pages），不假装映射
    assert "bibo:pages" in first["unsupportedFields"]
    assert preview["unsupportedFields"] == ["bibo:pages"]
    # 未登录/无文件 → 400（空 RDF）
    empty = _preview(client, a, "<?xml version='1.0'?><rdf:RDF xmlns:rdf='u'/>")
    assert empty.status_code == 400


def test_new381_import_dedupes_and_reports(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    first = _import(client, a)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["imported"] == 2 and body["duplicates"] == 0
    # 二次导入：external_id 命中 → 重复跳过（不无声覆盖，保原始值）
    second = _import(client, a).json()
    assert second["imported"] == 0 and second["duplicates"] == 2
    # includeDuplicates=true → 唯一索引兜底：同一引用标识绝不覆盖既有
    # 原始值，逐条以 failed 如实报告
    forced = _import(client, a, includeDuplicates="true").json()
    assert forced["imported"] == 0 and forced["failed"] == 2
    assert all("不覆盖既有值" in f["reason"] for f in forced["failures"])
    listing = client.get(
        "/api/v1/preservation/records?format=zotero_rdf", headers=a
    ).json()
    assert {r["externalId"] for r in listing["records"]} == {"ABCD1234", "EFGH5678"}


def test_new381_duplicate_detection_against_existing(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    _import(client, a)
    response = _preview(client, a).json()
    assert response["duplicates"] == 2
    dup = response["items"][0]
    assert dup["duplicate"] is True and dup["duplicateReason"] == "external_id"


def test_new381_hostile_input_capped(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    broken = _preview(client, a, "this is not <xml at all")
    assert broken.status_code == 400
    # 条目数上限：>2000 条 z:item → 400（构造到边界之上一点点即可）
    many = "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' " \
           "xmlns:z='http://www.zotero.org/namespaces/export#'>" + "".join(
        f"<z:item rdf:about='http://x/items/K{i:06d}'><dc:title"
        " xmlns:dc='http://purl.org/dc/elements/1.1/'>t</dc:title></z:item>"
        for i in range(2001)
    ) + "</rdf:RDF>"
    capped = _preview(client, a, many)
    assert capped.status_code == 400
    assert "上限" in capped.json()["error"]["message"]


def test_new381_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    _import(client, a)
    # B 的清单为空——A 导入的书目对 B 不可见
    b_records = client.get("/api/v1/preservation/records", headers=b).json()
    assert b_records["records"] == []
    # B 重复检测面也看不到 A 的条目：同一文件 B 导入全部为新增
    b_import = _import(client, b).json()
    assert b_import["imported"] == 2 and b_import["duplicates"] == 0
    # B 的记录 id 与 A 的互不相同
    a_ids = {
        r["id"]
        for r in client.get("/api/v1/preservation/records", headers=a).json()["records"]
    }
    b_ids = {
        r["id"]
        for r in client.get("/api/v1/preservation/records", headers=b).json()["records"]
    }
    assert a_ids and b_ids and not (a_ids & b_ids)
    assert new_uuid()  # 助手 smoke（uuid 命名空间可用）
