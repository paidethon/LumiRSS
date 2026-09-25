"""E1: N039 附件失效检测 + N045 阅读中断便签（服务端）。

- N039：上报（≤20/次）→ (kind, src) 幂等 upsert（重复上报只刷新
  lastSeenAt/hitCount，绝不翻倍）；GET 列表；纯记录——服务端没有任何
  重试路径，src 原样保存；
- N045：便签 PUT（latest-wins）/ GET / DELETE；≤200 字符；
  paraId 段落锚点随行保存与回读。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


def test_n039_media_failure_upsert_idempotent_and_listed(client):
    app = client.app
    run(app.state.db.migrate())
    ref = encode_entry_ref("m1")
    payload = {"failures": [{"kind": "image", "src": "https://img.example/a.png"}]}

    first = client.post(f"/api/v1/entries/{ref}/media-failures", json=payload)
    assert first.status_code == 200, first.text
    assert len(first.json()["failures"]) == 1
    first_seen = first.json()["failures"][0]["firstSeenAt"]

    second = client.post(f"/api/v1/entries/{ref}/media-failures", json=payload)
    assert second.status_code == 200
    rows = second.json()["failures"]
    assert len(rows) == 1  # upsert：绝不翻倍
    assert rows[0]["hitCount"] == 2  # 命中计数 +1
    assert rows[0]["firstSeenAt"] == first_seen  # 首次上报时间恒定

    listed = client.get(f"/api/v1/entries/{ref}/media-failures")
    assert listed.status_code == 200
    assert listed.json()["failures"][0]["src"] == "https://img.example/a.png"


def test_n039_media_failure_bounded_request_and_entry_cap(client):
    app = client.app
    run(app.state.db.migrate())
    ref = encode_entry_ref("m2")
    # 单次 >20 → 422。
    too_many = {
        "failures": [
            {"kind": "other", "src": f"https://img.example/{i}"} for i in range(21)
        ]
    }
    assert (
        client.post(f"/api/v1/entries/{ref}/media-failures", json=too_many).status_code
        == 422
    )
    # 每条目 50 行上限：塞 60 个不同 src → 只保留最近 50。
    for chunk_start in range(0, 60, 20):
        payload = {
            "failures": [
                {"kind": "image", "src": f"https://img.example/{i}"}
                for i in range(chunk_start, chunk_start + 20)
            ]
        }
        response = client.post(f"/api/v1/entries/{ref}/media-failures", json=payload)
        assert response.status_code == 200
    rows = client.get(f"/api/v1/entries/{ref}/media-failures").json()["failures"]
    assert len(rows) == 50
    # 最旧的（编号最小的 src）被裁掉。
    srcs = {row["src"] for row in rows}
    assert "https://img.example/0" not in srcs
    assert "https://img.example/59" in srcs


def test_n039_media_failure_invalid_ref_and_kind(client):
    run(client.app.state.db.migrate())
    assert (
        client.get("/api/v1/entries/not-a-ref/media-failures").status_code == 400
    )
    bad_kind = client.post(
        f"/api/v1/entries/{encode_entry_ref('m3')}/media-failures",
        json={"failures": [{"kind": "video", "src": "https://x"}]},
    )
    assert bad_kind.status_code == 422


def test_n045_reading_note_crud_and_latest_wins(client):
    app = client.app
    run(app.state.db.migrate())
    ref = encode_entry_ref("n1")

    # GET 无便签 → 404 reading_note_not_found。
    missing = client.get(f"/api/v1/entries/{ref}/note")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "reading_note_not_found"

    put = client.put(
        f"/api/v1/entries/{ref}/note",
        json={"note": "看到第三章", "paraId": "p-3"},
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["note"] == "看到第三章"
    assert body["paraId"] == "p-3"

    # latest-wins：再次 PUT 恒覆盖（含清空 paraId）。
    client.put(f"/api/v1/entries/{ref}/note", json={"note": "看到第五章"})
    fetched = client.get(f"/api/v1/entries/{ref}/note").json()
    assert fetched["note"] == "看到第五章"
    assert fetched["paraId"] is None

    deleted = client.delete(f"/api/v1/entries/{ref}/note")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/entries/{ref}/note").status_code == 404
    # 幂等删除。
    assert client.delete(f"/api/v1/entries/{ref}/note").status_code == 204


def test_n045_reading_note_bounds(client):
    run(client.app.state.db.migrate())
    ref = encode_entry_ref("n2")
    too_long = client.put(
        f"/api/v1/entries/{ref}/note", json={"note": "字" * 201}
    )
    assert too_long.status_code == 422
    empty = client.put(f"/api/v1/entries/{ref}/note", json={"note": "   "})
    assert empty.status_code == 422
