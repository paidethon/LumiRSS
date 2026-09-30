"""NEW-362 相似标题候选审阅 — 可解释相似度 / 显式确认才入组 / 隔离。"""

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

CANDIDATES_PATH = "/api/v1/search/similar-title-candidates"
CONFIRM_PATH = "/api/v1/search/similar-title-candidates/confirm"


def _seed_pair(env):
    seed_entry(env, "a", "n362-a", title="深度学习阅读器入门指南")
    seed_entry(env, "a", "n362-b", title="深度学习阅读器入门指南（转载）")
    seed_entry(env, "a", "n362-c", title="完全无关的食谱合集")


def test_new362_candidates_explainable(ab_env):  # noqa: F811
    """候选带可解释相似度（score/共有二元组/片段样例）；无关稿不出现。"""
    client = ab_env["client"]
    _seed_pair(ab_env)
    ref_a = encode_entry_ref('n362-a')
    response = client.get(
        CANDIDATES_PATH, params={"entryRef": ref_a}, headers=ab_env["a"]
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    refs = [c["entryRef"] for c in payload["candidates"]]
    assert encode_entry_ref('n362-b') in refs
    assert encode_entry_ref('n362-c') not in refs
    candidate = payload["candidates"][0]
    assert candidate["score"] >= 60
    assert candidate["sharedBigrams"] > 0
    assert candidate["sharedSample"]
    assert candidate["totalBigrams"]["a"] > 0
    assert candidate["inGroup"] is None  # 只列候选，绝不自动入组
    assert payload["scanned"] >= 2


def test_new362_confirm_creates_relation(ab_env):  # noqa: F811
    """只有显式确认才写 item_relations：转载 → manual+转载前缀；
    重复 → duplicate；确认后候选如实标注 inGroup。"""
    client = ab_env["client"]
    _seed_pair(ab_env)
    seed_entry(ab_env, "a", "n362-d", title="深度学习阅读器入门指南（修订版）")
    ref_a = encode_entry_ref('n362-a')
    ref_b = encode_entry_ref('n362-b')
    ref_d = encode_entry_ref('n362-d')

    reprint = client.post(
        CONFIRM_PATH,
        json={"aRef": ref_a, "bRef": ref_b, "relation": "reprint"},
        headers=ab_env["a"],
    )
    assert reprint.status_code == 201, reprint.text
    assert reprint.json()["relation"]["kind"] == "manual"
    assert reprint.json()["relation"]["note"].startswith("转载：")

    duplicate = client.post(
        CONFIRM_PATH,
        json={"aRef": ref_a, "bRef": ref_d, "relation": "duplicate"},
        headers=ab_env["a"],
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["relation"]["kind"] == "duplicate"

    # 幂等：同一确认重放不新建。
    again = client.post(
        CONFIRM_PATH,
        json={"aRef": ref_a, "bRef": ref_b, "relation": "reprint"},
        headers=ab_env["a"],
    )
    assert again.status_code == 201
    assert again.json()["relation"]["id"] == reprint.json()["relation"]["id"]

    listing = client.get(
        CANDIDATES_PATH, params={"entryRef": ref_a}, headers=ab_env["a"]
    ).json()
    in_groups = {c["entryRef"]: c["inGroup"] for c in listing["candidates"]}
    assert in_groups[ref_b] == "manual"
    assert in_groups[ref_d] == "duplicate"


def test_new362_validation_and_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    _seed_pair(ab_env)
    ref_a = encode_entry_ref('n362-a')
    ref_b = encode_entry_ref('n362-b')

    assert (
        client.post(
            CONFIRM_PATH,
            json={"aRef": ref_a, "bRef": ref_a, "relation": "duplicate"},
            headers=ab_env["a"],
        ).status_code
        == 422
    )
    assert (
        client.post(
            CONFIRM_PATH,
            json={"aRef": ref_a, "bRef": ref_b, "relation": "merge"},
            headers=ab_env["a"],
        ).status_code
        == 422
    )
    unknown = client.get(
        CANDIDATES_PATH,
        params={"entryRef": encode_entry_ref('n362-ghost')},
        headers=ab_env["a"],
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["type"] == "search_entry_not_found"

    # 隔离：A 的条目在 B 的投影里不存在（同一 404，不泄露存在性）。
    b_view = client.get(
        CANDIDATES_PATH, params={"entryRef": ref_a}, headers=ab_env["b"]
    )
    assert b_view.status_code == 404
