"""N111 目标卡扩展 + N112 材料状态扩展 —— 正负向（规格逐条）。

N111：workspace_goals 增加自由文本目标陈述（goal_text）+ 完成条件清单
（conditions_json，显示+本机勾选，绝不存勾选状态）；API update 接受；
update+fetch 往返一致；旧调用方（不带新键）绝不无意清空。
N112：看板状态枚举扩展（excerpted 待摘录 / needs_verification 待验证）；
逐状态设置持久化；非法状态 422；FreshRSS read/star 独立（负向断言）。
"""

import asyncio
import sqlite3

import pytest

from lumirss.entryref import encode_entry_ref
from lumirss.main import app

BOARD_STATUSES = ("todo", "reading", "excerpted", "needs_verification", "done")


def run(coro):
    return asyncio.run(coro)


class _RecordingAdapter:
    """只读 FreshRSS 替身：记录 get_entry 调用次数（看板写绝不该调用）。"""

    def __init__(self, entries: dict) -> None:
        self._entries = entries
        self.get_entry_calls = 0

    async def get_entry(self, item_id: str):
        self.get_entry_calls += 1
        entry = self._entries.get(item_id)
        if entry is None:
            from lumirss.adapters.freshrss import EntryNotFound

            raise EntryNotFound(item_id)
        return entry


def _entry_detail(item_id: str, title: str):
    from lumirss.models import EntryDetail

    return EntryDetail(
        entryRef=encode_entry_ref(item_id),
        title=title,
        feedTitle="测试源",
        url=f"https://example.com/{item_id}",
        publishedAt="2026-09-01T00:00:00+00:00",
        read=False,
        starred=False,
        contentText=f"{title} 的正文文本。",
        contentHtml=None,
    )


@pytest.fixture()
def rss_world(client):
    """投影行 + 只读适配器替身；返回 (ref, adapter)。"""
    entry_ref = encode_entry_ref("9001")
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url,"
            " feed_title, title, author, url, content_text, published_at, read,"
            " starred, fetched_at) VALUES ('9001', ?, 'https://f.example/rss',"
            " '源', '标题9001', '', 'u', '正文9001', '2026-09-01T00:00:00+00:00',"
            " 0, 0, 0)",
            (entry_ref,),
        )
    )
    adapter = _RecordingAdapter({"9001": _entry_detail("9001", "标题9001")})
    app.state.freshrss_adapter = adapter
    yield f"rss:{entry_ref}", adapter
    app.state.freshrss_adapter = None


def _mk_ws(client, name):
    ws = client.post("/api/v1/workspaces", json={"name": name}).json()["id"]
    bm = client.post(
        "/api/v1/library/bookmarks",
        json={"url": f"https://{name}.example/1", "title": name},
    ).json()["ref"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": bm})
    return ws, bm


# ===== N111 目标卡扩展 ========================================================


def test_n111_goal_text_conditions_roundtrip(client):
    ws, _bm = _mk_ws(client, "n111-ws")
    put = client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={
            "targetCount": 3,
            "deadline": "2026-12-31",
            "goalText": "读完三篇 LLM 推理优化的文章",
            "conditions": ["能说出 KV cache 的作用", "写一篇摘要"],
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["goalText"] == "读完三篇 LLM 推理优化的文章"
    assert body["conditions"] == ["能说出 KV cache 的作用", "写一篇摘要"]

    fetched = client.get(f"/api/v1/workspaces/{ws}/goal").json()
    assert fetched["goalText"] == body["goalText"]
    assert fetched["conditions"] == body["conditions"]
    assert fetched["targetCount"] == 3
    # update+fetch 往返：改条件后再取仍一致
    put2 = client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={"targetCount": 3, "goalText": "新陈述", "conditions": ["条件A"]},
    )
    assert put2.status_code == 200
    fetched2 = client.get(f"/api/v1/workspaces/{ws}/goal").json()
    assert fetched2["goalText"] == "新陈述"
    assert fetched2["conditions"] == ["条件A"]
    assert fetched2["deadline"] is None  # 未带 deadline = 清除（原有语义）


def test_n111_put_without_new_keys_preserves(client):
    """旧调用方只 PUT targetCount/deadline → goalText/conditions 保留。"""
    ws, _bm = _mk_ws(client, "n111-keep")
    client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={"targetCount": 2, "goalText": "陈述", "conditions": ["甲", "乙"]},
    )
    old_caller = client.put(
        f"/api/v1/workspaces/{ws}/goal", json={"targetCount": 5}
    )
    assert old_caller.status_code == 200
    body = old_caller.json()
    assert body["targetCount"] == 5
    assert body["goalText"] == "陈述"
    assert body["conditions"] == ["甲", "乙"]


def test_n111_explicit_clear(client):
    ws, _bm = _mk_ws(client, "n111-clear")
    client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={"targetCount": 1, "goalText": "陈述", "conditions": ["条件"]},
    )
    cleared = client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={"targetCount": 1, "goalText": "", "conditions": []},
    )
    assert cleared.status_code == 200
    body = cleared.json()
    assert body["goalText"] is None
    assert body["conditions"] == []


def test_n111_conditions_validation(client):
    ws, _bm = _mk_ws(client, "n111-bad")
    too_many = client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={"targetCount": 1, "conditions": [f"条件{i}" for i in range(21)]},
    )
    assert too_many.status_code in (400, 422)  # 20 上限（pydantic max_length）
    too_long = client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={"targetCount": 1, "conditions": ["x" * 201]},
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["type"] == "invalid_goal"
    # 空白条件被归一掉；重复条件去重
    normalized = client.put(
        f"/api/v1/workspaces/{ws}/goal",
        json={"targetCount": 1, "conditions": ["  甲 ", "甲", ""]},
    )
    assert normalized.status_code == 200
    assert normalized.json()["conditions"] == ["甲"]


# ===== N112 材料状态扩展 ======================================================


def test_n112_board_all_five_statuses(client):
    ws, bm = _mk_ws(client, "n112-ws")
    for status in BOARD_STATUSES:
        moved = client.put(
            f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": status}
        )
        assert moved.status_code == 200, moved.text
        board = client.get(f"/api/v1/workspaces/{ws}/board").json()
        assert len(board["columns"]) == 5
        column = next(c for c in board["columns"] if c["status"] == status)
        assert column["total"] == 1 and column["items"][0]["itemRef"] == bm
        assert all(
            c["total"] == 0 for c in board["columns"] if c["status"] != status
        )


def test_n112_invalid_status_rejected_422(client):
    ws, bm = _mk_ws(client, "n112-bad")
    bad = client.put(
        f"/api/v1/workspaces/{ws}/board", json={"itemRef": bm, "status": "blocked"}
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_board_status"


def test_n112_read_state_independent(client, rss_world):
    """看板状态（含新状态）绝不触碰 FreshRSS read/star（负向）。"""
    ref, adapter = rss_world
    ws = client.post("/api/v1/workspaces", json={"name": "n112-rss"}).json()["id"]
    client.post(f"/api/v1/workspaces/{ws}/items", json={"itemRef": ref})
    calls_before = adapter.get_entry_calls
    for status in ("excerpted", "needs_verification", "done"):
        moved = client.put(
            f"/api/v1/workspaces/{ws}/board", json={"itemRef": ref, "status": status}
        )
        assert moved.status_code == 200
    row = run(
        app.state.db.fetch_one(
            "SELECT read, starred FROM search_entries WHERE entry_ref = ?",
            (ref.removeprefix("rss:"),),
        )
    )
    assert row["read"] == 0 and row["starred"] == 0
    # 看板写路径不解析上游：调用计数不变（成员加入时的那次除外）。
    assert adapter.get_entry_calls == calls_before


def test_n112_migration_check_constraint_enforced(client):
    """0098 重建后的 CHECK 拒绝枚举外的状态（直接 SQL 负向）。"""
    ws, bm = _mk_ws(client, "n112-check")

    def _try():
        conn = sqlite3.connect(f"{app.state.db.path}")
        try:
            conn.execute(
                "INSERT INTO workspace_item_status (workspace_id, item_ref, status, updated_at) VALUES (?, ?, 'archived', 'now')",
                (ws, bm),
            )
        finally:
            conn.close()

    with pytest.raises(sqlite3.IntegrityError):
        _try()
