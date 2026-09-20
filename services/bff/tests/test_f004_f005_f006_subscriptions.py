"""F004 重复订阅检查器 / F005 来源备注 / F006 批量分类迁移。"""

import asyncio
from types import SimpleNamespace

from lumirss.main import app
from lumirss.source_notes import SourceNotesStore
from lumirss.subscriptionref import encode_subscription_ref


def run(coroutine):
    return asyncio.run(coroutine)


# --- F004 ------------------------------------------------------------------


def _install_subscriptions(rows: list[tuple[str, str]]) -> dict[str, str]:
    """(title, feed_url) → 订阅假件；返回 feed_url → ref 映射。"""
    subs = []
    ref_of = {}
    for i, (title, url) in enumerate(rows):
        ref = encode_subscription_ref(f"feed/{i + 1}")
        ref_of[url] = ref
        subs.append(
            SimpleNamespace(
                stream_id=f"feed/{i + 1}",
                subscription_ref=ref,
                title=title,
                feed_url=url,
                category_label=None,
            )
        )

    async def _list_subs():
        return list(subs)

    app.state.freshrss_control_adapter = SimpleNamespace(list_subscriptions=_list_subs)
    return ref_of


def test_f004_same_url_and_query_param_diff_merge(client):
    _install_subscriptions(
        [
            ("源 A", "https://example.com/feed?utm_source=x"),
            ("源 A2", "https://EXAMPLE.com/feed/"),
            ("源 B", "https://other.example/feed"),
        ]
    )
    body = client.get("/api/v1/subscriptions/duplicate-suspects").json()
    assert len(body["groups"]) == 1, "同 URL（大小写/尾斜杠/追踪参数差异）合并"
    members = {m["feedUrl"] for m in body["groups"][0]["members"]}
    assert members == {"https://example.com/feed?utm_source=x", "https://EXAMPLE.com/feed/"}
    assert body["groups"][0]["key"].startswith("example.com/feed")
    assert "utm_source" not in body["groups"][0]["key"]
    assert body["checked"] == 3


def test_f004_same_site_different_path_not_merged_and_signature_kept(client):
    _install_subscriptions(
        [
            ("列表页", "https://example.com/list"),
            ("文章页", "https://example.com/article/1"),
            ("带签名", "https://example.com/list?token=secret"),
        ]
    )
    body = client.get("/api/v1/subscriptions/duplicate-suspects").json()
    assert body["groups"] == [], "路径不同/带签名参数不合并（保守）"


def test_f004_empty_result_when_no_duplicates(client):
    _install_subscriptions(
        [
            ("甲", "https://a.example/feed"),
            ("乙", "https://b.example/feed"),
        ]
    )
    body = client.get("/api/v1/subscriptions/duplicate-suspects").json()
    assert body["groups"] == []
    assert body["checked"] == 2


# --- F005 ------------------------------------------------------------------


REF = "s1.ZmVlZC85"


def test_f005_notes_crud_clear_persist_and_search(client):
    store = SourceNotesStore(app.state.db)
    # 初次读取 → 全 null（无行）
    got = client.get(f"/api/v1/subscriptions/{REF}/notes").json()
    assert got["note"] is None and got["subscriptionRef"] == REF
    # PATCH 写入（部分字段）
    patched = client.patch(
        f"/api/v1/subscriptions/{REF}/notes",
        json={"note": "<script>alert(1)</script> 原文存储", "reason": "重读价值高"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["note"].startswith("<script>"), "存原文（渲染转义是 Web 层职责）"
    assert body["reason"] == "重读价值高"
    assert body["maintenanceLog"] is None
    # sentinel：缺席字段不动
    again = client.patch(
        f"/api/v1/subscriptions/{REF}/notes", json={"maintenanceLog": "2026-09-19 更新地址"}
    ).json()
    assert again["note"].startswith("<script>")
    assert again["maintenanceLog"] == "2026-09-19 更新地址"
    # 清空（null 语义）
    cleared = client.patch(
        f"/api/v1/subscriptions/{REF}/notes", json={"note": None}
    ).json()
    assert cleared["note"] is None
    assert cleared["reason"] == "重读价值高"
    # 列表 + note_search（后端过滤）
    run(store.update_notes("s1.other", note="RSSHub 路由"))
    listing = client.get("/api/v1/subscriptions/notes").json()
    assert len(listing["items"]) == 2
    filtered = client.get("/api/v1/subscriptions/notes?note_search=RSSHub").json()
    assert [i["subscriptionRef"] for i in filtered["items"]] == ["s1.other"]
    # 重启（新 store 实例）后仍在
    fresh = SourceNotesStore(app.state.db)
    assert run(fresh.get_notes("s1.other"))["note"] == "RSSHub 路由"


def test_f005_cascade_delete_no_orphans(client):
    store = SourceNotesStore(app.state.db)
    ref = encode_subscription_ref("feed/77")
    run(store.update_notes(ref, note="将被级联删除"))

    async def _unsubscribe(stream_id):
        return None

    app.state.freshrss_control_adapter = SimpleNamespace(unsubscribe=_unsubscribe)
    response = client.delete(f"/api/v1/subscriptions/{ref}")
    assert response.status_code == 204
    remaining = run(store.search_notes())
    assert all(item["subscriptionRef"] != ref for item in remaining), "无孤儿行"


# --- F006 ------------------------------------------------------------------


def _install_move_adapter(move_results: dict[str, Exception | None]):
    calls: list[tuple[str, str]] = []

    async def _move_category(stream_id, category_id):
        calls.append((stream_id, category_id))
        exc = move_results.get(stream_id)
        if exc is not None:
            raise exc

    app.state.freshrss_control_adapter = SimpleNamespace(move_category=_move_category)
    return calls


def test_f006_batch_move_partial_failure_and_idempotent(client):
    from lumirss.adapters.freshrss_control import CategoryNotFound

    ref_ok = encode_subscription_ref("feed/1")
    ref_bad = encode_subscription_ref("feed/2")
    calls = _install_move_adapter({"feed/2": CategoryNotFound("nope")})
    body = client.post(
        "/api/v1/subscriptions/batch-move",
        json={"refs": [ref_ok, ref_bad, ref_ok], "targetCategoryId": "user/-/label/科技"},
    )
    assert body.status_code == 200, body.text
    payload = body.json()
    assert payload["moved"] == 1
    items = {i["ref"]: i for i in payload["items"]}
    assert items[ref_ok]["ok"] is True
    assert items[ref_bad]["ok"] is False
    assert items[ref_bad]["error"] == "category_not_found"
    # 成功项不重复执行（重复 ref 只移动一次）
    assert calls.count(("feed/1", "user/-/label/科技")) == 1
    # 再次提交同一批 = 幂等（重复执行移动是 no-op 语义）
    again = client.post(
        "/api/v1/subscriptions/batch-move",
        json={"refs": [ref_ok], "targetCategoryId": "user/-/label/科技"},
    )
    assert again.status_code == 200
    assert again.json()["moved"] == 1


def test_f006_batch_move_invalid_ref_reported_per_item(client):
    calls = _install_move_adapter({})
    body = client.post(
        "/api/v1/subscriptions/batch-move",
        json={"refs": ["not-a-ref"], "targetCategoryId": "user/-/label/科技"},
    )
    assert body.status_code == 200
    items = body.json()["items"]
    assert items[0]["ok"] is False
    assert items[0]["error"] == "invalid_ref"
    assert calls == []
    # 空数组 / 空 target → 422
    empty = client.post(
        "/api/v1/subscriptions/batch-move",
        json={"refs": [], "targetCategoryId": "user/-/label/科技"},
    )
    assert empty.status_code == 422
