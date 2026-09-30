"""NEW-382 RIS 导入与导出 — 往返校验、不支持字段报告、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import RIS_SAMPLE


def _post(client, who, path, text, **params):
    return client.post(
        path,
        params=params or None,
        content=text.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )


def test_new382_preview_reports_unsupported_tags(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    response = _post(client, a, "/api/v1/preservation/ris/preview", RIS_SAMPLE)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["format"] == "ris"
    assert preview["total"] == 2
    first = preview["items"][0]
    # 原始引用标识：AN tag 原样保留
    assert first["externalId"] == "ris-key-001"
    assert first["title"] == "引文往返校验初探"
    assert first["creators"] == ["王五", "赵六"]
    assert first["publication"] == "情报学报"
    assert "RIS" in first["tags"]
    # 不支持字段（CN/SN）如实报告，不假装映射
    assert sorted(first["unsupportedFields"]) == ["CN", "SN"]
    assert sorted(preview["unsupportedFields"]) == ["CN", "SN"]
    assert preview["duplicates"] == 0


def test_new382_import_export_roundtrip_ok(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    imported = _post(client, a, "/api/v1/preservation/ris/import", RIS_SAMPLE).json()
    assert imported["imported"] == 2
    listing = client.get("/api/v1/preservation/records?format=ris", headers=a).json()
    record_ids = [record["id"] for record in listing["records"]]
    exported = client.get(
        "/api/v1/preservation/ris/export",
        params={"ids": record_ids},
        headers=a,
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["x-lumi-roundtrip"] == "ok"
    assert exported.headers["content-type"].startswith("application/x-research-info-systems")
    text = exported.text
    assert "TY  - JOUR" in text and "ER  -" in text
    # 往返台账可查，结论 ok
    exports = client.get("/api/v1/preservation/ris/exports", headers=a).json()
    assert exports["exports"][0]["roundtripOk"] is True
    assert exports["exports"][0]["recordCount"] == 2


def test_new382_roundtrip_detects_tampering(ab_env):  # noqa: F811 — pytest 夹具注入
    """导出文本被改 → 往返校验如实报 diffs（不是永远 ok）。"""
    from lumirss.new382_ris import roundtrip_report, serialize_ris

    records = [
        {
            "externalId": "x1",
            "title": "标题甲",
            "creators": ["作者"],
            "pubYear": "2024",
            "publication": "刊物",
            "publisher": "出版社",
            "url": "https://e.example/x",
            "doi": "10.1/x",
            "abstract": "摘要内容",
            "itemType": "JOUR",
            "tags": ["t1"],
        }
    ]
    exported = serialize_ris(records)
    assert roundtrip_report(records, exported)["roundtripOk"] is True
    tampered = exported.replace("标题甲", "标题乙")
    report = roundtrip_report(records, tampered)
    assert report["roundtripOk"] is False
    assert any("title" in entry["changed"] for entry in report["records"])


def test_new382_hostile_input(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    empty = _post(client, a, "/api/v1/preservation/ris/preview", "没有 RIS 标记的文本")
    assert empty.status_code == 400


def test_new382_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    _post(client, a, "/api/v1/preservation/ris/import", RIS_SAMPLE)
    # B 看不到 A 的 RIS 记录；导出为空 → 400 nothing_to_export
    b_records = client.get("/api/v1/preservation/records?format=ris", headers=b)
    assert b_records.json()["records"] == []
    b_export = client.get("/api/v1/preservation/ris/export", headers=b)
    assert b_export.status_code == 400
    assert b_export.json()["error"]["type"] == "nothing_to_export"
    # B 自己导入后，台账互不可见
    _post(client, b, "/api/v1/preservation/ris/import", RIS_SAMPLE)
    b_exports = client.get("/api/v1/preservation/ris/exports", headers=b).json()
    assert b_exports["exports"] == []
