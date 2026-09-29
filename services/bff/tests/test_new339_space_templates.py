"""NEW-339 共读模板 —— 模板不含成员与内容（测试断言）；预览零写入；应用落地。"""

from new231_helpers import ab_session
from new331_helpers import space_with_members


def test_template_from_space_excludes_members_and_content(monkeypatch, tmp_path):
    """管理者从空间生成模板：栏目（名称/顺序）+ 角色规则 + 显式讨论模板；
    响应中绝无成员清单与任何文章/讨论内容；重名 409；成员越权 403。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n339b", name="模板源空间", requireApproval=True)
        sid = space["id"]
        member = session.login("n339b")

        for name in ("精读", "速览"):
            section = session.client.post(
                f"/api/v1/spaces/{sid}/sections", json={"name": name}, headers=session.owner
            )
            assert section.status_code == 201
        # 源空间里有真实讨论内容（绝不能进模板）
        discussion = session.client.post(
            f"/api/v1/spaces/{sid}/discussions",
            json={"title": "源空间机密讨论", "question": "不应出现在模板里"},
            headers=member,
        )
        assert discussion.status_code == 201

        # 成员越权生成模板 → 403
        forbidden = session.client.post(
            f"/api/v1/spaces/{sid}/template",
            json={"name": "成员模板", "discussionTemplates": ["x"]},
            headers=member,
        )
        assert forbidden.status_code == 403

        created = session.client.post(
            f"/api/v1/spaces/{sid}/template",
            json={
                "name": "月度精读模板",
                "description": "含两个栏目与两条开场模板",
                "discussionTemplates": [
                    "这次阅读你最不同意哪一句？",
                    "哪个引用需要重新核对？",
                ],
            },
            headers=session.owner,
        )
        assert created.status_code == 201, created.text
        template = created.json()
        assert [s["name"] for s in template["sections"]] == ["精读", "速览"]
        assert template["roleRules"] == {"requireApproval": True}
        assert len(template["discussionTemplates"]) == 2
        # 不含成员与内容：members 键不存在；成员名与讨论内容不在载荷中
        assert "members" not in template
        dumped = str(template)
        assert "n339b" not in dumped
        assert "源空间机密讨论" not in dumped

        # 重名 → 409
        dup = session.client.post(
            f"/api/v1/spaces/{sid}/template",
            json={"name": "月度精读模板", "discussionTemplates": []},
            headers=session.owner,
        )
        assert dup.status_code == 409

        # 预览零写入：预览前后模板数量一致，载荷含栏目/规则/模板与说明
        before = session.client.get("/api/v1/space-templates", headers=session.owner)
        preview = session.client.get(
            f"/api/v1/space-templates/{template['id']}/preview", headers=member
        )
        assert preview.status_code == 200
        assert preview.json()["sections"] == template["sections"]
        assert "零写入" in preview.json()["previewNote"]
        after = session.client.get("/api/v1/space-templates", headers=session.owner)
        assert len(after.json()["items"]) == len(before.json()["items"])

        # 不存在的模板 → 404
        missing = session.client.get(
            "/api/v1/space-templates/00000000-0000-0000-0000-000000000000/preview",
            headers=session.owner,
        )
        assert missing.status_code == 404


def test_apply_template_creates_fresh_space(monkeypatch, tmp_path):
    """创建新空间时先预览再应用：新空间带栏目/角色规则/讨论模板；
    成员只有创建者一人；不含任何源空间内容。"""
    with ab_session(monkeypatch, tmp_path) as session:
        space, _members = space_with_members(session, "n339c", name="应用源", requireApproval=True)
        sid = space["id"]
        member = session.login("n339c")
        section = session.client.post(
            f"/api/v1/spaces/{sid}/sections", json={"name": "共享栏目"}, headers=session.owner
        )
        assert section.status_code == 201
        template = session.client.post(
            f"/api/v1/spaces/{sid}/template",
            json={"name": "可复用模板", "discussionTemplates": ["开场问题"]},
            headers=session.owner,
        )
        template_id = template.json()["id"]

        applied = session.client.post(
            f"/api/v1/space-templates/{template_id}/create-space",
            json={"name": "由模板新建的空间", "description": "应用模板"},
            headers=member,
        )
        assert applied.status_code == 201, applied.text
        new_space = applied.json()
        assert new_space["requireApproval"] is True
        assert new_space["discussionTemplates"] == ["开场问题"]
        assert new_space["myRole"] == "manager"

        detail = session.client.get(f"/api/v1/spaces/{new_space['id']}", headers=member)
        assert detail.status_code == 200
        body = detail.json()
        assert [s["name"] for s in body["sections"]] == ["共享栏目"]
        assert [m["username"] for m in body["members"]] == ["n339c"]  # 只有创建者
