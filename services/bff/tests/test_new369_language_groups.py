"""NEW-369 个人资料语言筛选 — 显式记录/用户校正分组 / unknown 单独 / 隔离。"""

import asyncio

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

BY_LANGUAGE_PATH = "/api/v1/search/by-language"
OVERRIDES_PATH = "/api/v1/translation/language-overrides"


def _seed_multilingual(env):
    """e1=entry 更正 en；e2/e3=源更正 ja（feed f2）；e4=来源记录 de
    （source_overrides）；e5=无任何记录（unknown）。"""
    seed_entry(env, "a", "n369-e1", title="Alpha 对照 一", content_text="词")
    seed_entry(env, "a", "n369-e2", title="Alpha 对照 二", content_text="词")
    seed_entry(env, "a", "n369-e3", title="Alpha 对照 三", content_text="词")
    seed_entry(env, "a", "n369-e4", title="Alpha 对照 四", content_text="词")
    seed_entry(env, "a", "n369-e5", title="Alpha 对照 五", content_text="词")

    async def rewire():
        from lumirss.user_scope import user_context

        with user_context(env["a"]["userId"]):
            db = env["app"].state.db
            await db.execute(
                "UPDATE search_entries SET feed_url = ? WHERE item_id = ?",
                ("https://f2.example/rss", "n369-e2"),
            )
            await db.execute(
                "UPDATE search_entries SET feed_url = ? WHERE item_id = ?",
                ("https://f2.example/rss", "n369-e3"),
            )
            await db.execute(
                "UPDATE search_entries SET feed_url = ? WHERE item_id = ?",
                ("https://f3.example/rss", "n369-e4"),
            )
            await db.execute(
                "UPDATE search_entries SET feed_url = ? WHERE item_id = ?",
                ("https://f4.example/rss", "n369-e5"),
            )

    asyncio.run(rewire())

    put = OVERRIDES_PATH
    assert (
        client_put(env, put, {"scope": "entry", "refKey": encode_entry_ref("n369-e1"), "language": "en"})
        == 200
    )
    assert (
        client_put(env, put, {"scope": "source", "refKey": "https://f2.example/rss", "language": "ja"})
        == 200
    )
    set_source_recorded_language(env, "https://f3.example/rss", "de")


def client_put(env, path: str, payload: dict) -> int:
    return env["client"].put(path, json=payload, headers=env["a"]).status_code


def set_source_recorded_language(env, feed_url: str, language: str) -> None:
    """来源上「明确记录」的语言（source_overrides.language，非猜测）。"""

    async def run():
        from lumirss.user_scope import user_context

        with user_context(env["a"]["userId"]):
            await env["app"].state.db.execute(
                "INSERT INTO source_overrides (feed_url, hidden_until,"
                " show_from, language, updated_at)"
                " VALUES (?, NULL, NULL, ?, '2026-01-01T00:00:00Z')"
                " ON CONFLICT(feed_url) DO UPDATE SET language = excluded.language",
                (feed_url, language),
            )

    asyncio.run(run())


def test_new369_groups_from_explicit_records_only(ab_env):  # noqa: F811
    """分组只来自显式记录/校正；未知语言单独成组，绝不按界面语言猜测。"""
    client = ab_env["client"]
    _seed_multilingual(ab_env)
    response = client.get(BY_LANGUAGE_PATH, params={"q": "Alpha"}, headers=ab_env["a"])
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 5
    groups = {g["language"]: g["count"] for g in payload["groups"]}
    assert groups == {"en": 1, "ja": 2, "de": 1}  # unknown 不在 groups 里
    assert payload["unknown"]["count"] == 1
    assert len(payload["unknown"]["sampleRefs"]) == 1
    en_group = next(g for g in payload["groups"] if g["language"] == "en")
    assert en_group["sampleRefs"] == [encode_entry_ref('n369-e1')]

    # entry 更正优先于源更正：e1 明确 en（即便它的源没有更正）。
    assert "https://f1" not in str(payload)


def test_new369_group_filter_narrows(ab_env):  # noqa: F811
    """分组可作筛选：源更正组按 feedUrl 收窄后计数一致（组合语义）。"""
    client = ab_env["client"]
    _seed_multilingual(ab_env)
    narrowed = client.get(
        BY_LANGUAGE_PATH,
        params={"q": "Alpha", "feedUrl": "https://f2.example/rss"},
        headers=ab_env["a"],
    ).json()
    assert narrowed["total"] == 2
    groups = {g["language"]: g["count"] for g in narrowed["groups"]}
    assert groups == {"ja": 2}
    assert narrowed["unknown"]["count"] == 0


def test_new369_isolation(ab_env):  # noqa: F811
    """A 的命中与更正对 B 不可见：B 同查询全空。"""
    client = ab_env["client"]
    _seed_multilingual(ab_env)
    b_payload = client.get(
        BY_LANGUAGE_PATH, params={"q": "Alpha"}, headers=ab_env["b"]
    ).json()
    assert b_payload["total"] == 0
    assert b_payload["groups"] == []
    assert b_payload["unknown"]["count"] == 0


def test_new369_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    assert (
        client.get(BY_LANGUAGE_PATH, params={"q": ""}, headers=ab_env["a"]).status_code
        == 400
    )
    both = client.get(
        BY_LANGUAGE_PATH,
        params={"q": "Alpha", "feedUrl": "https://x", "categoryId": "c1"},
        headers=ab_env["a"],
    )
    assert both.status_code == 400
