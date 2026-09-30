"""NEW-341 个人数据访问记录 — 记录范围/边界说明/公开 feed 留痕 +
A/B 隔离。（零真实网络；复用 new2xx_ab 的 A/B 会话夹具）"""

import asyncio

from lumirss.new341_access_log import list_access_events
from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new341_empty_log_states_boundaries(ab_env):  # noqa: F811
    """空记录也如实返回记录范围与「无法记录」边界（不冒充有日志）。"""
    client = ab_env["client"]
    response = client.get("/api/v1/privacy/access-log", headers=ab_env["a"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["items"] == []
    assert "token" in payload["recordedScope"]
    joined = " ".join(payload["unrecorded"])
    assert "FreshRSS" in joined
    assert "不经过 Lumi" in joined
    assert "绝不记录访问者 IP" in joined
    assert any("同一 404" in note for note in payload["unrecorded"])


def test_new341_briefing_feed_access_recorded_and_isolated(ab_env):  # noqa: F811
    """A 启用简报 feed → 外部拉取成功 → A 的日志出现 briefing_feed
    事件；B 的日志没有 A 的事件（per-user 隔离）。"""
    client = ab_env["client"]
    enabled = client.post("/api/v1/briefings/feed/enable", headers=ab_env["a"])
    assert enabled.status_code == 200, enabled.text
    token = enabled.json()["token"]

    fetched = client.get(f"/feeds/briefings/{token}.atom")
    assert fetched.status_code == 200, fetched.text

    a_log = client.get("/api/v1/privacy/access-log", headers=ab_env["a"]).json()
    assert any(item["purpose"] == "briefing_feed" for item in a_log["items"])
    assert any(item["purposeLabel"] == "个人简报 RSS 订阅" for item in a_log["items"])

    b_log = client.get("/api/v1/privacy/access-log", headers=ab_env["b"]).json()
    assert b_log["items"] == []

    # 错 token → 404 不泄露存在性，也不留痕。
    missing = client.get("/feeds/briefings/deadbeefdead.atom")
    assert missing.status_code == 404
    a_log2 = client.get("/api/v1/privacy/access-log", headers=ab_env["a"]).json()
    assert len(a_log2["items"]) == len(a_log["items"])


def test_new341_limit_is_bounded(ab_env):  # noqa: F811
    client = ab_env["client"]
    response = client.get(
        "/api/v1/privacy/access-log?limit=99999", headers=ab_env["a"]
    )
    assert response.status_code == 200


def test_new341_list_events_pure_shape(tmp_path):
    """模块层：purposeLabel 映射与未知 purpose 兜底。"""

    async def run():
        from lumirss.new341_access_log import record_access_event
        from lumirss.storage import Database

        # FIX-386：per-test tmp_path，禁止固定 /tmp 路径（多 worktree
        # 并行 pytest 会读写同一文件 → 串数据/锁冲突）。
        db = Database(tmp_path / "lumi.sqlite")
        await record_access_event(db, "share_link", "链接 演示")
        await record_access_event(db, "unknown_purpose", "x")
        return await list_access_events(db, 10)

    payload = asyncio.run(run())
    labels = {item["purpose"]: item["purposeLabel"] for item in payload["items"]}
    assert labels["share_link"] == "个人共享链接"
    assert labels["unknown_purpose"] == "unknown_purpose"
