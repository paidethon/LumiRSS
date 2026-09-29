"""NEW-235 笔记模板填空 — 模板 CRUD / 结构化填充 / 自由文本保留 / 隔离。

- 模板字段校验（key 词表、label 必填、1..20 个、key 唯一）；
- 填充不改写 content_md（自由文本区保留）；未知字段 422；缺失补空串；
- 删模板后已填充的 values 保留（fields 归空，诚实不伪造字段定义）。
"""

from new231_helpers import ab_session

_FIELDS = [
    {"key": "source_type", "label": "来源类型"},
    {"key": "key_claim", "label": "核心论断"},
    {"key": "to_verify", "label": "待核实"},
]


def _create_note(client, title: str = "阅读记录", content: str = "自由文本正文，不会被模板改写。\n") -> dict:
    response = client.post("/api/v1/library/notes", json={"title": title, "contentMd": content})
    assert response.status_code == 201, response.text
    return response.json()


def test_new235_template_crud_and_fill(client):
    """建模板 → 填充笔记 → 正文不变 → 回读填充 → 校验分支。"""
    created = client.post(
        "/api/v1/note-templates", json={"name": "阅读记录模板", "fields": _FIELDS}
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert [f["key"] for f in template["fields"]] == ["source_type", "key_claim", "to_verify"]

    # 校验：空名 / 重复 key / 非法 key / 空 fields
    assert (
        client.post("/api/v1/note-templates", json={"name": " ", "fields": _FIELDS}).status_code
        == 422
    )
    dup = client.post(
        "/api/v1/note-templates",
        json={
            "name": "重复",
            "fields": [
                {"key": "a", "label": "甲"},
                {"key": "a", "label": "乙"},
            ],
        },
    )
    assert dup.status_code == 422
    assert (
        client.post(
            "/api/v1/note-templates",
            json={"name": "非法", "fields": [{"key": "Bad-Key", "label": "甲"}]},
        ).status_code
        == 422
    )
    assert (
        client.post("/api/v1/note-templates", json={"name": "空", "fields": []}).status_code
        == 422
    )

    note = _create_note(client)
    fill = client.put(
        f"/api/v1/library/notes/{note['uuid']}/template-fill",
        json={
            "templateId": template["id"],
            "values": {"source_type": "期刊", "key_claim": "注意密度随温度变化"},
        },
    )
    assert fill.status_code == 200, fill.text
    body = fill.json()
    assert body["values"]["to_verify"] == ""  # 缺失补空串（诚实）
    assert body["values"]["source_type"] == "期刊"

    # 正文未被改写（自由文本区保留）
    detail = client.get(f"/api/v1/library/notes/{note['uuid']}")
    assert detail.status_code == 200
    assert detail.json()["contentMd"] == note["contentMd"]

    # 回读
    readback = client.get(f"/api/v1/library/notes/{note['uuid']}/template-fill")
    assert readback.status_code == 200
    assert readback.json()["templateId"] == template["id"]
    assert readback.json()["values"]["key_claim"] == "注意密度随温度变化"

    # 未知字段 → 422；未知模板/笔记 → 404
    bad = client.put(
        f"/api/v1/library/notes/{note['uuid']}/template-fill",
        json={"templateId": template["id"], "values": {"nope": "x"}},
    )
    assert bad.status_code == 422
    assert (
        client.put(
            f"/api/v1/library/notes/{note['uuid']}/template-fill",
            json={"templateId": "no-such", "values": {}},
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/library/notes/no-such/template-fill").status_code == 404
    )

    # 删模板 → 已填充 values 保留，fields 归空（诚实）
    assert client.delete(f"/api/v1/note-templates/{template['id']}").status_code == 204
    after = client.get(f"/api/v1/library/notes/{note['uuid']}/template-fill").json()
    assert after["fields"] == []
    assert after["values"]["source_type"] == "期刊"
    assert client.delete(f"/api/v1/note-templates/{template['id']}").status_code == 404


def test_new235_cross_user_templates_isolated(monkeypatch, tmp_path):
    """A 的模板与填充对 B 不可见（per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        template = session.client.post(
            "/api/v1/note-templates",
            json={"name": "A 的模板", "fields": [{"key": "a", "label": "甲"}]},
            headers=session.owner,
        )
        assert template.status_code == 201
        note = session.client.post(
            "/api/v1/library/notes",
            json={"title": "A 的笔记", "contentMd": "A 的正文\n"},
            headers=session.owner,
        ).json()

        member = session.activate_member("n235b")
        assert (
            session.client.get(
                f"/api/v1/library/notes/{note['uuid']}/template-fill", headers=member
            ).status_code
            == 404
        )
        assert (
            session.client.put(
                f"/api/v1/library/notes/{note['uuid']}/template-fill",
                json={"templateId": template.json()["id"], "values": {}},
                headers=member,
            ).status_code
            == 404
        )
        # B 的模板列表为空（模板定义也是 per-user）
        assert (
            session.client.get("/api/v1/note-templates", headers=member).json()["items"]
            == []
        )
