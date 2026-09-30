"""NEW-366 段落级搜索结果 — 多段落分别列出 / 显式保存片段 / 隔离。"""

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

PARAGRAPHS_PATH = "/api/v1/search/paragraphs"
FRAGMENTS_PATH = "/api/v1/search/fragments"

_LONG_CONTENT = (
    "首段不含关键词只讲背景。\n"
    "第二段讨论内核调度器的演进史。\n"
    "第三段没有命中内容。\n"
    "第四段再次回到内核内存管理的话题。"
)


def _seed_long_entry(env):
    seed_entry(
        env, "a", "n366-long", title="长文示例", content_text=_LONG_CONTENT
    )
    return encode_entry_ref('n366-long')


def test_new366_paragraph_hits_listed_separately(ab_env):  # noqa: F811
    """长文的多段落命中分别列出（index/offset/命中词）；无命中段不出现。"""
    client = ab_env["client"]
    ref = _seed_long_entry(ab_env)
    response = client.get(
        PARAGRAPHS_PATH, params={"entryRef": ref, "q": "内核"}, headers=ab_env["a"]
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["paragraphs"]) == 2
    assert payload["paragraphTotal"] == 4
    assert payload["complete"] is True
    indexes = [p["index"] for p in payload["paragraphs"]]
    assert indexes == [1, 3]
    assert all("内核" in p["text"] for p in payload["paragraphs"])
    assert payload["paragraphs"][0]["terms"] == ["内核"]
    assert payload["paragraphs"][0]["offset"] >= 0
    assert "entryRef" in payload["entry"]


def test_new366_save_only_relevant_fragment(ab_env):  # noqa: F811
    """用户显式保存选中的段落；清单/删除闭环；未选中段不落库。"""
    client = ab_env["client"]
    ref = _seed_long_entry(ab_env)
    saved = client.post(
        FRAGMENTS_PATH,
        json={
            "entryRef": ref,
            "query": "内核",
            "paragraphIndex": 1,
            "text": "第二段讨论内核调度器的演进史。",
        },
        headers=ab_env["a"],
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["entryRef"] == ref
    assert body["query"] == "内核"

    listing = client.get(FRAGMENTS_PATH, headers=ab_env["a"]).json()
    assert len(listing["items"]) == 1
    assert listing["items"][0]["id"] == body["id"]

    by_ref = client.get(
        FRAGMENTS_PATH, params={"entryRef": ref}, headers=ab_env["a"]
    ).json()
    assert len(by_ref["items"]) == 1

    assert (
        client.delete(f"{FRAGMENTS_PATH}/{body['id']}", headers=ab_env["a"]).status_code
        == 204
    )
    assert client.get(FRAGMENTS_PATH, headers=ab_env["a"]).json()["items"] == []


def test_new366_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    _seed_long_entry(ab_env)
    missing = client.get(
        PARAGRAPHS_PATH,
        params={
            "entryRef": encode_entry_ref('n366-ghost'),
            "q": "内核",
        },
        headers=ab_env["a"],
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "search_entry_not_found"
    no_hits = client.get(
        PARAGRAPHS_PATH,
        params={"entryRef": encode_entry_ref('n366-long'), "q": "量子"},
        headers=ab_env["a"],
    )
    assert no_hits.status_code == 200
    assert no_hits.json()["paragraphs"] == []
    too_long_text = client.post(
        FRAGMENTS_PATH,
        json={
            "entryRef": encode_entry_ref('n366-long'),
            "query": "内核",
            "paragraphIndex": 0,
            "text": "x" * 401,
        },
        headers=ab_env["a"],
    )
    assert too_long_text.status_code == 422
    ghost_save = client.post(
        FRAGMENTS_PATH,
        json={
            "entryRef": encode_entry_ref('n366-ghost'),
            "query": "内核",
            "paragraphIndex": 0,
            "text": "片段",
        },
        headers=ab_env["a"],
    )
    assert ghost_save.status_code == 404


def test_new366_isolation(ab_env):  # noqa: F811
    """A 的长文与片段对 B 不可见（B 的片段清单恒空）。"""
    client = ab_env["client"]
    ref = _seed_long_entry(ab_env)
    client.post(
        FRAGMENTS_PATH,
        json={"entryRef": ref, "query": "内核", "paragraphIndex": 1, "text": "片段"},
        headers=ab_env["a"],
    )
    assert (
        client.get(
            PARAGRAPHS_PATH,
            params={"entryRef": ref, "q": "内核"},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    assert client.get(FRAGMENTS_PATH, headers=ab_env["b"]).json()["items"] == []
