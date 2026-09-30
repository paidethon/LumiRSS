"""NEW-367 搜索会话回溯 — 步骤序列 / 选中结果 / 重新打开接续最后一步 / 隔离。"""

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

SESSIONS_PATH = "/api/v1/search/sessions"


def _build_session(client, headers) -> dict:
    created = client.post(
        SESSIONS_PATH, json={"title": "内核调度器调研"}, headers=headers
    )
    assert created.status_code == 201, created.text
    session = created.json()
    sid = session["id"]
    first = client.post(
        f"{SESSIONS_PATH}/{sid}/steps",
        json={"query": "内核 调度", "filters": {"state": "unread"}},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"{SESSIONS_PATH}/{sid}/steps",
        json={"query": "内核 内存"},
        headers=headers,
    )
    assert second.status_code == 201
    ref = encode_entry_ref('n367-pick')
    selection = client.post(
        f"{SESSIONS_PATH}/{sid}/selections",
        json={"refs": [ref, ref, "rss:other"]},  # 重复 ref 去重
        headers=headers,
    )
    assert selection.status_code == 200, selection.text
    return selection.json()


def test_new367_session_resume_at_last_step(ab_env):  # noqa: F811
    """重新打开接续到最后一步：resumeStep=最后一步；历史步骤不改写。"""
    client = ab_env["client"]
    seed_entry(ab_env, "a", "n367-pick", title="内核 选中结果")
    detail = _build_session(client, ab_env["a"])
    sid = detail["id"]
    assert detail["currentStep"] == 1
    assert detail["resumeStep"] == 1
    assert detail["steps"][0]["query"] == "内核 调度"
    assert detail["steps"][1]["query"] == "内核 内存"
    # 选中结果记到最后一步，重复 ref 已去重。
    assert detail["steps"][1]["refs"] == [
        encode_entry_ref('n367-pick'),
        "rss:other",
    ]
    assert detail["steps"][0]["refs"] == []
    assert detail["steps"][0]["filters"] == {"state": "unread"}

    reopened = client.post(
        f"{SESSIONS_PATH}/{sid}/reopen", headers=ab_env["a"]
    )
    assert reopened.status_code == 200
    body = reopened.json()
    assert body["reopened"] is True
    assert body["resumeStep"] == body["currentStep"] == 1

    listing = client.get(SESSIONS_PATH, headers=ab_env["a"]).json()
    assert [item["id"] for item in listing["items"]] == [sid]
    assert listing["items"][0]["stepCount"] == 2


def test_new367_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    assert client.get(f"{SESSIONS_PATH}/nope", headers=ab_env["a"]).status_code == 404
    assert (
        client.post(f"{SESSIONS_PATH}/nope/reopen", headers=ab_env["a"]).status_code
        == 404
    )
    created = client.post(
        SESSIONS_PATH, json={"title": "空会话"}, headers=ab_env["a"]
    )
    assert created.status_code == 201
    empty_selection = client.post(
        f"{SESSIONS_PATH}/{created.json()['id']}/selections",
        json={"refs": []},
        headers=ab_env["a"],
    )
    assert empty_selection.status_code == 409
    bad_title = client.post(
        SESSIONS_PATH, json={"title": ""}, headers=ab_env["a"]
    )
    assert bad_title.status_code == 422


def test_new367_isolation(ab_env):  # noqa: F811
    """A 的会话对 B 完全不可见（列表为空、详情 404 同缺失语义）。"""
    client = ab_env["client"]
    seed_entry(ab_env, "a", "n367-pick", title="内核 选中结果")
    detail = _build_session(client, ab_env["a"])
    assert client.get(SESSIONS_PATH, headers=ab_env["b"]).json()["items"] == []
    assert (
        client.get(
            f"{SESSIONS_PATH}/{detail['id']}", headers=ab_env["b"]
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{SESSIONS_PATH}/{detail['id']}/reopen", headers=ab_env["b"]
        ).status_code
        == 404
    )
