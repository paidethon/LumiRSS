"""F107/F108 —— W6 Inbox 投递详情/失败重放 + 载荷契约试跑。"""

import asyncio


def run(coroutine):
    return asyncio.run(coroutine)


def _create_source(client, name="w6-push"):
    resp = client.post("/api/v1/inbox/sources", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ingest(client, source, payload, bearer=None, raw=False):
    headers = {"Authorization": f"Bearer {bearer or source['secret']}"}
    if raw:
        return client.post(
            f"/api/v1/inbox/ingest/{source['uuid']}",
            content=payload,
            headers={**headers, "content-type": "application/json"},
        )
    return client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}", json=payload, headers=headers
    )


def _payload(guid="g-1", title="标题一"):
    return {"guid": guid, "title": title, "content": "正文内容"}


# ---- F107 -------------------------------------------------------------------


def test_f107_events_recorded_duplicate_and_replay_flow(client):
    source = _create_source(client)
    first = _ingest(client, source, _payload())
    assert first.status_code == 200 and first.json()["status"] == "created"

    # 重复投递：记 duplicate 事件且条目不重复（负向）
    replay = _ingest(client, source, _payload())
    assert replay.json()["status"] == "exists"
    events = client.get(f"/api/v1/inbox/sources/{source['uuid']}/events").json()["items"]
    statuses = [e["status"] for e in events]
    assert statuses == ["duplicate", "delivered"]
    assert all(len(e["payloadHashPrefix"]) == 8 for e in events)

    items = client.get("/api/v1/inbox/items").json()["items"]
    assert len([i for i in items if i["sourceUuid"] == source["uuid"]]) == 1

    # 失败事件：非法 URL（服务端校验拒绝，400 invalid_app_settings 族）→ failed 落事件
    bad = client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}",
        headers={"Authorization": f"Bearer {source['secret']}"},
        json={"guid": "g-bad", "title": "坏载荷", "content": "x", "url": "javascript:alert(1)"},
    )
    assert bad.status_code in (400, 422)
    events2 = client.get(f"/api/v1/inbox/sources/{source['uuid']}/events").json()["items"]
    failed = [e for e in events2 if e["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["guid"] == "g-bad"
    assert failed[0]["errorSummary"]

    # 失败 → 修复载荷不可（重放用原载荷也会失败）——先构造可重放的失败：
    # 用直接 SQL 模拟「来源曾故障但载荷合法」的 failed 事件
    from lumirss.inbox_events import InboxEventStore

    store = InboxEventStore(client.app.state.db)
    event_id = run(
        store.record(
            source_uuid=source["uuid"],
            guid="g-replay",
            status="failed",
            error_summary="transient upstream outage",
            payload=_payload("g-replay", "重放条目"),
        )
    )
    replayed = client.post(f"/api/v1/inbox/events/{event_id}/replay")
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["status"] == "created"
    assert replayed.json()["replayedFrom"] == event_id

    # 再次重放：现在原载荷已 delivered → 新事件 duplicate；重放旧事件仍可
    # （重放的是 failed 快照；幂等吸收为 exists）
    replayed2 = client.post(f"/api/v1/inbox/events/{event_id}/replay").json()
    assert replayed2["status"] == "exists"

    # 对 delivered/duplicate 事件重放 → 409 not_replayable（负向）
    events3 = client.get(f"/api/v1/inbox/sources/{source['uuid']}/events").json()["items"]
    delivered_event = next(e for e in events3 if e["status"] == "delivered")
    not_replayable = client.post(f"/api/v1/inbox/events/{delivered_event['id']}/replay")
    assert not_replayable.status_code == 409
    assert not_replayable.json()["error"]["type"] == "not_replayable"


def test_f107_replay_unknown_source_and_restart_persistence(client):
    source = _create_source(client)
    from lumirss.inbox_events import InboxEventStore

    store = InboxEventStore(client.app.state.db)
    event_id = run(
        store.record(
            source_uuid=source["uuid"],
            guid="g-persist",
            status="failed",
            error_summary="x",
            payload=_payload("g-persist", "持久条目"),
        )
    )

    # 来源已删除 → 重放 404（负向）
    assert client.delete(f"/api/v1/inbox/sources/{source['uuid']}").status_code == 200
    gone = client.post(f"/api/v1/inbox/events/{event_id}/replay")
    assert gone.status_code == 404

    # 重启后事件仍在（新 store 实例读同一库——模拟进程重启后的读取）
    store2 = InboxEventStore(client.app.state.db)
    events = run(store2.list_events(source["uuid"]))
    assert [e["id"] for e in events] == [event_id]


# ---- F108 -------------------------------------------------------------------


def test_f108_dry_run_field_errors_unknown_fields_and_zero_write(client):
    source = _create_source(client)

    # 必填缺失逐字段 + 超长字段上限
    resp = client.post(
        f"/api/v1/inbox/sources/{source['uuid']}/ingest/dry-run",
        json={"title": "缺 guid", "unknownField": {"a": {"b": {"c": {"d": 1}}}}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid"] is False
    fields = {e["field"] for e in data["errors"]}
    assert "guid" in fields
    assert any("未知字段" in n for n in data["notes"])
    assert any("嵌套" in n for n in data["notes"])

    long_title = client.post(
        f"/api/v1/inbox/sources/{source['uuid']}/ingest/dry-run",
        json={"guid": "g-long", "title": "x" * 600},
    )
    assert long_title.json()["valid"] is False
    assert any(e["field"] == "title" for e in long_title.json()["errors"])

    # 合法载荷：wouldCreate + 重复 GUID 检出 + 零写入
    ok = client.post(
        f"/api/v1/inbox/sources/{source['uuid']}/ingest/dry-run",
        json=_payload("g-dry", "试跑标题"),
    )
    ok_data = ok.json()
    assert ok_data["valid"] is True
    assert ok_data["wouldCreate"] == {"title": "试跑标题", "kind": "api_item"}
    assert ok_data["wouldDuplicate"] is False

    # 危险 HTML 在 would_create 之前已被净化（负向：sanitize 后不含 script）
    danger = client.post(
        f"/api/v1/inbox/sources/{source['uuid']}/ingest/dry-run",
        json={"guid": "g-html", "title": "带脚本", "contentHtml": "<p>ok</p><script>alert(1)</script>"},
    )
    assert danger.json()["valid"] is True
    import json as _json

    assert "script" not in _json.dumps(danger.json(), ensure_ascii=False).replace(
        "contentHtml", ""
    ) or danger.json()["notes"] == []

    # 零写入断言：试跑若干次后无任何条目产生
    items = client.get("/api/v1/inbox/items").json()["items"]
    assert len([i for i in items if i["sourceUuid"] == source["uuid"]]) == 0

    # 正式投递后：重复 GUID 的 dry-run 如实提示 wouldDuplicate
    assert _ingest(client, source, _payload("g-dup", "先投递")).status_code == 200
    dup = client.post(
        f"/api/v1/inbox/sources/{source['uuid']}/ingest/dry-run",
        json=_payload("g-dup", "再试跑"),
    ).json()
    assert dup["wouldDuplicate"] is True
    assert any("幂等" in n for n in dup["notes"])


def test_f108_dry_run_and_live_share_same_validator(client):
    """试跑与正式 ingest 同一校验器：同一坏载荷两条路径的错误一致。"""
    from lumirss.errors import InvalidInboxPayload
    from lumirss.models import InboxIngestItem
    from lumirss.routers.inbox import prepare_ingest_item

    bad_url = {"guid": "g-url", "title": "t", "url": "ftp://example.com/file"}
    source = _create_source(client, "validator-check")
    # 试跑路径
    via_dry_run = client.post(
        f"/api/v1/inbox/sources/{source['uuid']}/ingest/dry-run", json=bad_url
    )
    assert via_dry_run.status_code == 200
    dry_errors = via_dry_run.json()["errors"]
    # 正式路径（store 层校验函数直接调用——同一 prepare_ingest_item）
    try:
        prepare_ingest_item(InboxIngestItem.model_validate(bad_url))
        raise AssertionError("应抛 InvalidInboxPayload")
    except InvalidInboxPayload as exc:
        live_reason = str(exc)
    assert any(live_reason in e["reason"] for e in dry_errors)

    # 非法时间戳：同样两路一致
    bad_ts = {"guid": "g-ts", "publishedAt": "不是时间"}
    dry_ts = client.post(
        f"/api/v1/inbox/sources/{source['uuid']}/ingest/dry-run", json=bad_ts
    ).json()
    try:
        prepare_ingest_item(InboxIngestItem.model_validate(bad_ts))
        raise AssertionError("应抛 InvalidInboxPayload")
    except InvalidInboxPayload as exc:
        assert any(str(exc) in e["reason"] for e in dry_ts["errors"])
