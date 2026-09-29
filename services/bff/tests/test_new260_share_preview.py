"""NEW-260 研究分享脱敏预览 — 共享前逐项盘点私人内容 + 确认快照。

- 盘点（GET，零写入）：私人笔记（note 类字段）、成员名出现位置、
  附件（诚实空表——研究组不存附件）；
- 确认（POST）：把勾选结果存成 manifest 快照（append-only），自带
  盘点计数可核对；不产出任何真实分享包；
- 校验：非数组/非字符串项 → 422；未知项目 → 404；
- 隔离：A 的盘点与确认快照对 B 404（含控制库成员名扫描按各自库）。
"""

import uuid

from fastapi.testclient import TestClient

from new2xx_ab import ab_env  # noqa: F401,F811


def _seed_project_with_private_bits(client: TestClient, title: str) -> str:
    """建项目并放一条带 note 的假设材料 + 一条带 note 的反例。

    注：单用户（basic owner）环境下控制库只有 owner 一个账号——成员名
    命中的 alice/bob 断言放 ab_env 用例，这里只断言盘点结构。"""
    project = client.post(
        "/api/v1/research/projects", json={"title": title}
    ).json()
    hid = client.post(
        f"/api/v1/research/projects/{project['id']}/hypotheses",
        json={
            "statement": "示例假设",
            "supportCondition": "S1",
            "refuteCondition": "R1",
        },
    ).json()["id"]
    client.post(
        f"/api/v1/research/hypotheses/{hid}/materials",
        json={
            "itemRef": f"library:{uuid.uuid4()}",
            "side": "support",
            "note": "这条备注只给自己看（另附 owner 手记）",
        },
    )
    client.post(
        f"/api/v1/research/projects/{project['id']}/counterexamples",
        json={
            "excerpt": "与结论冲突的原文",
            "note": "这处存疑待查",
        },
    )
    return project["id"]


def test_new260_preview_lists_private_and_members(client):  # noqa: F811
    """盘点逐项列出私人笔记与成员名出现位置；附件诚实为空。"""
    project_id = _seed_project_with_private_bits(client, "盘点项目")
    preview = client.get(
        f"/api/v1/research/projects/{project_id}/share-preview"
    ).json()

    private_ids = [n["id"] for n in preview["privateNotes"]]
    assert len(private_ids) == 2
    tables = {n["table"] for n in preview["privateNotes"]}
    assert tables == {"research_hypothesis_materials", "research_counterexamples"}

    # 控制库现有成员（basic 环境只有 owner）的精确子串命中。
    member_names = {m["username"] for m in preview["memberNames"]}
    assert member_names == {"owner"}
    for member in preview["memberNames"]:
        assert member["occurrences"], "命中必须带位置"

    assert preview["attachments"] == []
    assert "不存附件" in preview["attachmentsNote"]
    assert "不产出任何真实分享包" in preview["note"]


def test_new260_confirm_snapshot_and_validation(client):  # noqa: F811
    """确认存 manifest 快照（含盘点计数）；台账 append-only；校验 422。"""
    project_id = _seed_project_with_private_bits(client, "确认项目")
    preview = client.get(
        f"/api/v1/research/projects/{project_id}/share-preview"
    ).json()
    include_ids = [n["id"] for n in preview["privateNotes"]][:1]

    made = client.post(
        f"/api/v1/research/projects/{project_id}/share-confirmations",
        json={
            "includePrivateNoteIds": include_ids,
            "anonymizeMemberUsernames": ["bob"],
        },
    )
    assert made.status_code == 201, made.text
    confirmation = made.json()
    assert confirmation["manifest"]["includePrivateNoteIds"] == include_ids
    assert confirmation["manifest"]["anonymizeMemberUsernames"] == ["bob"]
    assert confirmation["manifest"]["privateNoteCountAtConfirm"] == 2

    listed = client.get(
        f"/api/v1/research/projects/{project_id}/share-confirmations"
    ).json()
    assert len(listed["items"]) == 1
    assert listed["items"][0]["id"] == confirmation["id"]

    # 再确认一次 → 台账两条（append-only）。
    client.post(
        f"/api/v1/research/projects/{project_id}/share-confirmations",
        json={"includePrivateNoteIds": [], "anonymizeMemberUsernames": []},
    )
    assert (
        len(
            client.get(
                f"/api/v1/research/projects/{project_id}/share-confirmations"
            ).json()["items"]
        )
        == 2
    )

    # 校验面。
    assert (
        client.post(
            f"/api/v1/research/projects/{project_id}/share-confirmations",
            json={"includePrivateNoteIds": "all", "anonymizeMemberUsernames": []},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/projects/{project_id}/share-confirmations",
            json={"includePrivateNoteIds": [42], "anonymizeMemberUsernames": []},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/research/projects/missing-pid/share-preview"
        ).status_code
        == 404
    )


def test_new260_ab_isolation(ab_env):  # noqa: F811
    """A 的盘点与确认快照对 B 404；成员名扫描只看 A 自己项目的文本。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 分享预览"}, headers=ab_env["a"]
    ).json()
    pid = project["id"]
    hid = client.post(
        f"/api/v1/research/projects/{pid}/hypotheses",
        json={
            "statement": "A 的假设",
            "supportCondition": "S",
            "refuteCondition": "R",
        },
        headers=ab_env["a"],
    ).json()["id"]
    client.post(
        f"/api/v1/research/hypotheses/{hid}/materials",
        json={
            "itemRef": f"library:{uuid.uuid4()}",
            "side": "support",
            "note": "只有 alice 知道的出处",
        },
        headers=ab_env["a"],
    )

    preview_b = client.get(
        f"/api/v1/research/projects/{pid}/share-preview", headers=ab_env["b"]
    )
    assert preview_b.status_code == 404
    assert (
        client.post(
            f"/api/v1/research/projects/{pid}/share-confirmations",
            json={"includePrivateNoteIds": [], "anonymizeMemberUsernames": []},
            headers=ab_env["b"],
        ).status_code
        == 404
    )

    # A 自己盘点：note 命中、成员名 alice 命中（B 不出现在 A 的库里）。
    preview = client.get(
        f"/api/v1/research/projects/{pid}/share-preview", headers=ab_env["a"]
    ).json()
    assert len(preview["privateNotes"]) == 1
    assert {m["username"] for m in preview["memberNames"]} == {"alice"}
