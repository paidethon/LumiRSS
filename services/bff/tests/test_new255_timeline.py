"""NEW-255 事件时间线编辑器 — 事件发生时间 vs 报道时间。

- event_at 按用户掌握的精度原文登记（「1997 年」合法，不改写）；
- reported_at 可选；两侧都能解析 YYYY-MM-DD 前缀才算 reportedDaysAfter，
  解析不了诚实返回 null（不猜时间差）；列表给 unparseableCount；
- 隔离：A 的事件对 B 404。
"""

from fastapi.testclient import TestClient

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient) -> dict:
    return client.post(
        "/api/v1/research/projects", json={"title": "时间线项目"}
    ).json()


def test_new255_event_create_gap_and_fuzzy(client):  # noqa: F811
    """可解析对 → 天数差；模糊 eventAt → unparseable 且不猜差值。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/timeline"

    precise = client.post(
        base,
        json={
            "title": "水厂投产",
            "eventAt": "1997-03-15",
            "reportedAt": "1997-03-20",
            "itemRef": f"rss:{encode_entry_ref('n255-a')}",
        },
    )
    assert precise.status_code == 201, precise.text
    body = precise.json()
    assert body["eventDateParsed"] == "1997-03-15"
    assert body["reportedDateParsed"] == "1997-03-20"
    assert body["reportedDaysAfter"] == 5

    fuzzy = client.post(
        base,
        json={"title": "改造启动（约）", "eventAt": "约 2003 年春", "reportedAt": "2003-04-01"},
    )
    assert fuzzy.status_code == 201, fuzzy.text
    fuzzy_body = fuzzy.json()
    assert fuzzy_body["eventDateParsed"] is None
    assert fuzzy_body["reportedDaysAfter"] is None  # 不猜

    listed = client.get(base).json()
    assert listed["unparseableCount"] == 1
    assert len(listed["items"]) == 2

    # PATCH：把模糊时间补成可解析 → 差值出现。
    patched = client.patch(
        f"/api/v1/research/timeline-events/{fuzzy_body['id']}",
        json={"eventAt": "2003-03-28", "note": "依据县志补齐"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["reportedDaysAfter"] == 4

    assert (
        client.delete(
            f"/api/v1/research/timeline-events/{body['id']}"
        ).status_code
        == 204
    )


def test_new255_validation_and_errors(client):  # noqa: F811
    """空标题/空 eventAt → 422；坏 itemRef → 422；未知事件 → 404。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/timeline"

    assert client.post(base, json={"title": " ", "eventAt": "2000-01-01"}).status_code == 422
    assert client.post(base, json={"title": "T", "eventAt": ""}).status_code == 422
    assert (
        client.post(
            base,
            json={"title": "T", "eventAt": "2000-01-01", "itemRef": "nope"},
        ).status_code
        == 422
    )
    event = client.post(base, json={"title": "T", "eventAt": "2000-01-01"}).json()
    assert (
        client.patch(
            "/api/v1/research/timeline-events/missing-event",
            json={"note": "x"},
        ).status_code
        == 404
    )
    assert event["reportedDaysAfter"] is None  # 无 reportedAt 不算差值


def test_new255_ab_isolation(ab_env):  # noqa: F811
    """A 登记的事件对 B 不可见；A 的时间修正不影响 B。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 时间线"}, headers=ab_env["a"]
    ).json()
    event_id = client.post(
        f"/api/v1/research/projects/{project['id']}/timeline",
        json={"title": "A 的事件", "eventAt": "2001-02-03"},
        headers=ab_env["a"],
    ).json()["id"]

    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/timeline",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/research/timeline-events/{event_id}",
            json={"eventAt": "1999-01-01"},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
