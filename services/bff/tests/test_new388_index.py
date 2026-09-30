"""NEW-388 个人索引导出 — 字段白名单（不附全文）、校验值稳定、A/B 隔离。"""

import json

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import RIS_SAMPLE, ZOTERO_RDF


def _seed(client, who):
    created = client.post(
        "/api/v1/preservation/zotero/import",
        content=ZOTERO_RDF.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )
    assert created.status_code == 201
    created = client.post(
        "/api/v1/preservation/ris/import",
        content=RIS_SAMPLE.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )
    assert created.status_code == 201


def test_new388_catalog_excludes_fulltext(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    _seed(client, a)
    response = client.get("/api/v1/preservation/index-export", headers=a)
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert catalog["recordCount"] == 4
    blob = json.dumps(catalog, ensure_ascii=False)
    # 不附全文：已知摘要文本不出现；记录条目里没有 abstract 键
    # （"abstract" 只允许出现在 excluded 声明里）
    assert "讨论书目记录的长期保存" not in blob
    for record in catalog["records"]:
        assert "abstract" not in record
    assert "excluded" in catalog and "abstract" in catalog["excluded"]
    # 目录字段：externalId / 标签 / 来源 / 校验值
    entry = next(
        record
        for record in catalog["records"]
        if record["externalId"] == "ABCD1234"
    )
    assert entry["title"] == "长期保存的格式迁移研究"
    assert "陈, 静" in entry["creators"]
    assert "数字保存" in entry["tags"]
    assert entry["publication"] == "档案学刊"
    assert len(entry["sha256"]) == 64
    # 聚合标签与来源
    assert "数字保存" in catalog["tags"]
    assert "档案学刊" in catalog["sources"]


def test_new388_checksums_stable_and_ledger(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    _seed(client, a)
    first = client.get("/api/v1/preservation/index-export", headers=a).json()
    second = client.get("/api/v1/preservation/index-export", headers=a).json()
    assert first["catalogSha256"] == second["catalogSha256"]
    # 新增一条（全新 externalId + 全新标题）→ 整体校验值变化
    client.post(
        "/api/v1/preservation/zotero/import",
        content=ZOTERO_RDF.replace(
            "ABCD1234", "ZZZZ9999"
        ).replace("长期保存的格式迁移研究", "追加的一条新记录").encode("utf-8"),
        headers={**a, "content-type": "application/octet-stream"},
    )
    third = client.get("/api/v1/preservation/index-export", headers=a).json()
    assert third["catalogSha256"] != first["catalogSha256"]
    exports = client.get("/api/v1/preservation/index-export/exports", headers=a).json()
    assert len(exports["exports"]) == 3
    assert third["catalogSha256"] in {
        entry["catalogSha256"] for entry in exports["exports"]
    }


def test_new388_download_and_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    _seed(client, a)
    download = client.get(
        "/api/v1/preservation/index-export", params={"download": "true"}, headers=a
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    catalog = download.json()
    assert catalog["recordCount"] == 4
    # B 的目录为空（A 的资料对 B 不可见）
    b_catalog = client.get("/api/v1/preservation/index-export", headers=b).json()
    assert b_catalog["recordCount"] == 0
    assert b_catalog["records"] == []
