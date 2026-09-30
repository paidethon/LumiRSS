"""NEW-389 分卷导出 — 按容量切卷、逐卷清单、缺卷拒绝、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import ZOTERO_RDF


def _seed(client, who, count=6):
    """每次只导第一条条目（截掉 fixture 的第二条），count 次 → count 条。"""
    for index in range(count):
        rdf = ZOTERO_RDF.replace("ABCD1234", f"VOL{index:04d}").replace(
            "长期保存的格式迁移研究",
            f"分卷测试记录 {index:03d} " + "x" * 400,  # 每条约 1KB（解析端有 500 截断）
        )
        rdf = (
            rdf.split('<z:item rdf:about="http://www.zotero.org/zotero/items/EFGH5678">')[0]
            + "</rdf:RDF>"
        )
        created = client.post(
            "/api/v1/preservation/zotero/import",
            content=rdf.encode("utf-8"),
            headers={**who, "content-type": "application/octet-stream"},
        )
        assert created.status_code == 201, created.text
    return [
        record["id"]
        for record in client.get("/api/v1/preservation/records", headers=who).json()[
            "records"
        ]
    ]


def test_new389_export_splits_by_capacity(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    ids = _seed(client, a, count=12)
    response = client.post(
        "/api/v1/preservation/volumes/export",
        json={"itemIds": ids, "maxVolumeBytes": 8192},
        headers=a,
    )
    assert response.status_code == 200, response.text
    split = response.json()
    manifest = split["setManifest"]
    assert manifest["itemCount"] == 12
    assert len(split["volumes"]) >= 2  # 8KiB 装不下 12 条
    assert [v["index"] for v in split["volumes"]] == list(
        range(1, len(split["volumes"]) + 1)
    )
    assert all(v["of"] == len(split["volumes"]) for v in split["volumes"])
    all_ids = [item["id"] for volume in split["volumes"] for item in volume["items"]]
    assert sorted(all_ids) == sorted(manifest["itemIds"])
    sets = client.get("/api/v1/preservation/volumes/sets", headers=a).json()
    assert sets["sets"][0]["setId"] == manifest["setId"]


def test_new389_check_reports_missing_volumes(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    ids = _seed(client, a, count=12)
    split = client.post(
        "/api/v1/preservation/volumes/export",
        json={"itemIds": ids, "maxVolumeBytes": 8192},
        headers=a,
    ).json()
    volumes = split["volumes"]
    assert len(volumes) >= 2
    # 完整卷集 → check complete
    full = client.post(
        "/api/v1/preservation/volumes/check",
        json={"setManifest": split["setManifest"], "volumes": volumes},
        headers=a,
    ).json()
    assert full["complete"] is True
    assert full["missingVolumes"] == [] and full["missingItems"] == []
    # 丢一卷 → check 如实报告缺卷 + 缺条目
    partial = client.post(
        "/api/v1/preservation/volumes/check",
        json={"setManifest": split["setManifest"], "volumes": volumes[1:]},
        headers=a,
    ).json()
    assert partial["complete"] is False
    assert partial["missingVolumes"] == [1]
    assert len(partial["missingItems"]) == len(volumes[0]["items"])


def test_new389_import_refuses_incomplete_and_imports_complete(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    ids = _seed(client, a, count=12)
    # 先清掉已导入的记录，模拟「迁移到新库」场景：用另一成员 B 导出再
    # 导回 A？——直接用 B 的空库做导入目标，导出面用 A。
    split = client.post(
        "/api/v1/preservation/volumes/export",
        json={"itemIds": ids, "maxVolumeBytes": 8192},
        headers=a,
    ).json()
    volumes = split["volumes"]
    # 缺卷导入 → 409，绝不默默少导
    refused = client.post(
        "/api/v1/preservation/volumes/import",
        json={"setManifest": split["setManifest"], "volumes": volumes[1:]},
        headers=a,
    )
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["type"] == "volume_set_incomplete"
    assert error["missingVolumes"] == [1]
    # 缺卷导入后库里一条都没多（先清空再验证更严格：A 库本来就有这批）
    imports = client.get("/api/v1/preservation/volumes/imports", headers=a).json()
    assert imports["imports"][0]["status"] == "incomplete"
    # 完整卷集导入（A 的记录已存在 → 全部 matched）
    done = client.post(
        "/api/v1/preservation/volumes/import",
        json={"setManifest": split["setManifest"], "volumes": volumes},
        headers=a,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["added"] == 0 and body["matched"] == 12
    assert body["reconciliationId"]
    recon = client.get(
        f"/api/v1/preservation/reconciliations/{body['reconciliationId']}", headers=a
    )
    assert recon.status_code == 200
    assert recon.json()["source"] == f"volume:{split['setManifest']['setId']}"
    imports = client.get("/api/v1/preservation/volumes/imports", headers=a).json()
    imported_row = next(
        row for row in imports["imports"] if row["status"] == "imported"
    )
    assert imported_row["reconciliationId"] == body["reconciliationId"]


def test_new389_fresh_target_import_and_validation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    ids = _seed(client, a, count=5)
    split = client.post(
        "/api/v1/preservation/volumes/export",
        json={"itemIds": ids, "maxVolumeBytes": 8192},
        headers=a,
    ).json()
    # B 的空库：完整导入 → 全部 added + 对账单
    done = client.post(
        "/api/v1/preservation/volumes/import",
        json={"setManifest": split["setManifest"], "volumes": split["volumes"]},
        headers=b,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["added"] == 5 and body["matched"] == 0
    counts = body["reconciliation"]["counts"]
    assert counts["added"] == 5 and counts["missing"] == 0
    # 校验：非法上限 / 无资料成员的空集 → 400
    bad = client.post(
        "/api/v1/preservation/volumes/export",
        json={"itemIds": ids, "maxVolumeBytes": 10},
        headers=a,
    )
    assert bad.status_code == 400
    empty = client.post(
        "/api/v1/preservation/volumes/export",
        json={"itemIds": [], "maxVolumeBytes": 65536},
        headers=ab_env["owner"],  # owner 库没有任何资料
    )
    assert empty.status_code == 400
