"""NEW-365 搜索排除词建议审批 — 候选纯计数 / 确认才生效 / 撤销 / 隔离。"""

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

CANDIDATES_PATH = "/api/v1/search/exclusion-candidates"
WORDS_PATH = "/api/v1/search/exclusion-words"


def _seed_marked(env):
    """三篇被标记「不相关」的结果共享词「广告」，且都含查询词。"""
    for index in range(3):
        seed_entry(
            env,
            "a",
            f"n365-marked-{index}",
            title=f"内核 新闻汇编 第{index}期",
            content_text=f"内核 动态。本期含广告与推广内容{index}。",
        )


def test_new365_candidates_are_counted_not_applied(ab_env):  # noqa: F811
    """候选 = 标记结果中的高频词（含该词条数排序）；确认前不进查询。"""
    client = ab_env["client"]
    _seed_marked(ab_env)
    marked_refs = [
        encode_entry_ref(f'n365-marked-{i}') for i in range(3)
    ]
    payload = client.post(
        CANDIDATES_PATH,
        json={"query": "内核", "markedRefs": marked_refs},
        headers=ab_env["a"],
    )
    assert payload.status_code == 200, payload.text
    body = payload.json()
    assert body["markedScanned"] == 3
    assert body["markedMissing"] == 0
    words = {c["word"]: c["markedHits"] for c in body["candidates"]}
    assert words.get("广告") == 3  # 三篇标记结果都含该词
    assert "内核" not in words  # 查询词本身永不进候选


def test_new365_approve_apply_revoke(ab_env):  # noqa: F811
    client = ab_env["client"]
    _seed_marked(ab_env)
    approved = client.post(
        WORDS_PATH,
        json={"query": "内核", "word": "广告"},
        headers=ab_env["a"],
    )
    assert approved.status_code == 201, approved.text
    body = approved.json()
    assert body["already"] is False

    listing = client.get(f"{WORDS_PATH}?q=内核", headers=ab_env["a"]).json()
    assert [item["word"] for item in listing["items"]] == ["广告"]

    again = client.post(
        WORDS_PATH, json={"query": "内核", "word": "广告"}, headers=ab_env["a"]
    )
    assert again.status_code == 201
    assert again.json()["already"] is True

    deleted = client.delete(
        f"{WORDS_PATH}/{body['id']}", headers=ab_env["a"]
    )
    assert deleted.status_code == 204
    assert client.get(f"{WORDS_PATH}?q=内核", headers=ab_env["a"]).json()[
        "items"
    ] == []
    assert (
        client.delete(f"{WORDS_PATH}/{body['id']}", headers=ab_env["a"]).status_code
        == 404
    )


def test_new365_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    empty_refs = client.post(
        CANDIDATES_PATH,
        json={"query": "内核", "markedRefs": []},
        headers=ab_env["a"],
    )
    assert empty_refs.status_code == 422

    # 单查询确认词上限 20：第 21 个如实拒绝（422 word_invalid），不静默淘汰。
    for index in range(20):
        word = client.post(
            WORDS_PATH,
            json={"query": "内核", "word": f"词{index:02d}号"},
            headers=ab_env["a"],
        )
        assert word.status_code == 201, word.text
    over_cap = client.post(
        WORDS_PATH,
        json={"query": "内核", "word": "超额词"},
        headers=ab_env["a"],
    )
    assert over_cap.status_code == 422
    assert over_cap.json()["error"]["type"] == "word_invalid"
    # 上限按查询键隔离：换一个查询不受影响。
    other = client.post(
        WORDS_PATH,
        json={"query": "另一个 查询", "word": "超额词"},
        headers=ab_env["a"],
    )
    assert other.status_code == 201


def test_new365_isolation(ab_env):  # noqa: F811
    """A 的确认词是本人数据：B 的同查询没有已确认词。"""
    client = ab_env["client"]
    _seed_marked(ab_env)
    client.post(
        WORDS_PATH, json={"query": "内核", "word": "广告"}, headers=ab_env["a"]
    )
    b_listing = client.get(f"{WORDS_PATH}?q=内核", headers=ab_env["b"]).json()
    assert b_listing["items"] == []
    # B 标记自己的结果提候选：A 的条目不在 B 投影 → 全部 missing。
    b_payload = client.post(
        CANDIDATES_PATH,
        json={
            "query": "内核",
            "markedRefs": [encode_entry_ref('n365-marked-0')],
        },
        headers=ab_env["b"],
    ).json()
    assert b_payload["markedScanned"] == 0
    assert b_payload["markedMissing"] == 1
    assert b_payload["candidates"] == []
