"""NEW-327 笔记属性列映射 — frontmatter → 可见列/筛选，原文件不变。"""


from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new321_vault import write_vault


def _setup(client, owner, tmp_path):
    vault = write_vault(
        tmp_path,
        {
            "a.md": "---\ntitle: A\nstatus: draft\nrating: 4\n---\nA\n",
            "b.md": "---\ntitle: B\nstatus: published\n---\nB\n",
            "c.md": "---\ntitle: C\nstatus: draft\n---\nC\n",
        },
    )
    created = client.put(
        "/api/v1/obsidian/settings", json={"vaultPath": str(vault)}, headers=owner
    )
    assert created.status_code == 200, created.text
    assert (
        client.post("/api/v1/obsidian/rescan", headers=owner).status_code == 200
    )
    return vault


def test_new327_available_fields_and_column_mapping(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    vault = _setup(client, owner, tmp_path)

    listing = client.get("/api/v1/obsidian/property-columns", headers=owner).json()
    fields = {f["field"]: f["noteCount"] for f in listing["fields"]}
    assert fields["status"] == 3 and fields["rating"] == 1
    assert listing["columns"] == []  # 未配置前列表为空（不自动发明列）

    put = client.put(
        "/api/v1/obsidian/property-columns",
        json={"field": "status", "label": "状态", "visible": True, "filterable": True, "position": 1},
        headers=owner,
    )
    assert put.status_code == 200, put.text
    put2 = client.put(
        "/api/v1/obsidian/property-columns",
        json={"field": "rating", "label": "评分", "position": 2},
        headers=owner,
    )
    assert put2.status_code == 200
    columns = client.get("/api/v1/obsidian/property-columns", headers=owner).json()["columns"]
    assert [c["field"] for c in columns] == ["status", "rating"]
    assert columns[0]["filterable"] is True and columns[1]["filterable"] is False

    # 校验：空字段 / 坏 position → 400
    assert (
        client.put(
            "/api/v1/obsidian/property-columns", json={"field": ""}, headers=owner
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/v1/obsidian/property-columns",
            json={"field": "x", "position": "high"},
            headers=owner,
        ).status_code
        == 400
    )
    deleted = client.delete(
        "/api/v1/obsidian/property-columns?field=rating", headers=owner
    )
    assert deleted.status_code == 200

    # 原文件格式保持不变（绝不回写 frontmatter）
    assert (vault / "a.md").read_text(encoding="utf-8").startswith(
        "---\ntitle: A\nstatus: draft\nrating: 4\n---"
    )


def test_new327_filter_notes_by_property_value(ab_env, tmp_path):  # noqa: F811
    client, owner = ab_env["client"], ab_env["owner"]
    _setup(client, owner, tmp_path)
    result = client.get(
        "/api/v1/obsidian/property-columns/notes?field=status&value=draft",
        headers=owner,
    ).json()
    titles = {n["title"] for n in result["notes"]}
    assert titles == {"A", "C"}
    note_a = next(n for n in result["notes"] if n["title"] == "A")
    assert note_a["properties"]["rating"] == "4"  # 属性随行可见
    published = client.get(
        "/api/v1/obsidian/property-columns/notes?field=status&value=published",
        headers=owner,
    ).json()
    assert {n["title"] for n in published["notes"]} == {"B"}
    # 无命中 → 空列表（诚实），非错误
    none = client.get(
        "/api/v1/obsidian/property-columns/notes?field=status&value=archived",
        headers=owner,
    ).json()
    assert none["notes"] == []
    # 缺 field → 400
    assert (
        client.get(
            "/api/v1/obsidian/property-columns/notes", headers=owner
        ).status_code
        == 400
    )


def test_new327_per_user_isolation_between_accounts(ab_env, tmp_path):  # noqa: F811
    client, owner, b = ab_env["client"], ab_env["owner"], ab_env["b"]
    _setup(client, owner, tmp_path)
    assert (
        client.put(
            "/api/v1/obsidian/property-columns",
            json={"field": "status", "label": "状态"},
            headers=owner,
        ).status_code
        == 200
    )
    for method, path, kwargs in (
        ("get", "/api/v1/obsidian/property-columns", {}),
        (
            "put",
            "/api/v1/obsidian/property-columns",
            {"json": {"field": "rating", "label": "评分"}},
        ),
        (
            "get",
            "/api/v1/obsidian/property-columns/notes?field=status&value=draft",
            {},
        ),
    ):
        response = getattr(client, method)(path, headers=b, **kwargs)
        assert response.status_code == 403, (method, path, response.text)
    columns = client.get(
        "/api/v1/obsidian/property-columns", headers=owner
    ).json()["columns"]
    assert [c["field"] for c in columns] == ["status"]
