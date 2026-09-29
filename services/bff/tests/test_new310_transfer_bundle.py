"""NEW-310 接入配置转移包 — 无秘密导出/凭据引用重选（生成新钥或合并
进既有来源）/缺选择如实跳过/防重复导入 + A/B 隔离。"""

import asyncio
import copy
import json

from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _run(coroutine):
    return asyncio.run(coroutine)


def _make_source(client, name, path):
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": name,
            "endpoint": "https://api.example.com/" + path,
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_new310_export_is_secret_free(client):
    made = _make_source(client, "T310 源一", "t310a")
    exported = client.get("/api/v1/api-sources/transfer-bundle")
    assert exported.status_code == 200, exported.text
    bundle = exported.json()
    assert bundle["kind"] == "lumirss-api-intake"
    assert bundle["version"] == 1
    flat = json.dumps(bundle)
    assert made["secret"] not in flat  # 明文凭据绝不入包
    assert "atomPath" not in flat and "etag" not in flat
    entry = bundle["sources"][0]
    assert set(entry) == {
        "credentialRef",
        "name",
        "endpoint",
        "itemsExpr",
        "fieldMap",
        "pagination",
        "maxRunsPerHour",
    }
    assert entry["credentialRef"] == "apisource:" + made["uuid"]


def test_new310_import_generate_merge_skip_and_deduupe(client):
    original = _make_source(client, "T310 原生", "t10b")
    bundle = client.get("/api/v1/api-sources/transfer-bundle").json()
    ref = bundle["sources"][0]["credentialRef"]

    # 1) generate：新建来源并铸造新凭据；响应无任何秘密
    first = client.post(
        "/api/v1/api-sources/transfer-bundle/import",
        json={"bundle": bundle, "credentials": {ref: "generate"}},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["created"]) == 1 and not body["merged"] and not body["skipped"]
    new_uuid = body["created"][0]["uuid"]
    assert new_uuid != original["uuid"]
    assert "secret" not in first.text and "atomPath" not in first.text
    assert "请通过该来源的凭据入口" in body["created"][0]["credentialNote"]

    # 2) 合并：credentialRef 指向既有来源 → 更新其配置、保留其凭据
    bundle_two = copy.deepcopy(bundle)
    bundle_two["sources"][0]["name"] = "T310 原生（转移版）"
    second = client.post(
        "/api/v1/api-sources/transfer-bundle/import",
        json={
            "bundle": bundle_two,
            "credentials": {ref: original["uuid"]},
        },
    )
    assert second.status_code == 200, second.text
    assert [m["uuid"] for m in second.json()["merged"]] == [original["uuid"]]
    listing = client.get("/api/v1/api-sources").json()["items"]
    by_uuid = {s["uuid"]: s for s in listing}
    assert by_uuid[original["uuid"]]["name"] == "T310 原生（转移版）"
    assert by_uuid[new_uuid]["name"] == "T310 原生"  # generate 出的兄弟不受影响

    # 3) 未选择凭据引用 → 跳过并如实报告
    bundle_three = copy.deepcopy(bundle)
    bundle_three["sources"][0]["name"] = "T310 无选择"
    third = client.post(
        "/api/v1/api-sources/transfer-bundle/import",
        json={"bundle": bundle_three, "credentials": {}},
    )
    assert third.status_code == 200, third.text
    skipped = third.json()["skipped"]
    assert len(skipped) == 1 and "未选择凭据引用" in skipped[0]["reason"]

    # 4) 同一包二次导入 → 409 already_imported（防重复导入）
    repeat = client.post(
        "/api/v1/api-sources/transfer-bundle/import",
        json={"bundle": bundle_three, "credentials": {}},
    )
    assert repeat.status_code == 409
    assert repeat.json()["error"]["type"] == "already_imported"

    bad = client.post(
        "/api/v1/api-sources/transfer-bundle/import",
        json={"bundle": {"kind": "other"}, "credentials": {}},
    )
    assert bad.status_code == 422


def test_new310_cross_user_transfer_isolated(ab_env):  # noqa: F811 — pytest 夹具注册
    """B 的导出不含 A 的来源；B 的清单里看不到 A 导入出的新来源。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]
    created = client.post(
        "/api/v1/api-sources",
        headers=a,
        json={
            "name": "A 的转移源",
            "endpoint": "https://api.example.com/ta",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "t"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text

    export_a = client.get(
        "/api/v1/api-sources/transfer-bundle", headers=a
    ).json()
    assert len(export_a["sources"]) == 1
    export_b = client.get(
        "/api/v1/api-sources/transfer-bundle", headers=b
    ).json()
    assert export_b["sources"] == []

    imported = client.post(
        "/api/v1/api-sources/transfer-bundle/import",
        headers=a,
        json={
            "bundle": export_a,
            "credentials": {export_a["sources"][0]["credentialRef"]: "generate"},
        },
    )
    assert imported.status_code == 200, imported.text
    new_uuid = imported.json()["created"][0]["uuid"]
    assert (
        client.get(f"/api/v1/api-sources/{new_uuid}/mapping-samples", headers=b).status_code
        == 404
    )
    b_list = client.get("/api/v1/api-sources", headers=b).json()["items"]
    assert all(s["uuid"] != new_uuid for s in b_list)
