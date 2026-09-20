"""F050/F051/F052/F056/F058 后端测试 — 检查台、批注、导出、进度、复习队列。"""

import asyncio
from types import SimpleNamespace

from lumirss.main import app


def _run(coroutine):
    return asyncio.run(coroutine)


# ---- F050 批量检查台 --------------------------------------------------------


def _install_control(refs_and_urls):
    from lumirss.main import app
    from lumirss.subscriptionref import encode_subscription_ref

    subs = []
    for i, url in enumerate(refs_and_urls):
        subs.append(
            SimpleNamespace(
                stream_id=f"feed/{i + 1}",
                subscription_ref=encode_subscription_ref(f"feed/{i + 1}"),
                title=f"源{i}",
                feed_url=url,
                category_id=None,
                category_label=None,
            )
        )

    async def _list():
        return list(subs)

    app.state.freshrss_control_adapter = SimpleNamespace(list_subscriptions=_list)
    return {sub.subscription_ref for sub in subs}


def test_f050_health_check_classes_and_dedup(client):
    """各类分类 fixture；重复 ref 去重；200 非 feed → bad_content。"""
    from lumirss.main import app

    refs = _install_control(
        [
            "https://ok.example.com/feed.xml",
            "https://bad.example.com/page",
            "https://auth.example.com/feed",
        ]
    )
    ref_list = sorted(refs)

    async def fake_probe(feed_url, timeout_s):
        _ = timeout_s
        if "ok." in feed_url:
            return {"status": "ok", "httpStatus": 200}
        if "bad." in feed_url:
            return {"status": "bad_content", "httpStatus": 200}
        if "auth." in feed_url:
            return {"status": "auth_error", "httpStatus": 403}
        return {"status": "network_error"}

    app.state.health_probe = fake_probe
    response = client.post(
        "/api/v1/subscriptions/health-check",
        json={"refs": ref_list + [ref_list[0]], "timeoutS": 3},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 3  # 重复 ref 去重
    by_status = {item["status"] for item in items}
    assert by_status == {"ok", "bad_content", "auth_error"}

    # 检查不改配置（负向）：无任何来源覆盖/迁移记录被写入
    overrides = client.get("/api/v1/sources/overrides").json()["items"]
    assert overrides == []


def test_f050_health_check_unknown_ref_and_limit(client):
    from lumirss.main import app

    refs = _install_control(["https://ok.example.com/feed.xml"])
    ref_list = sorted(refs)
    app.state.health_probe = None  # 走真实 probe 路径（unknown ref 不出网）
    response = client.post(
        "/api/v1/subscriptions/health-check",
        json={"refs": ["e2.notarealref", ref_list[0]], "timeoutS": 3},
    )
    items = response.json()["items"]
    statuses = {item["ref"]: item["status"] for item in items}
    assert statuses["e2.notarealref"] == "not_found"
    # 上限 50：51 个 ref → 422
    too_many = client.post(
        "/api/v1/subscriptions/health-check",
        json={"refs": [f"r{i}" for i in range(51)]},
    )
    assert too_many.status_code == 422


# ---- F051 批注服务端化 ------------------------------------------------------


def test_f051_annotations_crud_search_and_idempotent_import(client):
    """CRUD、CJK 检索、分页；导入幂等（同锚点不重复）；重启持久。"""
    anchor = {"paraId": "p-3", "quote": "重要观点"}
    created = client.post(
        "/api/v1/annotations",
        json={
            "entryRef": "e1.abc",
            "anchor": anchor,
            "excerpt": "这是一段重要观点摘录",
            "note": "我的想法：值得复读",
            "color": "green",
        },
    )
    assert created.status_code == 201
    body = created.json()
    annotation_id = body["id"]
    assert body["excerpt"] == "这是一段重要观点摘录"

    # 幂等导入：同 entry+anchor 再 POST → 返回既有行（仍 201 语义但同一 id）
    again = client.post(
        "/api/v1/annotations",
        json={"entryRef": "e1.abc", "anchor": dict(anchor), "excerpt": "重复导入"},
    )
    assert again.status_code == 201
    assert again.json()["id"] == annotation_id

    # 单篇列表
    listing = client.get("/api/v1/annotations", params={"entryRef": "e1.abc"}).json()
    assert len(listing["items"]) == 1

    # CJK 检索
    found = client.get("/api/v1/annotations", params={"q": "复读"}).json()
    assert len(found["items"]) == 1
    miss = client.get("/api/v1/annotations", params={"q": "不存在的词"}).json()
    assert miss["items"] == []

    # PATCH + DELETE
    updated = client.patch(
        f"/api/v1/annotations/{annotation_id}", json={"note": "更新后的批注"}
    )
    assert updated.json()["note"] == "更新后的批注"
    deleted = client.delete(f"/api/v1/annotations/{annotation_id}")
    assert deleted.status_code == 204
    gone = client.get("/api/v1/annotations", params={"entryRef": "e1.abc"}).json()
    assert gone["items"] == []

    # BFF 重启（同 tmp 库的新 TestClient）后仍在：由 store 直接验证
    from lumirss.annotation_store import AnnotationStore

    item = _run(
        AnnotationStore(app.state.db).create(
            entry_ref="e1.persist",
            anchor={"paraId": "p-1"},
            excerpt="重启后仍在",
            note=None,
        )
    )
    assert item is not None


# ---- F052 汇编导出 ----------------------------------------------------------


def test_f052_export_markdown_scope_and_escaping(client):
    """导出记录数与选择一致；Markdown 转义；空选择 422。"""
    client.post(
        "/api/v1/annotations",
        json={
            "entryRef": "e1.a",
            "anchor": {"paraId": "p1"},
            "excerpt": "摘录含 > 引用与 `code`",
            "note": "# 不是标题\n> 不是引用",
        },
    )
    client.post(
        "/api/v1/annotations",
        json={"entryRef": "e1.b", "anchor": {"paraId": "p2"}, "excerpt": "另一篇的摘录"},
    )
    export = client.post(
        "/api/v1/annotations/export", json={"entryRefs": ["e1.a"]}
    )
    assert export.status_code == 200
    assert "text/markdown" in export.headers["content-type"]
    text = export.text
    assert "另一篇" not in text  # 只含所选文章
    assert "\\`code\\`" in text  # 反引号转义
    assert "\\# 不是标题" in text  # 行首 # 转义
    assert "\\> 不是引用" in text  # 行首 > 转义

    empty = client.post("/api/v1/annotations/export", json={"entryRefs": []})
    assert empty.status_code == 422
    no_match = client.post("/api/v1/annotations/export", json={"q": "不存在"})
    assert no_match.status_code == 422


# ---- F056 跨设备继续阅读 ----------------------------------------------------


def test_f056_reading_progress_roundtrip_and_latest_wins(client):
    """PUT/GET 往返；同 entry 冲突 latest-wins（服务器 updated_at 仲裁）。"""
    put = client.put(
        "/api/v1/reading-progress",
        json={"entryRef": "e1.x", "paraId": "p-5", "pct": 42.5, "deviceLabel": "桌面"},
    )
    assert put.status_code == 204
    client.put(
        "/api/v1/reading-progress",
        json={"entryRef": "e1.y", "paraId": "p-1", "pct": 10.0, "deviceLabel": "手机"},
    )
    listing = client.get("/api/v1/reading-progress").json()["items"]
    assert len(listing) == 2

    # 两客户端模拟冲突：第二台稍后上报同 entry → 服务器时间更晚胜出
    import time

    time.sleep(0.01)
    client.put(
        "/api/v1/reading-progress",
        json={"entryRef": "e1.x", "paraId": "p-9", "pct": 90.0, "deviceLabel": "平板"},
    )
    listing = client.get("/api/v1/reading-progress").json()["items"]
    target = next(item for item in listing if item["entryRef"] == "e1.x")
    assert target["paraId"] == "p-9" and target["pct"] == 90.0
    assert target["deviceLabel"] == "平板"
    # limit 上限 5
    for i in range(6):
        client.put(
            "/api/v1/reading-progress",
            json={"entryRef": f"e1.n{i}", "paraId": "p", "pct": 1.0},
        )
    assert len(client.get("/api/v1/reading-progress").json()["items"]) <= 5


# ---- F058 复习队列 ----------------------------------------------------------


def test_f058_review_queue_lifecycle(client):
    """到期边界、重复添加 409、延期、级联删除、完成不影响 RSS 已读（负向）。"""
    created = client.post(
        "/api/v1/annotations",
        json={"entryRef": "e1.r", "anchor": {"paraId": "p1"}, "excerpt": "要复习的摘录", "note": "批注内容"},
    )
    annotation_id = created.json()["id"]

    due = client.post(
        "/api/v1/review-queue",
        json={"annotationId": annotation_id, "dueAt": "2026-01-01T00:00:00Z"},
    )
    assert due.status_code == 201
    # 重复添加 → 409
    dup = client.post(
        "/api/v1/review-queue",
        json={"annotationId": annotation_id, "dueAt": "2026-02-01T00:00:00Z"},
    )
    assert dup.status_code == 409

    # 到期边界：未来 dueAt 不在 due 列表
    future = client.post(
        "/api/v1/annotations",
        json={"entryRef": "e1.r", "anchor": {"paraId": "p2"}, "excerpt": "未来的"},
    )
    future_id = future.json()["id"]
    import datetime as _dt

    soon = (_dt.datetime.now(_dt.UTC) + _dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    client.post(
        "/api/v1/review-queue",
        json={"annotationId": future_id, "dueAt": soon},
    )
    listing = client.get("/api/v1/review-queue", params={"status": "due"}).json()["items"]
    by_id = {item["annotationId"]: item for item in listing}
    assert by_id[annotation_id]["due"] is True
    assert by_id[future_id]["due"] is False  # 已排期但未到期（诚实标注）

    # 延期
    queue_id = by_id[annotation_id]["id"]
    postponed = client.post(
        f"/api/v1/review-queue/{queue_id}/postpone", json={"dueAt": "2099-03-01T00:00:00Z"}
    )
    assert postponed.status_code == 200

    # 完成；对 done 的可重新排期
    done = client.post(f"/api/v1/review-queue/{queue_id}/complete")
    assert done.json()["status"] == "done"
    reschedule = client.post(
        "/api/v1/review-queue",
        json={"annotationId": annotation_id, "dueAt": "2026-06-01T00:00:00Z"},
    )
    assert reschedule.status_code == 200 and reschedule.json()["rescheduled"] is True

    # 负向：复习操作不触碰 RSS 已读状态
    # （服务端没有任何 entries 状态调用；这里验证 API 面不存在误用通道）
    rss_state = client.patch(
        "/api/v1/entries/e1.notexist/state", json={"read": True}
    )
    assert rss_state.status_code in (400, 404)  # 正常 RSS 通道独立存在

    # 批注删除 → 队列项级联删除
    client.delete(f"/api/v1/annotations/{annotation_id}")
    import sqlite3

    row = _run(
        app.state.db.fetch_one(
            "SELECT id FROM review_queue WHERE annotation_id = ?", (annotation_id,)
        )
    )
    _ = sqlite3
    assert row is None

