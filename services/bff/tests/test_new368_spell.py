"""NEW-368 相近拼写搜索提示 — 零命中才提示 / 可选择不自动替换 / 隔离。"""

from new2xx_ab import ab_env, seed_entry  # noqa: F401 — pytest 夹具注册

SPELL_PATH = "/api/v1/search/spell-suggestions"


def test_new368_suggestions_only_on_zero_hits(ab_env):  # noqa: F811
    """「linx」（距 linux 一次编辑）零命中 → 候选含 linux；正常词 →
    hasHits=true 且候选恒空。"""
    client = ab_env["client"]
    seed_entry(
        ab_env,
        "a",
        "n368-a",
        title="linux kernel weekly news",
        content_text="linux 内核周报",
    )
    typo = client.get(SPELL_PATH, params={"q": "linx"}, headers=ab_env["a"])
    assert typo.status_code == 200, typo.text
    payload = typo.json()
    assert payload["hasHits"] is False
    suggestions = [
        c["suggestion"]
        for c in payload["candidates"]
        if c["term"] == "linx"
    ]
    assert "linux" in suggestions
    hit_candidate = next(
        c for c in payload["candidates"] if c["suggestion"] == "linux"
    )
    assert hit_candidate["distance"] == 1
    assert hit_candidate["occurrences"] >= 1

    normal = client.get(SPELL_PATH, params={"q": "linux"}, headers=ab_env["a"]).json()
    assert normal["hasHits"] is True
    assert normal["candidates"] == []


def test_new368_no_auto_replace_contract(ab_env):  # noqa: F811
    """负向契约：提示只是建议 —— 搜索端点对原查询原样执行（零命中
    依旧零命中），绝不悄悄替换。"""
    client = ab_env["client"]
    seed_entry(ab_env, "a", "n368-b", title="linux 内核速览")
    direct = client.get("/api/v1/search", params={"q": "linx"}, headers=ab_env["a"])
    assert direct.status_code == 200
    assert direct.json()["items"] == []  # 未被偷偷替换成 linux 的结果


def test_new368_validation_and_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    assert client.get(SPELL_PATH, params={"q": ""}, headers=ab_env["a"]).status_code == 422
    long_q = client.get(SPELL_PATH, params={"q": "词" * 201}, headers=ab_env["a"])
    assert long_q.status_code == 422  # Query(max_length=200) 校验层拦截

    # 词表来自本人投影：A 的索引对 B 的候选词表不可见。
    seed_entry(ab_env, "a", "n368-c", title="quantum computing notes")
    b_view = client.get(SPELL_PATH, params={"q": "quantm"}, headers=ab_env["b"]).json()
    suggestions = [c["suggestion"] for c in b_view["candidates"]]
    assert "quantum" not in suggestions
    a_view = client.get(SPELL_PATH, params={"q": "quantm"}, headers=ab_env["a"]).json()
    assert "quantum" in [c["suggestion"] for c in a_view["candidates"]]
