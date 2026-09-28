"""NEW-228 阅读中断便签（服务端）。

- 离开前写/改接续便签（thought 1..500 + resumeHint ≤300；一篇一个
  活跃便签，latest-wins）；
- 返回文章时 GET 显示活跃便签（无活跃 → note=null 诚实空态 + 归档
  计数）；
- 读完显式归档（archived_at 记账；归档后可写新便签 = 新旅程）；
- 活跃清单（跨材料「读到一半」）+ 归档历史；
- A/B 每用户隔离 + 校验。
"""

from fastapi.testclient import TestClient

from new2xx_ab import seed_entry  # noqa: F811


def _upsert(client: TestClient, headers: dict, ref: str, thought: str, hint: str | None = None):
    payload: dict = {"itemRef": ref, "thought": thought}
    if hint is not None:
        payload["resumeHint"] = hint
    return client.put("/api/v1/reading/interruption-notes", json=payload, headers=headers)


def test_upsert_latest_wins_and_return_view(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "n1", title="长访谈")
    made = _upsert(client, ab_env["a"], ref, "读到这里，作者还没给证据", "第 4 节末尾")
    assert made.status_code == 200, made.text
    note_id = made.json()["id"]

    # 再写 = 覆盖（latest-wins，同一行，无冲突分支）。
    second = _upsert(client, ab_env["a"], ref, "作者在第 6 节给了数据", "第 6 节图表")
    assert second.status_code == 200
    assert second.json()["id"] == note_id
    assert second.json()["thought"] == "作者在第 6 节给了数据"
    assert second.json()["resumeHint"] == "第 6 节图表"

    # 返回文章时的接续视图。
    view = client.get(
        "/api/v1/reading/interruption-notes", params={"itemRef": ref},
        headers=ab_env["a"],
    )
    assert view.status_code == 200
    body = view.json()
    assert body["note"]["thought"] == "作者在第 6 节给了数据"
    assert body["archivedCount"] == 0

    # 活跃清单（跨材料「读到一半」）。
    listing = client.get(
        "/api/v1/reading/interruption-notes/all", headers=ab_env["a"]
    )
    assert listing.status_code == 200
    assert listing.json()["items"][0]["itemRef"] == ref


def test_archive_then_new_note(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "n2", title="长文")
    _upsert(client, ab_env["a"], ref, "还差结论部分", "结论")

    archived = client.post(
        "/api/v1/reading/interruption-notes/archive",
        params={"itemRef": ref},
        headers=ab_env["a"],
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archivedAt"] is not None

    # 归档后：活跃视图 = null + archivedCount=1。
    view = client.get(
        "/api/v1/reading/interruption-notes", params={"itemRef": ref},
        headers=ab_env["a"],
    ).json()
    assert view["note"] is None
    assert view["archivedCount"] == 1

    # 归档历史可查；归档后可写新便签（新旅程）。
    history = client.get(
        "/api/v1/reading/interruption-notes/archived",
        params={"itemRef": ref},
        headers=ab_env["a"],
    )
    assert history.json()["items"][0]["thought"] == "还差结论部分"
    new_note = _upsert(client, ab_env["a"], ref, "重读一遍结论")
    assert new_note.status_code == 200
    assert new_note.json()["id"] != archived.json()["id"]

    # 没有活跃便签时归档 → 404。
    other = seed_entry(ab_env, "a", "n3")
    missing = client.post(
        "/api/v1/reading/interruption-notes/archive",
        params={"itemRef": other},
        headers=ab_env["a"],
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "interruption_note_not_found"


def test_delete_active_note(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "n4")
    _upsert(client, ab_env["a"], ref, "不要了")
    deleted = client.delete(
        "/api/v1/reading/interruption-notes", params={"itemRef": ref},
        headers=ab_env["a"],
    )
    assert deleted.status_code == 204
    view = client.get(
        "/api/v1/reading/interruption-notes", params={"itemRef": ref},
        headers=ab_env["a"],
    ).json()
    assert view["note"] is None
    assert view["archivedCount"] == 0


def test_validation_and_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "n5", title="A 的文章")
    empty = _upsert(client, ab_env["a"], ref, "  ")
    assert empty.status_code == 422
    assert empty.json()["error"]["type"] == "invalid_interruption_note"
    too_long = _upsert(client, ab_env["a"], ref, "字" * 501)
    assert too_long.status_code == 422

    # B 看不到 A 的便签（活跃视图为空态）。
    b_view = client.get(
        "/api/v1/reading/interruption-notes", params={"itemRef": ref},
        headers=ab_env["b"],
    ).json()
    assert b_view["note"] is None
    # B 归档 A 的便签 → 404（不泄露存在性）。
    b_archive = client.post(
        "/api/v1/reading/interruption-notes/archive",
        params={"itemRef": ref},
        headers=ab_env["b"],
    )
    assert b_archive.status_code == 404
