"""NEW-399 帮助文档反馈定位 — 版本/锚点定位、管理员闭环、391 通知闭环。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

REAL_DOC = "README.md"
REAL_ANCHOR = "LumiRSS"  # README 标题行里真实出现的词


def test_new399_submit_locates_version_and_anchor(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    created = client.post(
        "/api/v1/help/feedback",
        json={"docPath": REAL_DOC, "anchor": REAL_ANCHOR,
              "question": "这一段说的导入流程和当前版本界面不一致。"},
        headers=a,
    )
    assert created.status_code == 201, created.text
    feedback = created.json()
    assert feedback["version"] == "2.0.1"
    assert feedback["anchorFound"] is True
    assert feedback["status"] == "open"
    # 锚点找不到 = anchorFound false（检测结论不是保证），仍可提交
    missing_anchor = client.post(
        "/api/v1/help/feedback",
        json={"docPath": REAL_DOC, "anchor": "不存在的小节",
              "question": "锚点失效了。"},
        headers=a,
    )
    assert missing_anchor.status_code == 201
    assert missing_anchor.json()["anchorFound"] is False
    # 校验：未知文档 / 越界路径 / 空问题
    assert (
        client.post(
            "/api/v1/help/feedback",
            json={"docPath": "no/such/doc.md", "question": "x"},
            headers=a,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/help/feedback",
            json={"docPath": "../README.md", "question": "x"},
            headers=a,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/help/feedback",
            json={"docPath": REAL_DOC, "anchor": REAL_ANCHOR, "question": "  "},
            headers=a,
        ).status_code
        in (400, 422)
    )
    own = client.get("/api/v1/help/feedback", headers=a).json()
    assert len(own["items"]) == 2


def test_new399_admin_resolve_and_notification_loop(ab_env):  # noqa: F811
    client, a, owner = ab_env["client"], ab_env["a"], ab_env["owner"]
    feedback = client.post(
        "/api/v1/help/feedback",
        json={"docPath": REAL_DOC, "anchor": REAL_ANCHOR, "question": "步骤过期。"},
        headers=a,
    ).json()
    # 成员看不到管理队列
    denied = client.get("/api/v1/admin/help/feedback", headers=a)
    assert denied.status_code == 403
    queue = client.get(
        "/api/v1/admin/help/feedback?status=open", headers=owner
    ).json()
    assert any(item["id"] == feedback["id"] for item in queue["items"])
    assert queue["items"][0]["version"] == "2.0.1"
    # resolve 是终态；校验空修订/回复
    assert (
        client.post(
            f"/api/v1/admin/help/feedback/{feedback['id']}/resolve",
            json={"revisionNote": "  ", "reply": "已修订。"},
            headers=owner,
        ).status_code
        == 422
    )
    resolved = client.post(
        f"/api/v1/admin/help/feedback/{feedback['id']}/resolve",
        json={"revisionNote": "§2 安装步骤按 2.0.1 重写。",
              "reply": "已在当前版本文档修订，请再看一眼。"},
        headers=owner,
    )
    assert resolved.status_code == 200, resolved.text
    body = resolved.json()
    assert body["status"] == "revised" and body["resolvedAt"] is not None
    # 终态不可再次 resolve
    assert (
        client.post(
            f"/api/v1/admin/help/feedback/{feedback['id']}/resolve",
            json={"revisionNote": "再来一次", "reply": "不行"},
            headers=owner,
        ).status_code
        == 422
    )
    # 真实事件 → NEW-391 收件箱出现「帮助已回复」通知（只来自真实事件）
    inbox = client.get("/api/v1/notifications", headers=a).json()
    answered = [item for item in inbox["items"] if item["kind"] == "help_answered"]
    assert len(answered) == 1
    assert answered[0]["title"] == "你的文档反馈已处理"
    assert "修订" in answered[0]["body"]
    assert answered[0]["ref"] == f"help-feedback:{feedback['id']}"
    # 作者的反馈列表看到处理结果
    own = client.get("/api/v1/help/feedback", headers=a).json()
    entry = next(item for item in own["items"] if item["id"] == feedback["id"])
    assert entry["status"] == "revised" and "重写" in entry["revisionNote"]
    missing = client.post(
        "/api/v1/admin/help/feedback/999999/resolve",
        json={"revisionNote": "x", "reply": "y"},
        headers=owner,
    )
    assert missing.status_code == 404


def test_new399_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    feedback = client.post(
        "/api/v1/help/feedback",
        json={"docPath": REAL_DOC, "anchor": REAL_ANCHOR, "question": "A 的问题。"},
        headers=a,
    ).json()
    # B 的列表里没有 A 的反馈
    assert client.get("/api/v1/help/feedback", headers=b).json()["items"] == []
    # B（成员）不能 resolve A 的反馈
    assert (
        client.post(
            f"/api/v1/admin/help/feedback/{feedback['id']}/resolve",
            json={"revisionNote": "越权", "reply": "越权"},
            headers=b,
        ).status_code
        == 403
    )
    own = client.get("/api/v1/help/feedback", headers=a).json()
    entry = next(item for item in own["items"] if item["id"] == feedback["id"])
    assert entry["status"] == "open"
