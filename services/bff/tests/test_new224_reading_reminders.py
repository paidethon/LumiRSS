"""NEW-224 阅读预约清单（服务端）。

- 一次性预约 CRUD：create（活跃上限）/ list（due 标注）/ reschedule /
  cancel（幂等）/ complete / delete；
- 提示面只在应用内：due = active 且 remind_at ≤ now（服务端时间），
  首次被读到记 reminded_at，状态不变直到用户显式处置；
  channel 恒为 in-app，响应 note 明示无推送/邮件；
- A/B 每用户隔离 + 时间戳/超限校验。
"""

from datetime import UTC, datetime, timedelta

from new2xx_ab import ab_env, seed_entry  # noqa: F401,F811


def _iso(delta_seconds: int) -> str:
    moment = datetime.now(UTC) + timedelta(seconds=delta_seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_create_list_and_in_app_channel(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "r1", title="预约文")
    made = client.post(
        "/api/v1/reading/reminders",
        json={"itemRef": ref, "remindAt": _iso(3600), "note": "晚饭后读"},
        headers=ab_env["a"],
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["status"] == "active"
    assert body["note"] == "晚饭后读"

    listing = client.get("/api/v1/reading/reminders", headers=ab_env["a"])
    assert listing.status_code == 200
    payload = listing.json()
    assert payload["channel"] == "in-app"
    assert "推送" in payload["note"]
    assert payload["items"][0]["itemRef"] == ref
    assert payload["items"][0]["due"] is False


def test_due_marks_reminded_once(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "r2", title="到期文")
    made = client.post(
        "/api/v1/reading/reminders",
        json={"itemRef": ref, "remindAt": _iso(-60)},
        headers=ab_env["a"],
    )
    assert made.status_code == 201
    reminder_id = made.json()["id"]

    first = client.get("/api/v1/reading/reminders/due", headers=ab_env["a"])
    assert first.status_code == 200
    body = first.json()
    assert len(body["items"]) == 1 and body["items"][0]["id"] == reminder_id
    assert body["items"][0]["remindedAt"] is not None

    second = client.get("/api/v1/reading/reminders/due", headers=ab_env["a"])
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    # reminded_at 不被二次改写（一次性触达标记）。
    assert second.json()["items"][0]["remindedAt"] == body["items"][0]["remindedAt"]

    # 到期 ≠ 自动处置：仍 active，直到用户 complete。
    row = client.get(
        "/api/v1/reading/reminders", headers=ab_env["a"]
    ).json()["items"][0]
    assert row["status"] == "active"
    completed = client.post(
        f"/api/v1/reading/reminders/{reminder_id}/complete", headers=ab_env["a"]
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    # done 不再出现在 due。
    due = client.get("/api/v1/reading/reminders/due", headers=ab_env["a"])
    assert due.json()["items"] == []
    # done 不能再取消。
    cancel_done = client.post(
        f"/api/v1/reading/reminders/{reminder_id}/cancel", headers=ab_env["a"]
    )
    assert cancel_done.status_code == 422


def test_reschedule_and_cancel(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "r3")
    made = client.post(
        "/api/v1/reading/reminders",
        json={"itemRef": ref, "remindAt": _iso(600)},
        headers=ab_env["a"],
    )
    reminder_id = made.json()["id"]
    moved = client.post(
        f"/api/v1/reading/reminders/{reminder_id}/reschedule",
        json={"remindAt": _iso(7200)},
        headers=ab_env["a"],
    )
    assert moved.status_code == 200
    assert moved.json()["remindAt"] > made.json()["remindAt"]

    cancelled = client.post(
        f"/api/v1/reading/reminders/{reminder_id}/cancel", headers=ab_env["a"]
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # 取消幂等。
    again = client.post(
        f"/api/v1/reading/reminders/{reminder_id}/cancel", headers=ab_env["a"]
    )
    assert again.status_code == 200
    # 取消后不能改期。
    moved_again = client.post(
        f"/api/v1/reading/reminders/{reminder_id}/reschedule",
        json={"remindAt": _iso(9000)},
        headers=ab_env["a"],
    )
    assert moved_again.status_code == 422
    # 默认列表不含 cancelled；显式包含可见。
    default_list = client.get("/api/v1/reading/reminders", headers=ab_env["a"])
    assert default_list.json()["items"] == []
    with_cancelled = client.get(
        "/api/v1/reading/reminders",
        params={"includeCancelled": "true"},
        headers=ab_env["a"],
    )
    assert len(with_cancelled.json()["items"]) == 1
    # 物理删除。
    deleted = client.delete(
        f"/api/v1/reading/reminders/{reminder_id}", headers=ab_env["a"]
    )
    assert deleted.status_code == 204
    assert (
        client.delete(
            f"/api/v1/reading/reminders/{reminder_id}", headers=ab_env["a"]
        ).status_code
        == 404
    )


def test_validation_and_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "r4")
    bad_time = client.post(
        "/api/v1/reading/reminders",
        json={"itemRef": ref, "remindAt": "not-a-time"},
        headers=ab_env["a"],
    )
    assert bad_time.status_code == 422
    assert bad_time.json()["error"]["type"] == "invalid_reading_reminder"
    bad_ref = client.post(
        "/api/v1/reading/reminders",
        json={"itemRef": "nope", "remindAt": _iso(60)},
        headers=ab_env["a"],
    )
    assert bad_ref.status_code == 422

    # B 看不到 A 的预约；B 的 due 为空。
    b_list = client.get("/api/v1/reading/reminders", headers=ab_env["b"])
    assert b_list.json()["items"] == []
    b_due = client.get("/api/v1/reading/reminders/due", headers=ab_env["b"])
    assert b_due.json()["items"] == []
    # 不存在的预约 → 404（跨用户同样 404，不泄露存在性）。
    assert (
        client.post(
            "/api/v1/reading/reminders/rrem-nope/cancel", headers=ab_env["a"]
        ).status_code
        == 404
    )
