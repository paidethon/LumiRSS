"""NEW-245 引文出处补全 — 登记 / 原始值与补充值分离 / 隔离。

- 登记（author/date 可以是 NULL=原始缺失）；重复登记 409（原始值
  不被覆盖）；补全 author/date → 生效值 + origin=supplement；原始值
  永远分开展示；撤销补充恢复缺失态；
- 校验：field 非法 422；未登记的 ref 补充 404；
- 隔离：A 登记的引文对 B 是 404（真实 RoutingDatabase per-user 库）。
"""

from new231_helpers import ab_session


def test_new245_register_supplement_and_revert(client):
    """原始缺失 → 补充 → 生效值是补充值且 origin 标明；撤销 → 回到缺失。"""
    created = client.post(
        "/api/v1/citations",
        json={"citationRef": "c-001", "title": "无署名转载文", "author": None, "dateValue": None},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["author"] is None

    view = client.get("/api/v1/citations/c-001")
    assert view.status_code == 200
    fields = view.json()
    assert fields["author"] == {"original": None, "supplement": None, "effective": None, "origin": None}

    # 逐项补充 author
    supp = client.put(
        "/api/v1/citations/c-001/supplements/author", json={"value": "王小波"}
    )
    assert supp.status_code == 200, supp.text
    after = client.get("/api/v1/citations/c-001").json()
    assert after["author"]["original"] is None  # 原始值保持缺失
    assert after["author"]["supplement"] == "王小波"
    assert after["author"]["effective"] == "王小波"
    assert after["author"]["origin"] == "supplement"

    # 原始值优先于补充值：原始 author 存在时生效值 = 原始
    client.post(
        "/api/v1/citations",
        json={"citationRef": "c-002", "title": "有署名的文", "author": "李银河", "dateValue": None},
    )
    client.put("/api/v1/citations/c-002/supplements/author", json={"value": "别人"})
    mixed = client.get("/api/v1/citations/c-002").json()
    assert mixed["author"]["original"] == "李银河"
    assert mixed["author"]["effective"] == "李银河"
    assert mixed["author"]["origin"] == "original"

    # 撤销补充 → c-001 回到缺失态
    removed = client.delete("/api/v1/citations/c-001/supplements/author")
    assert removed.status_code == 204
    reverted = client.get("/api/v1/citations/c-001").json()
    assert reverted["author"]["supplement"] is None
    assert reverted["author"]["effective"] is None

    # 列表里两条都在
    listed = client.get("/api/v1/citations").json()
    assert {i["citationRef"] for i in listed["items"]} == {"c-001", "c-002"}


def test_new245_validation_and_conflict(client):
    """重复登记 409；field 非法 422；未登记补充 404。"""
    payload = {"citationRef": "c-dup", "title": "标题", "author": None, "dateValue": None}
    first = client.post("/api/v1/citations", json=payload)
    assert first.status_code == 201

    # 原始值不被覆盖：重复登记带不同 author → 409
    dup = client.post(
        "/api/v1/citations", json={"citationRef": "c-dup", "title": "另一标题", "author": "某人"}
    )
    assert dup.status_code == 409
    assert dup.json()["error"]["type"] == "citation_conflict"
    kept = client.get("/api/v1/citations/c-dup").json()
    assert kept["title"] == "标题"
    assert kept["author"]["original"] is None

    bad_field = client.put("/api/v1/citations/c-dup/supplements/year", json={"value": "2026"})
    assert bad_field.status_code == 422

    missing = client.put("/api/v1/citations/c-ghost/supplements/author", json={"value": "某人"})
    assert missing.status_code == 404

    empty_value = client.put("/api/v1/citations/c-dup/supplements/author", json={"value": " "})
    assert empty_value.status_code == 422


def test_new245_isolation_between_users(monkeypatch, tmp_path):
    """A 登记的引文对 B 是 404（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        created = session.client.post(
            "/api/v1/citations",
            json={"citationRef": "iso-1", "title": "A 的引文"},
            headers=session.owner,
        )
        assert created.status_code == 201, created.text

        b_view = session.client.get("/api/v1/citations/iso-1", headers=member)
        assert b_view.status_code == 404

        b_list = session.client.get("/api/v1/citations", headers=member)
        assert b_list.json()["items"] == []

        a_view = session.client.get("/api/v1/citations/iso-1", headers=session.owner)
        assert a_view.status_code == 200
