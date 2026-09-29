"""NEW-305 接入死信处理页 — 脱敏摘要/修正后重放/副作用不重放/隔离。"""

import asyncio
import json

from lumirss.main import app
from lumirss.new304_webhook_keys import SigningKeyStore, signature_header
from lumirss.new305_dead_letters import DeadLetterStore, summarize_payload
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

SECRET_VALUE = "SUPER-SECRET-VALUE"


def _run(coroutine):
    return asyncio.run(coroutine)


def _letter_store(tmp_path):
    from lumirss.storage import Database

    database = Database(tmp_path / "lumi.sqlite")
    _run(database.migrate())
    return DeadLetterStore(database)


def test_new305_summary_shapes():
    raw = json.dumps(
        {"eventId": "e1", "token": SECRET_VALUE, "count": 3, "ok": True, "tags": [1]}
    )
    summary = summarize_payload(raw)
    assert summary["topLevelType"] == "object"
    assert SECRET_VALUE not in str(summary)
    types = {entry["name"]: entry["type"] for entry in summary["keys"]}
    assert types["token"] == "string"
    assert types["count"] == "number"
    assert types["ok"] == "boolean"
    assert types["tags"] == "array"
    assert summarize_payload("{broken")["topLevelType"] == "invalid_json"
    listed = summarize_payload("[1,2,3]")
    assert listed["topLevelType"] == "array"
    assert listed["length"] == 3




def test_new305_store_dedupes_and_truncates(tmp_path):
    """同事件重复失败 → 同一条 pending 原地更新；超大原文截断并标记。"""
    store = _letter_store(tmp_path)
    big_text = "x" * (200 * 1024)
    first_id = _run(
        store.record(
            endpoint_uuid="ep",
            event_id="evt-1",
            reason="第一次失败。",
            raw_text='{"note":"a',
        )
    )
    second_id = _run(
        store.record(
            endpoint_uuid="ep",
            event_id="evt-1",
            reason="第二次失败（更新同一行）。",
            raw_text='{"note":"b',
        )
    )
    assert first_id == second_id
    big_id = _run(
        store.record(
            endpoint_uuid="ep",
            event_id="evt-big",
            reason="超大。",
            raw_text=big_text,
        )
    )
    letters = _run(store.list_dead_letters())
    assert len(letters) == 2
    by_event = {}
    for letter in letters:
        by_event[letter["eventId"]] = letter
    assert "第二次失败" in by_event["evt-1"]["reason"]
    assert "payload_raw" not in by_event["evt-1"]
    assert by_event["evt-big"]["payloadSummary"]["truncated"] is True
    raw_row = _run(store.get(big_id))
    raw_stored = str(raw_row["payload_raw"])
    assert len(raw_stored) < len(big_text)


def _endpoint_with_key(client):
    created = client.post("/api/v1/webhooks/endpoints", json={"label": "dl-flow"})
    assert created.status_code == 201, created.text
    endpoint = created.json()
    key = _run(SigningKeyStore(app.state.control_db).rotate(10))
    return endpoint, key["secret"]


def _ts_now():
    import time

    return int(time.time())


def _ingest(client, endpoint, key_plain, body):
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + endpoint["secret"],
        "X-Lumi-Signature": signature_header(_ts_now(), body, key_plain),
    }
    return client.post(
        "/api/v1/webhooks/ingest/" + endpoint["uuid"], content=body, headers=headers
    )


def test_new305_dead_letter_then_fixed_replay(client):
    """经由 303 接入产生的死信：清单脱敏；修正事件后重放成功进待确认
    区；死信标记 replayed；二次重放 409。"""
    endpoint, key = _endpoint_with_key(client)
    bad = json.dumps(
        {"eventId": "evt-9", "note": SECRET_VALUE, "items": [{"id": "d1"}]}
    ).encode("utf-8")
    first = _ingest(client, endpoint, key, bad)
    assert first.status_code == 202, first.text
    assert first.json()["deadLettered"] is True

    listed = client.get("/api/v1/webhooks/dead-letters")
    assert listed.status_code == 200
    assert SECRET_VALUE not in listed.text
    assert "payload_raw" not in listed.text
    letters = listed.json()["items"]
    assert len(letters) == 1
    letter_id = letters[0]["id"]
    assert letters[0]["status"] == "pending"

    fixed = json.dumps(
        {"eventId": "evt-9", "items": [{"id": "d1", "title": "修正后条目"}]}
    )
    replay = client.post(
        f"/api/v1/webhooks/dead-letters/{letter_id}/replay",
        json={"rawPayload": fixed},
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["replayed"] is True
    assert body["stored"] == 1

    pending = client.get("/api/v1/webhooks/inbox?status=pending").json()["items"]
    assert len(pending) == 1
    assert pending[0]["title"] == "修正后条目"

    after = client.get("/api/v1/webhooks/dead-letters?status=replayed").json()["items"]
    assert len(after) == 1
    assert after[0]["replayedAt"]

    second = client.post(f"/api/v1/webhooks/dead-letters/{letter_id}/replay", json={})
    assert second.status_code == 409
    assert second.json()["error"]["type"] == "dead_letter_already_replayed"


def test_new305_replay_still_broken_stays_pending(client):
    """无法修复的重放：死信保持 pending，原因更新，可再次尝试。"""
    endpoint, key = _endpoint_with_key(client)
    broken = b"this is not json at all"
    first = _ingest(client, endpoint, key, b'{"eventId":"e","items":[]}')
    assert first.status_code == 202
    bad_json = _ingest(client, endpoint, key, broken)
    assert bad_json.status_code == 400

    letters = client.get("/api/v1/webhooks/dead-letters?status=pending").json()["items"]
    target = None
    for letter in letters:
        if "不可解析" in letter["reason"]:
            target = letter
    assert target is not None

    replay = client.post(
        f"/api/v1/webhooks/dead-letters/{target['id']}/replay", json={}
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is False
    assert "仍不可解析" in replay.json()["reason"]

    still = client.get("/api/v1/webhooks/dead-letters?status=pending").json()["items"]
    ids = [letter["id"] for letter in still]
    assert target["id"] in ids


def test_new305_no_replay_of_already_accepted_side_effects(client):
    """事件已成功纳入（已裁决）后的死信重放：零新增行，明示「副作用
    不重放」（inbox 的 (endpoint, event, item) 唯一性兜底）。"""
    endpoint, key = _endpoint_with_key(client)

    good = json.dumps(
        {"eventId": "evt-d1", "items": [{"id": "r1", "title": "已纳入条目"}]}
    ).encode("utf-8")
    ok = _ingest(client, endpoint, key, good)
    assert ok.status_code == 202 and ok.json()["stored"] == 1
    pending = client.get("/api/v1/webhooks/inbox?status=pending").json()["items"]
    target_id = None
    for row in pending:
        if "evt-d1" in row["eventId"]:
            target_id = row["id"]
    assert target_id is not None
    assert client.post(f"/api/v1/webhooks/inbox/{target_id}/accept").status_code == 200

    # 同一事件第二次投递损坏（条目缺 title）→ 死信
    broken_second = json.dumps(
        {"eventId": "evt-d1", "note": "attempt-2", "items": [{"id": "r1"}]}
    ).encode("utf-8")
    second = _ingest(client, endpoint, key, broken_second)
    assert second.status_code == 202 and second.json()["deadLettered"] is True
    letters = client.get("/api/v1/webhooks/dead-letters?status=pending").json()["items"]
    letter_id = letters[0]["id"]
    inbox_before = client.get("/api/v1/webhooks/inbox").json()["items"]

    # 用户修正后重放：同一 (endpoint, event, item) 已裁决 → 不产生新行
    fixed = json.dumps(
        {"eventId": "evt-d1", "items": [{"id": "r1", "title": "修正标题"}]}
    )
    replay = client.post(
        f"/api/v1/webhooks/dead-letters/{letter_id}/replay",
        json={"rawPayload": fixed},
    )
    assert replay.status_code == 200, replay.text
    body = replay.json()
    assert body["replayed"] is True
    assert body["stored"] == 0
    assert body["note"] and "未重放任何新副作用" in body["note"]

    inbox_after = client.get("/api/v1/webhooks/inbox").json()["items"]
    assert len(inbox_after) == len(inbox_before)

def test_new305_cross_user_isolated(ab_env):  # noqa: F811 — pytest 夹具注册
    """A 的死信（含其重放入口）对 B 完全不可见。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]

    created = client.post(
        "/api/v1/webhooks/endpoints", headers=a, json={"label": "A 的死信端点"}
    )
    assert created.status_code == 201, created.text
    endpoint_uuid = created.json()["uuid"]

    async def store_letter(user_id, marker):
        from lumirss.new305_dead_letters import DeadLetterStore as _DLStore
        from lumirss.user_scope import user_context

        with user_context(user_id):
            await env["app"].state.db.migrate()
            letters = _DLStore(env["app"].state.db)
            return await letters.record(
                endpoint_uuid=endpoint_uuid,
                event_id="evt-" + marker,
                reason="隔离样本",
                raw_text=json.dumps({"marker": "VALUE-" + marker}),
            )

    a_id = _member_id(env, a)
    b_id = _member_id(env, b)
    letter_a = _run(store_letter(a_id, "a"))
    letter_b = _run(store_letter(b_id, "b"))
    assert letter_a is not None and letter_b is not None

    def scope_events(headers):
        rows = client.get(
            "/api/v1/webhooks/dead-letters", headers=headers
        ).json()["items"]
        return sorted(str(letter["eventId"]) for letter in rows)

    # 各自只看得到自己作用域里的死信（跨 per-user 库自增 id 相同是
    # 正常的 —— 隔离性断言看事件内容可见性）
    assert scope_events(headers=b) == ["evt-b"]
    assert scope_events(headers=a) == ["evt-a"]
    a_after = client.get(
        "/api/v1/webhooks/dead-letters?status=pending", headers=a
    ).json()["items"]
    assert len(a_after) == 1 and a_after[0]["status"] == "pending"


def _member_id(env, member) -> str:
    """会话模式取激活响应里的 userId；缺失时探测 /auth/session。"""
    if member["userId"]:
        return str(member["userId"])
    probe = env["client"].get(
        "/api/v1/auth/session", headers={"cookie": member["cookie"]}
    )
    return str(probe.json().get("userId") or "")
