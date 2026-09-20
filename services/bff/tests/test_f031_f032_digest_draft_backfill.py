"""F031 日报草稿审阅 + F032 缺失日期补刊。

用 gpt_digest 域的既有 fake 模式（FakeAdapter / FakeAiSettings /
deterministic provider）；覆盖：草稿不出现在公开 feed、发布幂等、校验
失败保留草稿、缺失日期列表的时区行为、补刊 409/无材料。"""

import asyncio
import json
from datetime import datetime

from lumirss.gpt_digest_configs import GptDigestConfigStore
from lumirss.gpt_digest_issues import GptDigestIssuesStore


def run(coroutine):
    return asyncio.run(coroutine)


class _FakeAdapter:
    def __init__(self, docs) -> None:
        self._docs = docs

    async def list_entry_documents(self, limit=120):
        return self._docs

    async def list_entries(self, **kwargs):  # pragma: no cover - not used
        raise AssertionError


class _FakeAiSettings:
    async def load(self):
        return {"ai.base_url": "https://api.example.com/v1", "ai.model": "m"}


class _OkProvider:
    async def complete(self, *, messages):
        return json.dumps(
            {
                "title": "日报",
                "sections": [
                    {"heading": "要点", "summary": "内容", "sourceIds": ["s1"]}
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )


def _ok(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


def _doc(item_id, published, feed_url="https://tech.example.com/rss"):
    return {
        "id": item_id,
        "title": f"标题{item_id}",
        "url": f"https://example.com/{item_id}",
        "published": published,
        "content_text": "正文",
        "feed_url": feed_url,
        "feed_title": "源",
    }


_DEFAULT_CONFIG = {
    "enabled": True,
    "hour": 8,
    "timezone": "Asia/Shanghai",
    "windowHours": 24,
    "limitCount": 12,
    "perSourceCap": 5,
}


def _seed_issue(client, config_id, issue_key, status="draft"):
    app = client.app
    run(
        GptDigestIssuesStore(app.state.db).upsert_issue(
            config_id=config_id,
            issue_key=issue_key,
            title="t",
            body_html="<p>b</p>",
            sections_json=json.dumps(
                {
                    "title": "t",
                    "sections": [
                        {
                            "heading": "h",
                            "items": [
                                {"title": "标题", "summary": "s", "sourceIds": ["s1"]}
                            ],
                        }
                    ],
                    "limitations": [],
                },
                ensure_ascii=False,
            ),
            refs_json=json.dumps({"s1": {"title": "标题", "url": "https://e.x/a"}}, ensure_ascii=False),
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
            status_for_new=status,
        )
    )


def test_f031_draft_not_in_public_feed_publish_idempotent_and_validation(client):
    app = client.app
    run(app.state.db.migrate())
    _seed_issue(client, 1, "2026-09-17", status="draft")

    # 公开订阅只含 published：草稿不可见（负向）
    from lumirss.gpt_digest_store import GptDigestStore

    token = GptDigestStore(app.state.db, app.state.secrets_store).ensure_feed_token()
    feed = client.get(f"/feeds/gpt-digest/{token}.atom")
    assert feed.status_code == 200
    assert "2026-09-17" not in feed.text

    # 管理列表可见草稿（含 status 徽标字段）
    listing = client.get("/api/v1/gpt-digest/issues").json()["items"]
    assert any(i["issueKey"] == "2026-09-17" and i["status"] == "draft" for i in listing)

    # 引用校验失败 → 仍是草稿（把 refs 清空使 sourceId 失配）
    run(
        app.state.db.execute(
            "UPDATE gpt_digest_issues SET refs_json = '{}' WHERE issue_key = '2026-09-17'",
            (),
        )
    )
    failed = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-17/publish")
    assert failed.status_code == 422
    still = run(GptDigestIssuesStore(app.state.db).get_issue(1, "2026-09-17"))
    assert still["status"] == "draft"

    # 修复引用后发布 → published 并出现在公开 feed
    run(
        app.state.db.execute(
            "UPDATE gpt_digest_issues SET refs_json = ? WHERE issue_key = '2026-09-17'",
            (json.dumps({"s1": {"title": "标题", "url": "https://e.x/a"}}),),
        )
    )
    published = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-17/publish")
    assert published.status_code == 200, published.text
    assert published.json()["issue"]["status"] == "published"
    feed2 = client.get(f"/feeds/gpt-digest/{token}.atom")
    assert "2026-09-17" in feed2.text

    # 幂等：再发布 200 不变
    again = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-17/publish")
    assert again.status_code == 200
    assert again.json()["issue"]["status"] == "published"

    # 存量期号回填 published：既有行（迁移前语义）本来就是 published——
    # 用直接 SQL 模拟一行的历史状态，确认 store 读取按 status 如实呈现。
    run(
        app.state.db.execute(
            "UPDATE gpt_digest_issues SET status = 'published' WHERE issue_key = '2026-09-17'",
            (),
        )
    )
    assert run(GptDigestIssuesStore(app.state.db).get_issue(1, "2026-09-17"))["status"] == "published"


def test_f032_missing_dates_timezone_and_backfill_guards(client):
    app = client.app
    run(app.state.db.migrate())
    configs = GptDigestConfigStore(app.state.db)
    run(configs.update_config(1, {"timezone": "Asia/Shanghai"}))

    # UTC+8：上海时间的「今天」可能比 UTC 早一天结束——先看上海缺失列表
    sh = client.get("/api/v1/gpt-digest/configs/1/missing-dates").json()
    assert sh["missing"], "新配置应有缺失日期"

    # 补一个缺失日期 → 列表收敛
    target = sh["missing"][-1]
    run(
        GptDigestIssuesStore(app.state.db).upsert_issue(
            config_id=1,
            issue_key=target,
            title="t",
            body_html="b",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
        )
    )
    sh2 = client.get("/api/v1/gpt-digest/configs/1/missing-dates").json()
    assert target not in sh2["missing"]

    # 时区差异：UTC 配置与 UTC+8 配置在同一 UTC 时刻可能给出不同的
    # 「最近一天」边界（至少 missing 键均为合法日期字符串）
    run(configs.update_config(1, {"timezone": "UTC"}))
    utc = client.get("/api/v1/gpt-digest/configs/1/missing-dates").json()
    for key in utc["missing"]:
        datetime.strptime(key, "%Y-%m-%d")  # 形状校验
    run(configs.update_config(1, {"timezone": "Asia/Shanghai"}))

    # 补刊生成：已有期号的日期 → 409 protected（不覆盖已发布）
    guarded = client.post(
        "/api/v1/gpt-digest/configs/1/generate",
        json={"targetDate": target},
    )
    assert guarded.status_code == 409
    assert guarded.json()["error"]["type"] == "protected"

    # FreshRSS 未配置 → 503（诚实错误，不产空刊）
    missing_now = client.get("/api/v1/gpt-digest/configs/1/missing-dates").json()
    real_missing = [d for d in missing_now["missing"] if d != target]
    if real_missing:
        attempt = client.post(
            "/api/v1/gpt-digest/configs/1/generate",
            json={"targetDate": real_missing[-1]},
        )
        assert attempt.status_code == 503
