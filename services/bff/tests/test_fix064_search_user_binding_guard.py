"""FIX-064 守卫：搜索索引查询与增量构建的用户绑定基线。

架构事实（0067 + O163 + N193 + FIX-217）：
- 查询路径：GET /api/v1/search 的 SearchIndexService 由
  _cached_on_app_state 按（已验证 uid, attr）缓存，SearchStore 全部
  SQL 落在 RoutingDatabase 路由出的 per-user 库；
- 增量构建路径：后台 search_sync_loop 只遍历 active_user_ids
  （status=active 且未被 background_paused），for_each_active_user 在
  进入用户上下文前即时复读生命周期，user_freshrss_adapter 只用该用户
  自己的 freshrss_binding + secrets，未绑定 → None（诚实跳过）。

本文件用 A/B 账户钉住两条硬证据（BASELINE_OK）：
1. A 的投影文档对 B 的搜索不可见（查询绑定）；
2. 增量构建的 FreshRSS 适配器按用户绑定——未绑定用户 None（跳过），
   A/B 各自拿到自己 base_url 的适配器（不共享凭据）。
"""

import asyncio
import secrets

import pytest

from new231_helpers import ab_session


def _run(coro):
    return asyncio.run(coro)


def _session_user_id(client, headers: dict[str, str]) -> str:
    probe = client.get("/api/v1/auth/session", headers=headers)
    assert probe.status_code == 200, probe.text
    return str(probe.json()["userId"])


def test_fix064_search_query_bound_to_requesting_user(monkeypatch, tmp_path):
    """A 投影里的文档只被 A 搜到；B 同词搜索看不到 A 的文档。"""
    with ab_session(monkeypatch, tmp_path) as session:
        client = session.client
        app = client.app
        alice = session.activate_member("fx064a")
        bob = session.activate_member("fx064b")
        alice_uid = _session_user_id(client, alice)
        bob_uid = _session_user_id(client, bob)

        marker = f"fx064needle-{secrets.token_hex(4)}"
        title_a = f"A 的私有条目 {marker}"

        from lumirss.search_writer import SearchEntryWriter
        from lumirss.user_scope import user_context

        def _seed(uid: str, title: str) -> None:
            async def _inner() -> None:
                writer = SearchEntryWriter(app.state.db)
                await app.state.db.migrate()
                await writer.insert_entry(
                    item_id=f"tag:freshrss.example,{uid}:entry-1",
                    entry_ref=f"e{uid}0001",
                    feed_url="https://feed.example/a.xml",
                    feed_title="A 的订阅源",
                    title=title,
                    author="author-a",
                    url="https://feed.example/a/1",
                    content_text=f"{marker} 正文内容",
                    published_at="2026-01-01T00:00:00Z",
                    read=0,
                    starred=0,
                    fetched_at=1,
                )

            with user_context(uid):
                _run(_inner())

        _seed(alice_uid, title_a)
        _seed(bob_uid, f"B 自己的条目 {secrets.token_hex(4)}")

        seen_a = client.get("/api/v1/search", params={"q": marker}, headers=alice)
        assert seen_a.status_code == 200, seen_a.text
        titles_a = [str(item.get("title") or "") for item in seen_a.json()["items"]]
        assert any(marker in t for t in titles_a), titles_a

        seen_b = client.get("/api/v1/search", params={"q": marker}, headers=bob)
        assert seen_b.status_code == 200, seen_b.text
        titles_b = [str(item.get("title") or "") for item in seen_b.json()["items"]]
        assert not any(marker in t for t in titles_b), titles_b

        owner_seen = client.get(
            "/api/v1/search", params={"q": marker}, headers=session.owner
        )
        assert owner_seen.status_code == 200
        titles_owner = [str(item.get("title") or "") for item in owner_seen.json()["items"]]
        assert not any(marker in t for t in titles_owner), titles_owner


def test_fix064_incremental_adapter_bound_per_user(monkeypatch, tmp_path):
    """增量构建的 FreshRSS 适配器：未绑定 → None；A/B 各用各的绑定。"""
    with ab_session(monkeypatch, tmp_path) as session:
        client = session.client
        app = client.app
        alice = session.activate_member("fx064ca")
        bob = session.activate_member("fx064cb")
        alice_uid = _session_user_id(client, alice)
        bob_uid = _session_user_id(client, bob)

        from lumirss.control_resources import (
            bind_freshrss_account,
            user_freshrss_adapter,
        )

        # 未绑定用户：诚实 None（后台增量跳过，绝不借用共享凭据）。
        assert _run(user_freshrss_adapter(app.state, bob_uid)) is None

        app.state.control_secrets.set(
            "freshrss_pool:alice-fr", "x" * 24
        )
        app.state.control_secrets.set(
            "freshrss_pool:bob-fr", "y" * 24
        )
        _run(
            bind_freshrss_account(
                app.state, alice_uid, "alice-fr", "https://freshrss-a.example"
            )
        )
        _run(
            bind_freshrss_account(
                app.state, bob_uid, "bob-fr", "https://freshrss-b.example"
            )
        )

        adapter_a = _run(user_freshrss_adapter(app.state, alice_uid))
        adapter_b = _run(user_freshrss_adapter(app.state, bob_uid))
        assert adapter_a is not None and adapter_b is not None
        assert (
            adapter_a._base_url == "https://freshrss-a.example"
        )
        assert (
            adapter_b._base_url == "https://freshrss-b.example"
        )
        assert (
            adapter_a._api_password.get_secret_value() == "x" * 24
        )
        assert (
            adapter_b._api_password.get_secret_value() == "y" * 24
        )


_ = pytest  # imported for parity with sibling suites; no direct use
