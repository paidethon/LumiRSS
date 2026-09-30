"""NEW-394 通知动作撤回提示 — 显式撤销登记、读取时联判失效、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from test_new391_notifications import _seed, _user_ids  # noqa: F401 — 同目录夹具复用


def _setup_actionable(env):
    ids = _user_ids(env)
    a_event = _seed(env, ids["a"], kind="share_event", source="space:alpha",
                    title="共享空间有新内容", ref="space:alpha", actionable=True)
    b_event = _seed(env, ids["b"], kind="task_failed", source="digest",
                    title="B 的任务失败", ref="digest:9", actionable=True)
    return a_event, b_event


def test_new394_register_revocation_and_read_side_join(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    a_event, _ = _setup_actionable(ab_env)
    # 登记前：actionable 为真
    before = client.get("/api/v1/notifications", headers=a).json()["items"][0]
    assert before["actionable"] is True
    assert before["invalidReason"] is None
    # 显式登记撤销（上游撤销流程 / 本人收回原事件）
    registered = client.post(
        f"/api/v1/notifications/{a_event['id']}/revocation",
        json={"reason": "共享链接已被本人收回。"},
        headers=a,
    )
    assert registered.status_code == 200, registered.text
    body = registered.json()
    assert body["invalidReason"] == "共享链接已被本人收回。"
    assert body["notificationId"] == a_event["id"]
    # 读取侧联判：actionable 强制为假 + 失效原因可见
    after = client.get("/api/v1/notifications", headers=a).json()["items"][0]
    assert after["actionable"] is False
    assert after["invalidReason"] == "共享链接已被本人收回。"
    detail = client.get(
        f"/api/v1/notifications/{a_event['id']}/revocation", headers=a
    ).json()
    assert detail["invalidReason"] == "共享链接已被本人收回。"
    # 重复登记 = 最新事实覆盖（不堆叠历史）
    updated = client.post(
        f"/api/v1/notifications/{a_event['id']}/revocation",
        json={"reason": "权限也已回收。"},
        headers=a,
    )
    assert updated.status_code == 200
    assert updated.json()["invalidReason"] == "权限也已回收。"


def test_new394_validation_and_missing(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    empty = client.post(
        "/api/v1/notifications/999999/revocation",
        json={"reason": "原因"},
        headers=a,
    )
    assert empty.status_code == 404
    blank = client.post(
        "/api/v1/notifications/1/revocation", json={"reason": "  "}, headers=a
    )
    assert blank.status_code in (404, 422)
    assert (
        client.get("/api/v1/notifications/1/revocation", headers=a).status_code == 404
    )


def test_new394_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    a_event, b_event = _setup_actionable(ab_env)
    # B 不能撤销 A 的通知（404 同形，不泄露存在性）
    denied = client.post(
        f"/api/v1/notifications/{a_event['id']}/revocation",
        json={"reason": "越权尝试"},
        headers=b,
    )
    assert denied.status_code == 404
    # A 的动作仍然有效（未受 B 影响）
    ok = client.post(
        f"/api/v1/notifications/{a_event['id']}/revocation",
        json={"reason": "本人收回。"},
        headers=a,
    )
    assert ok.status_code == 200
    # B 的通知不受 A 的撤销影响，B 看不到 A 的失效原因
    b_view = client.get("/api/v1/notifications", headers=b).json()["items"]
    target = next(item for item in b_view if item["id"] == b_event["id"])
    assert target["actionable"] is True
    assert target["invalidReason"] is None
    assert client.get(
        f"/api/v1/notifications/{a_event['id']}/revocation", headers=b
    ).status_code == 404
