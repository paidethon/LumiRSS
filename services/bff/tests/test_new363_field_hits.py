"""NEW-363 跨字段命中说明 — 标题/正文/作者/笔记归位 + 缺失诚实 + 隔离。"""

import asyncio

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

FIELD_HITS_PATH = "/api/v1/search/field-hits"


def _seed_rich_entry(env):
    """一篇正文与作者都含词条、并带本人笔记批注的条目。"""
    seed_entry(
        env,
        "a",
        "n363-rich",
        title="与词条无关的标题",
        content_text="正文深处提到量子这个词的位置。",
    )
    _set_author(env, "n363-rich", "量子研究所")

    async def annotate():
        from lumirss.annotation_store import AnnotationStore
        from lumirss.user_scope import user_context

        with user_context(env["a"]["userId"]):
            await AnnotationStore(env["app"].state.db).create(
                entry_ref=encode_entry_ref("n363-rich"),
                anchor={"type": "paragraph", "index": 0},
                excerpt="这一段提到量子纠缠。",
                note="我的量子笔记",
            )

    asyncio.run(annotate())
    return encode_entry_ref('n363-rich')


def _set_author(env, item_id: str, author: str) -> None:
    async def run():
        from lumirss.user_scope import user_context

        with user_context(env["a"]["userId"]):
            await env["app"].state.db.execute(
                "UPDATE search_entries SET author = ? WHERE item_id = ?",
                (author, item_id),
            )

    asyncio.run(run())


def test_new363_fields_located(ab_env):  # noqa: F811
    """正文/作者/本人笔记各自归位；笔记列带命中计数与摘录。"""
    client = ab_env["client"]
    ref = _seed_rich_entry(ab_env)
    response = client.post(
        FIELD_HITS_PATH,
        json={"query": "量子", "entryRefs": [ref]},
        headers=ab_env["a"],
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert "content" in item["fields"]
    assert "author" in item["fields"]
    assert "note" in item["fields"]
    assert item["noteHit"] is not None
    assert item["noteHit"]["count"] == 1
    assert "量子" in item["noteHit"]["excerpt"]


def test_new363_title_only_hit(ab_env):  # noqa: F811
    client = ab_env["client"]
    seed_entry(ab_env, "a", "n363-title", title="标题里就有磁悬浮", content_text="别的")
    ref = encode_entry_ref('n363-title')
    item = client.post(
        FIELD_HITS_PATH,
        json={"query": "磁悬浮", "entryRefs": [ref]},
        headers=ab_env["a"],
    ).json()["items"][0]
    assert item["fields"] == ["title"]
    assert item["noteHit"] is None


def test_new363_missing_and_isolation(ab_env):  # noqa: F811
    """不在本人投影的 ref 如实进 missing（不泄露存在性）；A 的归位对 B 不可见。"""
    client = ab_env["client"]
    ref = _seed_rich_entry(ab_env)
    ghost = encode_entry_ref('n363-ghost')
    payload = client.post(
        FIELD_HITS_PATH,
        json={"query": "量子", "entryRefs": [ref, ghost]},
        headers=ab_env["a"],
    ).json()
    assert payload["missing"] == [ghost]
    assert len(payload["items"]) == 1

    b_payload = client.post(
        FIELD_HITS_PATH,
        json={"query": "量子", "entryRefs": [ref]},
        headers=ab_env["b"],
    ).json()
    assert b_payload["items"] == []
    assert b_payload["missing"] == [ref]


def test_new363_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    empty = client.post(
        FIELD_HITS_PATH,
        json={"query": " ", "entryRefs": [encode_entry_ref('x')]},
        headers=ab_env["a"],
    )
    assert empty.status_code == 400
    too_many = client.post(
        FIELD_HITS_PATH,
        json={"query": "量子", "entryRefs": ["r" for _ in range(51)]},
        headers=ab_env["a"],
    )
    assert too_many.status_code == 422
