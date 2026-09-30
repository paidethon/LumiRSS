"""NEW-385 WARC 索引导入 — 资源索引字段、正文可选与活动内容拦截、
体积上限、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import sample_warc, warc_record


def _post_warc(client, who, path, raw, import_bodies=None):
    params = {"importBodies": "true"} if import_bodies else None
    return client.post(
        path,
        params=params,
        content=raw,
        headers={**who, "content-type": "application/octet-stream"},
    )


def test_new385_index_fields_preserved(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    response = _post_warc(client, a, "/api/v1/preservation/warc/preview", sample_warc())
    assert response.status_code == 200, response.text
    parsed = response.json()
    # 3 条可索引 response 记录；metadata 记录跳过计数
    assert len(parsed["records"]) == 3
    assert parsed["skipped"] == 1
    first = parsed["records"][0]
    assert first["targetUri"] == "https://archive.example/page-1"
    assert first["recordId"] == "<urn:uuid:11111111-1111-4111-8111-111111111111>"
    assert first["payloadDigest"] == "sha1:AAAA1111"
    assert first["httpStatus"].startswith("HTTP/1.1 200")
    assert first["activeContent"] is True  # text/html → 活动内容标记
    assert first["bodyText"] == ""  # 预览默认不导正文
    # 写入 + 台账
    imported = _post_warc(client, a, "/api/v1/preservation/warc/import", sample_warc())
    assert imported.status_code == 201, imported.text
    body = imported.json()
    assert body["imported"] == 3
    batches = client.get("/api/v1/preservation/warc/batches", headers=a).json()
    assert batches["batches"][0]["activeContent"] == 2  # 两条 html
    records = client.get(
        "/api/v1/preservation/warc/records",
        params={"batchId": body["batchId"]},
        headers=a,
    ).json()["records"]
    assert len(records) == 3
    assert all(record["bodyText"] == "" for record in records)


def test_new385_optional_text_body_imported_html_blocked(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    response = _post_warc(
        client, a, "/api/v1/preservation/warc/import", sample_warc(), import_bodies=True
    )
    assert response.status_code == 201, response.text
    assert response.json()["bodyImported"] == 1  # 只有 text/plain 一条
    listing = client.get("/api/v1/preservation/warc/records", headers=a).json()
    by_uri = {r["targetUri"]: r for r in listing["records"]}
    # text/plain 正文按用户选择导入（原样）
    assert "纯文本正文" in by_uri["https://archive.example/notes.txt"]["bodyText"]
    # HTML 即使显式要求也不落正文（活动内容拦截，FIX-328 模式）
    assert by_uri["https://archive.example/page-1"]["bodyText"] == ""
    assert by_uri["https://archive.example/active.html"]["bodyText"] == ""
    assert by_uri["https://archive.example/active.html"]["activeContent"] is True


def test_new385_oversized_record_index_only(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    big_payload = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n" + b"A" * 600_000
    )
    raw = warc_record(
        {
            "WARC-Type": "response",
            "WARC-Target-URI": "https://archive.example/big",
            "Content-Type": "application/http; msgtype=response",
        },
        big_payload,
    )
    response = _post_warc(
        client, a, "/api/v1/preservation/warc/import", raw, import_bodies=True
    )
    assert response.status_code == 201
    body = response.json()
    assert body["oversized"] == 1
    listing = client.get("/api/v1/preservation/warc/records", headers=a).json()
    big = listing["records"][0]
    # 超限记录：声明长度如实入索引，但正文绝不落库
    assert big["contentLength"] >= 600_000
    assert big["bodyText"] == ""


def test_new385_hostile_input(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    garbage = _post_warc(client, a, "/api/v1/preservation/warc/preview", b"not a warc")
    assert garbage.status_code == 400
    truncated = _post_warc(
        client, a, "/api/v1/preservation/warc/preview", b"WARC/1.0\r\nBroken"
    )
    assert truncated.status_code == 400


def test_new385_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    _post_warc(client, a, "/api/v1/preservation/warc/import", sample_warc())
    assert client.get("/api/v1/preservation/warc/records", headers=b).json()[
        "records"
    ] == []
    assert client.get("/api/v1/preservation/warc/batches", headers=b).json()[
        "batches"
    ] == []
    # B 自己导入，索引互不可见
    _post_warc(client, b, "/api/v1/preservation/warc/import", sample_warc())
    a_records = client.get("/api/v1/preservation/warc/records", headers=a).json()
    b_records = client.get("/api/v1/preservation/warc/records", headers=b).json()
    a_ids = {r["id"] for r in a_records["records"]}
    b_ids = {r["id"] for r in b_records["records"]}
    assert a_ids and b_ids and not (a_ids & b_ids)
