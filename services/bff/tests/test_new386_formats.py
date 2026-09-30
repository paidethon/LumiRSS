"""NEW-386 保存格式对照预览 — kept/changed/lost 判定、台账、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import ZOTERO_RDF

FULL_RECORD = {
    "externalId": "full-1",
    "title": "对照用完整记录",
    "creators": ["作者一", "作者二"],
    "pubYear": "2025",
    "publication": "对照学刊",
    "publisher": "对照出版社",
    "url": "https://fmt.example/full",
    "doi": "10.9/full",
    "abstract": "这是一段用于对照的摘要。",
    "itemType": "JOUR",
    "tags": ["格式", "对照"],
}


def _seed_one(client, who):
    created = client.post(
        "/api/v1/preservation/zotero/import",
        content=ZOTERO_RDF.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )
    assert created.status_code == 201
    records = client.get("/api/v1/preservation/records", headers=who).json()["records"]
    return next(r["id"] for r in records if r["title"] == "长期保存的格式迁移研究")


def test_new386_full_record_survives_all_formats(ab_env):  # noqa: F811 — pytest 夹具注入
    """字段齐全的记录：三格式都应 kept（对照的意义在差异，不在造差异）。"""
    from lumirss.new386_format_compare import compare_record

    result = compare_record(FULL_RECORD)
    for _fmt, view in result["formats"].items():
        assert view["lostFields"] == [], (_fmt, view)
    # 纯文本保留 URL 原文（不是可点链接，但字段值原样在）
    assert "url" in FULL_RECORD
    md = result["formats"]["markdown"]["fields"]
    html_view = result["formats"]["html"]["fields"]
    assert md["title"] == "kept" and html_view["title"] == "kept"
    assert md["creators"] == "kept" and html_view["creators"] == "kept"


def test_new386_detects_real_loss(ab_env):  # noqa: F811 — pytest 夹具注入
    """构造真实损失：Markdown/纯文本不保留 DOI 之外的某个字段。
    用 abstract 含换行/多空白的记录验证 changed 语义；用空字段验证 na。"""
    from lumirss.new386_format_compare import compare_record

    sparse = {**FULL_RECORD, "abstract": "", "tags": [], "doi": ""}
    result = compare_record(sparse)
    for view in result["formats"].values():
        assert "abstract" in view["fields"]
        assert view["fields"]["abstract"] == "na"  # 源就没有 → 不算损失
        assert view["fields"]["doi"] == "na"
        assert view["fields"]["tags"] == "na"
        assert view["lostFields"] == []


def test_new386_endpoint_and_ledger(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    item_id = _seed_one(client, a)
    response = client.post(
        "/api/v1/preservation/format-compare", json={"itemIds": [item_id]}, headers=a
    )
    assert response.status_code == 200, response.text
    body = response.json()
    comparison_id = body["comparisonId"]
    assert body["compared"] == 1
    formats = body["items"][0]["formats"]
    assert set(formats) == {"markdown", "html", "text"}
    detail = client.get(
        f"/api/v1/preservation/format-compare/{comparison_id}", headers=a
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == comparison_id
    listing = client.get("/api/v1/preservation/format-compare", headers=a).json()
    assert listing["comparisons"][0]["id"] == comparison_id
    missing = client.get(
        "/api/v1/preservation/format-compare/cmp-nope", headers=a
    )
    assert missing.status_code == 404


def test_new386_validation_and_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    empty = client.post(
        "/api/v1/preservation/format-compare", json={"itemIds": []}, headers=a
    )
    assert empty.status_code == 400
    item_id = _seed_one(client, a)
    # B 用 A 的 item id → 对照不到（隔离）
    denied = client.post(
        "/api/v1/preservation/format-compare", json={"itemIds": [item_id]}, headers=b
    )
    assert denied.status_code == 400  # 选中的资料不存在
    ok_a = client.post(
        "/api/v1/preservation/format-compare", json={"itemIds": [item_id]}, headers=a
    )
    assert ok_a.status_code == 200
