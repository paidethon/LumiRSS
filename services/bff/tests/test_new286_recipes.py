"""NEW-286 简报栏目配方 — CRUD / 校验 / 应用到草稿（如实报删除数）。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, iso, seed

SECTIONS = [
    {"key": "top", "label": "要闻", "rule": "starred", "budget": 400},
    {"key": "news", "label": "快讯", "rule": "recent", "budget": 800},
]


def test_recipe_crud(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    a = env["a"]
    created = client.post(
        "/api/v1/briefings/recipes", json={"name": "晨报配方", "sections": SECTIONS}, headers=a
    )
    assert created.status_code == 201, created.text
    recipe = created.json()
    assert [s["key"] for s in recipe["sections"]] == ["top", "news"]
    assert recipe["sections"][0]["budget"] == 400
    recipe_id = recipe["id"]

    fetched = client.get(f"/api/v1/briefings/recipes/{recipe_id}", headers=a)
    assert fetched.status_code == 200
    listed = client.get("/api/v1/briefings/recipes", headers=a).json()
    assert any(r["id"] == recipe_id for r in listed["recipes"])

    updated = client.put(
        f"/api/v1/briefings/recipes/{recipe_id}",
        json={
            "name": "晨报配方 v2",
            "sections": [{"key": "solo", "label": "唯一栏目", "rule": "recent", "budget": 1200}],
        },
        headers=a,
    )
    assert updated.status_code == 200
    assert updated.json()["sections"][0]["key"] == "solo"

    assert client.delete(f"/api/v1/briefings/recipes/{recipe_id}", headers=a).status_code == 204
    assert client.get(f"/api/v1/briefings/recipes/{recipe_id}", headers=a).status_code == 404


def test_recipe_validation(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    a = env["a"]
    cases = [
        {"name": "重复key", "sections": [
            {"key": "x", "label": "一", "rule": "recent", "budget": 400},
            {"key": "x", "label": "二", "rule": "recent", "budget": 400},
        ]},
        {"name": "坏规则", "sections": [
            {"key": "x", "label": "一", "rule": "magic", "budget": 400}
        ]},
        {"name": "feed缺url", "sections": [
            {"key": "x", "label": "一", "rule": "feed", "budget": 400}
        ]},
        {"name": "预算过小", "sections": [
            {"key": "x", "label": "一", "rule": "recent", "budget": 10}
        ]},
        {"name": "", "sections": SECTIONS},
        {"name": "栏目过多",
         "sections": [
             {"key": f"k{i}", "label": f"栏目{i}", "rule": "recent", "budget": 400}
             for i in range(13)
         ]},
    ]
    for payload in cases:
        response = client.post("/api/v1/briefings/recipes", json=payload, headers=a)
        assert response.status_code == 422, f"{payload}: {response.text}"


def test_apply_recipe_to_draft(ab_env):  # noqa: F811
    """套用配方：栏目替换、被移除栏目的条目移除并如实报数。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    recipe_id = client.post(
        "/api/v1/briefings/recipes", json={"name": "精简配方", "sections": [
            {"key": "news", "label": "快讯", "rule": "recent", "budget": 400}
        ]}, headers=a
    ).json()["id"]

    card1 = seed(env, "a", title="留在快讯", published=iso(hours=-5))
    card2 = seed(env, "a", title="随栏目消失", published=iso(hours=-4))
    created = client.post(
        "/api/v1/briefings",
        json={
            "title": "套用前",
            "sections": [
                {"key": "top", "label": "要闻"},
                {"key": "news", "label": "快讯"},
            ],
            "items": [
                {"entryRef": card1["entryRef"], "sectionKey": "news", "title": card1["title"]},
                {"entryRef": card2["entryRef"], "sectionKey": "top", "title": card2["title"]},
            ],
        },
        headers=a,
    )
    assert created.status_code == 201
    issue_id = created.json()["id"]

    applied = client.post(
        f"/api/v1/briefings/{issue_id}/apply-recipe",
        json={"recipeId": recipe_id},
        headers=a,
    )
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert [s["key"] for s in result["sections"]] == ["news"]
    assert [i["sectionKey"] for i in result["items"]] == ["news"]
    assert result["droppedItems"] == 1

    # 已确认期次不可套用
    confirm(client, a, issue_id)
    assert (
        client.post(
            f"/api/v1/briefings/{issue_id}/apply-recipe",
            json={"recipeId": recipe_id},
            headers=a,
        ).status_code
        == 409
    )


def test_apply_recipe_would_empty_rejected(ab_env):  # noqa: F811
    """套用会清空全部条目 → 422（不允许静默做成空刊）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    recipe_id = client.post(
        "/api/v1/briefings/recipes", json={"name": "无关配方", "sections": [
            {"key": "other", "label": "别的", "rule": "recent", "budget": 400}
        ]}, headers=a
    ).json()["id"]
    card = seed(env, "a", title="唯一条目", published=iso(hours=-5))
    issue_id = create_issue(client, a, title="只有要闻", cards=[card]).json()["id"]
    response = client.post(
        f"/api/v1/briefings/{issue_id}/apply-recipe",
        json={"recipeId": recipe_id},
        headers=a,
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "invalid_briefing_payload"


def test_cross_user_recipes_isolated(ab_env):  # noqa: F811
    """A 的配方对 B 404；B 建同名配方互不影响。"""
    env = ab_env
    client = env["client"]
    recipe_id = client.post(
        "/api/v1/briefings/recipes", json={"name": "A 配方", "sections": SECTIONS}, headers=env["a"]
    ).json()["id"]
    assert (
        client.get(f"/api/v1/briefings/recipes/{recipe_id}", headers=env["b"]).status_code
        == 404
    )
    b_list = client.get("/api/v1/briefings/recipes", headers=env["b"]).json()
    assert all(r["id"] != recipe_id for r in b_list["recipes"])
    assert (
        client.delete(f"/api/v1/briefings/recipes/{recipe_id}", headers=env["b"]).status_code
        == 404
    )
