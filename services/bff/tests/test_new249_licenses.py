"""NEW-249 资料引用许可证提示 — 记录 / 预览提示 / 未知诚实 / 隔离。

- 记录（user_record / source_explicit；license_text 空 = 明确未声明）
  → 提示预览逐条给 recorded / source_explicit / explicit_undeclared /
  unknown；未知明确标未知，不猜默认许可证；输出固定附免责声明；
- 校验：infoSource 非法 422（pydantic）；空 refs 422；
- 隔离：A 的许可证记录对 B 是 unknown（真实 RoutingDatabase per-user 库）。
"""

from new231_helpers import ab_session


def test_new249_record_and_notice_preview(client):
    """已记录 / 来源明示 / 明确未声明 / 无记录 四态 + 免责声明。"""
    put_user = client.put(
        "/api/v1/licenses/library:abc",
        json={"licenseText": "CC BY 4.0", "infoSource": "user_record", "note": "我在页脚看到的"},
    )
    assert put_user.status_code == 200, put_user.text

    put_explicit = client.put(
        "/api/v1/licenses/rss:e1.x",
        json={"licenseText": "All rights reserved", "infoSource": "source_explicit", "note": ""},
    )
    assert put_explicit.status_code == 200

    put_undeclared = client.put(
        "/api/v1/licenses/library:def",
        json={"licenseText": "", "infoSource": "source_explicit", "note": "页面没有声明"},
    )
    assert put_undeclared.status_code == 200

    preview = client.post(
        "/api/v1/licenses/notice-preview",
        json={"targetRefs": ["library:abc", "rss:e1.x", "library:def", "library:ghost"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    by_ref = {i["targetRef"]: i for i in body["items"]}
    assert by_ref["library:abc"]["status"] == "recorded"
    assert by_ref["library:abc"]["infoSource"] == "user_record"
    assert by_ref["rss:e1.x"]["status"] == "source_explicit"
    assert by_ref["library:def"]["status"] == "explicit_undeclared"
    assert by_ref["library:ghost"]["status"] == "unknown"
    assert by_ref["library:ghost"]["licenseText"] is None
    assert body["unknownCount"] == 2  # 明确未声明 + 无记录
    assert "不构成法律意见" in body["disclaimer"]

    # 单条查询：无记录 → unknown（不 404）
    single = client.get("/api/v1/licenses/library:ghost")
    assert single.status_code == 200
    assert single.json()["status"] == "unknown"

    # 撤销记录 → 回到 unknown
    removed = client.delete("/api/v1/licenses/library:abc")
    assert removed.status_code == 204
    after = client.get("/api/v1/licenses/library:abc").json()
    assert after["status"] == "unknown"


def test_new249_validation(client):
    bad_source = client.put(
        "/api/v1/licenses/library:x", json={"licenseText": "CC0", "infoSource": "guessed"}
    )
    assert bad_source.status_code == 422

    empty_refs = client.post("/api/v1/licenses/notice-preview", json={"targetRefs": []})
    assert empty_refs.status_code == 422

    too_long = client.put(
        "/api/v1/licenses/library:x",
        json={"licenseText": "字" * 501, "infoSource": "user_record"},
    )
    assert too_long.status_code == 422


def test_new249_isolation_between_users(monkeypatch, tmp_path):
    """A 的许可证记录对 B 是 unknown（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        put = session.client.put(
            "/api/v1/licenses/library:iso",
            json={"licenseText": "CC BY-SA 4.0", "infoSource": "user_record"},
            headers=session.owner,
        )
        assert put.status_code == 200, put.text

        b_view = session.client.get("/api/v1/licenses/library:iso", headers=member)
        assert b_view.status_code == 200
        assert b_view.json()["status"] == "unknown"

        b_preview = session.client.post(
            "/api/v1/licenses/notice-preview",
            json={"targetRefs": ["library:iso"]},
            headers=member,
        )
        assert b_preview.json()["items"][0]["status"] == "unknown"
        assert b_preview.json()["unknownCount"] == 1
