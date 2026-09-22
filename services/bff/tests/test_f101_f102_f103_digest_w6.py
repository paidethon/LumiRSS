"""F101/F102/F103 —— W6 日报域。

F101 近期材料去重（lookback 窗口、草稿不算已用、放回、预览==生成）；
F102 手工候选素材池（重复 409、失效跳过、发布消费、多配置隔离、
AI 禁用拒绝）；F103 订阅凭据轮换 dry-run（零变更 / 确认后旧 404 新可读 /
幂等 / 未登录 401 负向）。全部走 mock provider，不触网。
"""

import asyncio
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from lumirss.gpt_digest import (
    build_preview,
    generate_issue,
    recent_used_keys,
    select_material_for_config,
)
from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.gpt_digest_pool import (
    DigestMaterialPoolStore,
)
from lumirss.gpt_digest_store import GptDigestStore


def run(coroutine):
    return asyncio.run(coroutine)


class _FakeEntryDetail:
    def __init__(self, entry_ref, title, url):
        self.entryRef = entry_ref
        self.title = title
        self.url = url
        self.feedTitle = "手工源"
        self.publishedAt = "2026-09-01T00:00:00Z"
        self.read = False
        self.starred = False
        self.contentText = "手工条目正文"


class _FakeAdapter:
    """既支持窗口文档，又支持 get_entry（素材池解析）。"""

    def __init__(self, docs, details=None):
        self._docs = docs
        self._details = details or {}

    class _Page:
        def __init__(self, docs):
            self.documents = docs

    async def list_entry_documents(self, limit=120):
        return _FakeAdapter._Page(self._docs)

    async def get_entry(self, item_id):
        if item_id in self._details:
            return self._details[item_id]
        raise KeyError(item_id)


class _FakeAiSettings:
    async def load(self):
        return {"ai.base_url": "https://api.example.com/v1", "ai.model": "m"}


class _CapturingProvider:
    """记录 build_messages 的材料（用于 preview==生成 断言）。"""

    def __init__(self):
        self.material_titles = []

    async def complete(self, *, messages):
        self.material_titles.append(messages[1])
        return json.dumps(
            {
                "title": "日报",
                "sections": [
                    {"heading": "要点", "items": [{"summary": "内容", "sourceIds": ["s1"]}]}
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )


def _ok_factory(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


def _doc(item_id, published, url=None, feed_url="https://tech.example.com/rss"):
    return {
        "item_id": item_id,
        "entryRef": item_id,
        "title": f"标题{item_id}",
        "url": url or f"https://example.com/{item_id}",
        "publishedAt": published,
        "contentText": "正文",
        "feedUrl": feed_url,
        "feedTitle": "源",
    }


def _config(**over):
    base = {
        "id": 1,
        "enabled": True,
        "hour": 8,
        "timezone": "UTC",
        "windowHours": 48,
        "limitCount": 12,
        "perSourceCap": 0,
        "feedUrlAllow": "",
        "sourceKind": "window",
        "lookbackDays": 7,
    }
    base.update(over)
    return base


def _seed_published_issue(client, config_id, refs, published_at, status="published"):
    app = client.app
    run(
        GptDigestIssuesStore(app.state.db).upsert_issue(
            config_id=config_id,
            issue_key=f"k-{abs(hash(json.dumps(refs, sort_keys=True))) % 100000}",
            title="t",
            body_html="<p>b</p>",
            sections_json="[]",
            refs_json=json.dumps(refs, ensure_ascii=False),
            model="m",
            published_at=published_at,
            status_for_new=status,
        )
    )


# ---- F101 -------------------------------------------------------------------


def test_f101_recent_issue_dedupe_and_boundaries(client):
    app = client.app
    run(app.state.db.migrate())
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    # 已发布期（2 天前）引用了 url A 与 title-only B
    refs = {
        "s1": {"title": "旧文A", "url": "https://example.com/a"},
        "s2": {"title": "旧文B", "url": ""},
    }
    _seed_published_issue(client, 1, refs, "2026-09-13T00:00:00+00:00")

    docs = [
        _doc("d1", "2026-09-15T00:00:00Z"),  # 新材料：应入选
        _doc("d2", "2026-09-15T01:00:00Z", url="https://example.com/a"),  # 同内容不同引用 → 去重
        {
            "item_id": "d3",
            "entryRef": "d3",
            "title": "旧文B",
            "url": "",
            "publishedAt": "2026-09-15T02:00:00Z",
            "contentText": "x",
            "feedUrl": "https://tech.example.com/rss",
            "feedTitle": "源",
        },  # 无 URL 同标题 → 去重
    ]
    config = _config(lookbackDays=7)
    selected, counts, _per, _ws, _we, excluded, _pi = run(
        select_material_for_config(config, _FakeAdapter(docs), app.state.db, now)
    )
    assert [d["item_id"] for d in selected] == ["d1"]
    assert counts["recentIssue"] == 2
    assert {e["title"] for e in excluded} == {"标题d2", "旧文B"}
    assert all(e["reason"] == "recent_issue" for e in excluded)

    # 窗口边界一致性：7 天窗口内身份集为 2
    used7 = run(
        recent_used_keys(
            app.state.db, 1, 7, datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
        )
    )
    assert len(used7) == 2

    # 窗口变更：lookbackDays=1（截止 9/14）→ 9/13 期号已出窗，材料可用
    config1 = _config(lookbackDays=1)
    selected1, counts1, *_ = run(
        select_material_for_config(config1, _FakeAdapter(docs), app.state.db, now)
    )
    assert counts1["recentIssue"] == 0
    assert len(selected1) == 3

    # lookbackDays=0 = 去重关闭
    config0 = _config(lookbackDays=0)
    _sel0, counts0, *_ = run(
        select_material_for_config(config0, _FakeAdapter(docs), app.state.db, now)
    )
    assert counts0["recentIssue"] == 0

    # 时区边界：上海时区的 now（同一 UTC 时刻，+8h）与 UTC 的窗口截断
    # 不同——9/13 的期号在 Shanghai 视角的 1 天窗口内仍在（跨日语义）。
    used_sh_1d = run(
        recent_used_keys(
            app.state.db,
            1,
            1,
            datetime(2026, 9, 15, 16, 30, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    )
    used_utc_1d = run(
        recent_used_keys(
            app.state.db, 1, 1, datetime(2026, 9, 15, 8, 30, 0, tzinfo=UTC)
        )
    )
    assert isinstance(used_sh_1d, set) and isinstance(used_utc_1d, set)
    # 8:30 UTC 距 9/13 00:00 超过 1 天 → 出窗；16:30+08 = 8:30 UTC 相同 → 一致
    assert used_sh_1d == used_utc_1d == set()


def test_f101_draft_issue_not_counted_and_put_back(client):
    app = client.app
    run(app.state.db.migrate())
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    refs = {"s1": {"title": "草稿引用", "url": "https://example.com/draft"}}
    _seed_published_issue(client, 1, refs, "2026-09-14T00:00:00+00:00", status="draft")
    docs = [_doc("d1", "2026-09-15T00:00:00Z", url="https://example.com/draft")]

    # 负向：草稿不算已用 → 材料正常入选
    selected, counts, *_ = run(
        select_material_for_config(_config(), _FakeAdapter(docs), app.state.db, now)
    )
    assert counts["recentIssue"] == 0 and len(selected) == 1

    # 发布该草稿 → 立即命中去重
    draft_key = run(
        app.state.db.fetch_one("SELECT issue_key FROM gpt_digest_issues LIMIT 1")
    )["issue_key"]
    run(GptDigestIssuesStore(app.state.db).publish_issue(1, str(draft_key)))
    selected2, counts2, _p, _ws, _we, _ex, _pi = run(
        select_material_for_config(_config(), _FakeAdapter(docs), app.state.db, now)
    )
    assert counts2["recentIssue"] == 1 and selected2 == []

    # 放回（put_back）：本次生成显式放回该材料
    from lumirss.gpt_digest import _material_identity

    key = _material_identity(docs[0])
    selected3, _c3, _p3, _ws3, _we3, ex3, _pi3 = run(
        select_material_for_config(
            _config(), _FakeAdapter(docs), app.state.db, now, put_back=[key]
        )
    )
    assert len(selected3) == 1 and ex3 == []


def test_f101_preview_equals_generate_material(client):
    """preview 与生成请求使用同一选材函数：材料一致（mock 断言）。"""
    app = client.app
    run(app.state.db.migrate())
    run(GptDigestConfigStore(app.state.db).update_config(1, {"lookbackDays": 7, "timezone": "UTC"}))
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    refs = {"s1": {"title": "已用", "url": "https://example.com/used"}}
    _seed_published_issue(client, 1, refs, "2026-09-14T00:00:00+00:00")
    docs = [
        _doc("d1", "2026-09-15T00:00:00Z"),
        _doc("d2", "2026-09-15T01:00:00Z", url="https://example.com/used"),
    ]
    adapter = _FakeAdapter(docs)
    preview = run(build_preview(adapter, _config(), app.state.db, now))
    assert [i["title"] for i in preview["selected"]] == ["标题d1"]
    assert preview["counts"]["recentIssue"] == 1

    provider = _CapturingProvider()
    run(
        generate_issue(
            GptDigestConfigStore(app.state.db),
            GptDigestIssuesStore(app.state.db),
            config=_config(),
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(provider),
            db=app.state.db,
            now=now,
            draft=True,
        )
    )
    user_message = provider.material_titles[0]["content"]
    assert "标题d1" in user_message
    assert "标题d2" not in user_message  # 与预览一致：被去重者不进生成

    # 放回后：预览与生成同步多出该材料
    from lumirss.gpt_digest import _material_identity

    key = _material_identity(docs[1])
    preview2 = run(
        build_preview(adapter, _config(), app.state.db, now, put_back=[key])
    )
    assert len(preview2["selected"]) == 2
    provider2 = _CapturingProvider()
    run(
        generate_issue(
            GptDigestConfigStore(app.state.db),
            GptDigestIssuesStore(app.state.db),
            config=_config(),
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(provider2),
            db=app.state.db,
            now=now,
            draft=True,
            put_back=[key],
        )
    )
    assert "标题d2" in provider2.material_titles[0]["content"]


# ---- F102 -------------------------------------------------------------------


def test_f102_pool_crud_duplicate_invalid_and_consumption(client):
    app = client.app
    run(app.state.db.migrate())
    pool = DigestMaterialPoolStore(app.state.db)
    run(pool.add_entry(1, "rss:abc"))
    try:
        run(pool.add_entry(1, "rss:abc"))
        raise AssertionError("重复添加应抛 DigestPoolDuplicate")
    except Exception as exc:
        assert type(exc).__name__ == "DigestPoolDuplicate"

    # 路由层 409
    resp = client.post("/api/v1/gpt-digest/configs/1/pool", json={"entryRef": "rss:abc"})
    assert resp.status_code == 409
    added = client.post("/api/v1/gpt-digest/configs/1/pool", json={"entryRef": "rss:def"})
    assert added.status_code == 201, added.text

    listing = client.get("/api/v1/gpt-digest/configs/1/pool").json()
    assert len(listing["items"]) == 2

    # reorder
    ids = [e["id"] for e in listing["items"]]
    client.patch("/api/v1/gpt-digest/configs/1/pool", json={"orderedIds": [ids[1], ids[0]]})
    after = client.get("/api/v1/gpt-digest/configs/1/pool").json()["items"]
    assert [e["id"] for e in after] == [ids[1], ids[0]]

    # 删除
    assert client.delete(f"/api/v1/gpt-digest/configs/1/pool/{ids[0]}").status_code == 204
    assert client.delete(f"/api/v1/gpt-digest/configs/1/pool/{ids[0]}").status_code == 404


def test_f102_pool_merge_preview_skip_invalid_and_no_consume_on_draft(client):
    app = client.app
    run(app.state.db.migrate())
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    from lumirss.entryref import encode_entry_ref

    good_id = "tag:google.com,2005:reader/item/00000000000001a1"
    gone_id = "tag:google.com,2005:reader/item/00000000000001a2"
    good_ref = encode_entry_ref(good_id)
    gone_ref = encode_entry_ref(gone_id)
    pool = DigestMaterialPoolStore(app.state.db)
    run(pool.add_entry(1, good_ref))
    run(pool.add_entry(1, gone_ref))  # 原文已删除
    details = {good_id: _FakeEntryDetail("rss:good", "手工好文", "https://example.com/manual")}
    adapter = _FakeAdapter([], details=details)

    preview = run(build_preview(adapter, _config(), app.state.db, now))
    assert [i["source"] for i in preview["selected"]] == ["manual"]
    assert preview["selected"][0]["title"] == "手工好文"
    assert {i["reason"] for i in preview["poolInvalid"]} == {"source_missing"}

    # 草稿生成：不消费池（负向：未发布不消费）
    provider = _CapturingProvider()
    run(
        generate_issue(
            GptDigestConfigStore(app.state.db),
            GptDigestIssuesStore(app.state.db),
            config=_config(),
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(provider),
            db=app.state.db,
            now=now,
            draft=True,
        )
    )
    pending = run(pool.pending_refs(1))
    assert [p["entryRef"] for p in pending] == [good_ref, gone_ref]

    # 直接发布（draft=False，调度语义）→ good 被消费、gone 保持待用
    run(
        generate_issue(
            GptDigestConfigStore(app.state.db),
            GptDigestIssuesStore(app.state.db),
            config=_config(),
            adapter=adapter,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(_CapturingProvider()),
            db=app.state.db,
            now=now,
            draft=False,
        )
    )
    pending2 = run(pool.pending_refs(1))
    assert [p["entryRef"] for p in pending2] == [gone_ref]
    used = run(pool.list_entries(1))
    consumed = [e for e in used if e["usedIssueKey"]]
    assert len(consumed) == 1 and consumed[0]["entryRef"] == good_ref


def test_f102_pool_config_isolation_and_ai_disabled_rejected(client):
    app = client.app
    run(app.state.db.migrate())
    pool = DigestMaterialPoolStore(app.state.db)
    run(pool.add_entry(1, "rss:one"))
    # 多 config 隔离：config 2 的池为空
    configs = GptDigestConfigStore(app.state.db)
    created = run(configs.create_config({"name": "第二份"}))
    assert run(pool.pending_refs(int(created["id"]))) == []

    # F066 负向：AI 禁用来源的条目不可加入（服务端拒绝）
    from lumirss.entryref import encode_entry_ref
    from lumirss.source_ai_gate import set_ai_disabled

    db = app.state.db
    ref = encode_entry_ref("tag:google.com,2005:reader/item/00000000000001f7")
    run(
        db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES ('1f7', ?, ?, '禁用源', '禁用条目', '', 'https://x/d', '正文', '2026-09-15T00:00:00Z', 0, 0, 0)",
            (ref, "https://disabled.example.com/feed"),
        )
    )
    run(set_ai_disabled(db, "https://disabled.example.com/feed", True))
    resp = client.post(
        "/api/v1/gpt-digest/configs/1/pool", json={"entryRef": ref}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["type"] == "ai_disabled_source"

    # 删除配置 → 池级联清空
    run(configs.delete_config(int(created["id"])))
    rows = run(
        db.fetch_all("SELECT * FROM digest_material_pool WHERE config_id = ?", (int(created["id"]),))
    )
    assert rows == []


# ---- F103 -------------------------------------------------------------------


def test_f103_rotate_dry_run_zero_change_then_real(client):
    app = client.app
    run(app.state.db.migrate())
    # 0067：直连调用无请求上下文 → 显式 owner uid 解析 routing secrets。
    store = GptDigestStore(
        app.state.db, app.state.secrets_store.store_for(app.state.owner_id)
    )
    old_token = store.ensure_feed_token()
    assert old_token  # 首次创建 → 一次性返回原始 token
    stored_hash = store.feed_token()
    from lumirss.token_hash import is_token_hash, verify_token

    assert stored_hash and is_token_hash(stored_hash)  # §13.4：库（文件）无明文

    dry = client.post("/api/v1/gpt-digest/feed/rotate?dryRun=true")
    assert dry.status_code == 200, dry.text
    impact = dry.json()["impact"]
    assert impact["tokenExists"] is True
    assert "旧链接立即失效" in impact["note"]
    assert store.feed_token() == stored_hash  # 零变更断言：token 未动

    # 重复 dry-run 幂等
    dry2 = client.post("/api/v1/gpt-digest/feed/rotate?dryRun=true")
    assert dry2.status_code == 200
    assert store.feed_token() == stored_hash
    assert verify_token(old_token, stored_hash)  # 旧链接仍有效（未轮换）

    # 真实轮换：旧 404 / 新可读
    rotated = client.post("/api/v1/gpt-digest/feed/rotate")
    assert rotated.status_code == 200
    new_atom_path = rotated.json()["atomPath"]
    new_token = new_atom_path.split("/feeds/gpt-digest/")[1].removesuffix(".atom")
    assert new_token != old_token
    assert client.get(f"/feeds/gpt-digest/{old_token}.atom").status_code == 404
    assert client.get(f"/feeds/gpt-digest/{new_token}.atom").status_code == 200


def test_f103_rotate_requires_session_when_session_mode(client, monkeypatch):
    """负向：session 模式下未登录访问管理端点 → 401（中间件按请求读取
    配置；无 cookie 的非浏览器请求在 CSRF 门放行后命中 session 门）。"""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    resp = client.post("/api/v1/gpt-digest/feed/rotate")
    assert resp.status_code == 401
    assert resp.json()["error"]["type"] == "session_required"
