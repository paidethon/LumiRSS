"""NEW-261 术语表冲突处理 — 冲突发现、生效译法选择（来源/项目）、
缓存纪律（glossary_version 推进 + 已产生结果不悄悄改变）与 API 行为。

A/B 隔离：术语表与选择都在 per-user 库（ab_env 双成员各写各的，互不可见）。
Provider 全 fake。
"""

import asyncio

import pytest

from lumirss.ai_settings import AiSettingsUpdate
from lumirss.ai_translation import TranslationService
from lumirss.glossary import GlossaryStore, get_glossary_version
from lumirss.new261_glossary_conflicts import (
    GlossaryChoiceInvalid,
    clear_choice,
    effective_terms,
    list_conflicts,
    set_choice,
)
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


# ---------------------------------------------------------------------------
# 模块层：冲突发现 / 选择 / 生效解析
# ---------------------------------------------------------------------------


def _store(db):
    return GlossaryStore(db)


def test_conflicts_detected_when_same_term_has_distinct_definitions(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = _store(db)
    v1 = run(store.create("GraphQL", "一种查询语言"))
    v2 = run(store.create("GraphQL", "图查询规范名"))
    conflicts = run(list_conflicts(db))
    assert len(conflicts) == 1
    group = conflicts[0]
    assert group["term"] == "GraphQL"
    assert {v["termId"] for v in group["variants"]} == {v1["id"], v2["id"]}
    assert group["chosen"] is None


def test_no_conflict_for_identical_definitions_or_unique_terms(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = _store(db)
    run(store.create("GraphQL", "一种查询语言"))
    run(store.create("GraphQL", "一种查询语言"))  # 同词同义：不冲突
    run(store.create("RSSHub", "路由生成器"))  # 唯一词：不冲突
    assert run(list_conflicts(db)) == []


def test_project_choice_resolves_effective_term(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = _store(db)
    v1 = run(store.create("GraphQL", "一种查询语言"))
    v2 = run(store.create("GraphQL", "图查询规范名"))
    choice = run(set_choice(db, "GraphQL", v2["id"], "project"))
    assert choice["scope"] == "project"
    terms = run(effective_terms(db))
    assert terms == [{"term": "GraphQL", "translation": "图查询规范名"}]
    _ = v1


def test_source_choice_beats_project_choice_and_scopes_by_feed(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = _store(db)
    v1 = run(store.create("GraphQL", "一种查询语言"))
    v2 = run(store.create("GraphQL", "图查询规范名"))
    run(set_choice(db, "GraphQL", v1["id"], "project"))
    run(set_choice(db, "GraphQL", v2["id"], "source", "https://a.example/rss"))

    assert run(effective_terms(db, "https://a.example/rss"))[0]["translation"] == (
        "图查询规范名"
    )
    # 其他来源 → 项目选择生效
    assert run(effective_terms(db, "https://b.example/rss"))[0]["translation"] == (
        "一种查询语言"
    )
    # feed_url 未知 → 项目选择
    assert run(effective_terms(db))[0]["translation"] == "一种查询语言"


def test_choice_to_deleted_variant_degrades_to_default(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = _store(db)
    v1 = run(store.create("GraphQL", "一种查询语言"))
    v2 = run(store.create("GraphQL", "图查询规范名"))
    run(set_choice(db, "GraphQL", v2["id"], "project"))
    run(store.delete(v2["id"]))
    terms = run(effective_terms(db))
    assert terms == [{"term": "GraphQL", "translation": str(v1["definition"])}]


def test_choice_validation(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = _store(db)
    v1 = run(store.create("GraphQL", "一种查询语言"))
    run(store.create("RSSHub", "路由生成器"))
    with pytest.raises(GlossaryChoiceInvalid):
        run(set_choice(db, "GraphQL", "glo-nope", "project"))  # 未知词目
    with pytest.raises(GlossaryChoiceInvalid):
        run(set_choice(db, "GraphQL", v1["id"], "galaxy"))  # 非法 scope
    with pytest.raises(GlossaryChoiceInvalid):
        run(set_choice(db, "GraphQL", v1["id"], "source", ""))  # source 缺 URL
    with pytest.raises(GlossaryChoiceInvalid):
        run(set_choice(db, "  ", v1["id"], "project"))  # 空 term
    # 词目属于别的术语 → 拒绝
    other = run(store.create("RSSHub", "路由生成器"))
    with pytest.raises(GlossaryChoiceInvalid):
        run(set_choice(db, "GraphQL", other["id"], "project"))


def test_clear_choice_restores_default_and_reports_missing(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = _store(db)
    v2 = run(store.create("GraphQL", "图查询规范名"))
    run(set_choice(db, "GraphQL", v2["id"], "project"))
    assert run(clear_choice(db, "GraphQL", "project")) is True
    assert run(clear_choice(db, "GraphQL", "project")) is False
    # 默认解析 = updated_at 最新的一条词目（这里只有 v2）
    assert run(effective_terms(db))[0]["translation"] == "图查询规范名"


def test_choice_write_bumps_glossary_version(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    v2 = run(_store(db).create("GraphQL", "图查询规范名"))
    before = run(get_glossary_version(db))
    run(set_choice(db, "GraphQL", v2["id"], "project"))
    assert run(get_glossary_version(db)) != before
    version_after_set = run(get_glossary_version(db))
    run(clear_choice(db, "GraphQL", "project"))
    assert run(get_glossary_version(db)) != version_after_set


# ---------------------------------------------------------------------------
# 生成链路：生效译法进入 prompt；已产生缓存不悄悄改变
# ---------------------------------------------------------------------------


def _article_service(tmp_path, calls):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings_store = None

    from lumirss.ai_settings import AiSettingsStore

    settings_store = AiSettingsStore(db)
    run(settings_store.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")))

    class FakeAdapter:
        async def get_entry(self, item_id):
            class Detail:
                title = "t"
                contentText = "GraphQL is a query language."

            return Detail()

    class FakeTranslationService(TranslationService):
        def __init__(self, database):
            from lumirss.ai_artifacts import GenerationLockPool

            self._db = database
            self._settings = settings_store
            self._adapter = FakeAdapter()
            self._locks = GenerationLockPool()

        async def _provider_factory(self, base_url, model):
            class FakeProvider:
                async def complete(self, messages):
                    calls["prompts"].append(messages)
                    return "t\n"

            return FakeProvider()

    return FakeTranslationService(db), db


def test_effective_definition_enters_generation_prompt(tmp_path):
    calls = {"prompts": []}
    service, db = _article_service(tmp_path, calls)
    store = _store(db)
    v2 = run(store.create("GraphQL", "图查询规范名"))
    run(store.create("GraphQL", "一种查询语言"))
    run(set_choice(db, "GraphQL", v2["id"], "project"))

    from lumirss.entryref import encode_entry_ref

    state = run(service.generate_translation(encode_entry_ref("e1.new261a")))
    assert state.status == "success"
    user_prompt = calls["prompts"][0][-1]["content"]
    assert "GraphQL→图查询规范名" in user_prompt
    assert "GraphQL→一种查询语言" not in user_prompt


# ---------------------------------------------------------------------------
# A/B 隔离：per-user 库，A 的选择对 B 不可见
# ---------------------------------------------------------------------------


def test_ab_glossary_choices_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]

    def make_term(who, term, definition):
        response = client.post(
            "/api/v1/glossary",
            json={"term": term, "definition": definition},
            headers=env[who],
        )
        assert response.status_code == 201, response.text
        return response.json()

    make_term("a", "GraphQL", "一种查询语言")
    make_term("b", "GraphQL", "B 的译法一")
    make_term("b", "GraphQL", "B 的译法二")

    # A 建立项目选择
    chosen = make_term("a", "GraphQL", "A 的生效译法")
    pick = client.post(
        "/api/v1/glossary/conflicts/choice",
        json={"term": "GraphQL", "chosenTermId": chosen["id"], "scope": "project"},
        headers=env["a"],
    )
    assert pick.status_code == 200, pick.text

    a_conflicts = client.get("/api/v1/glossary/conflicts", headers=env["a"])
    b_conflicts = client.get("/api/v1/glossary/conflicts", headers=env["b"])
    assert a_conflicts.status_code == 200
    a_group = a_conflicts.json()["conflicts"][0]
    assert a_group["chosen"]["chosenTermId"] == chosen["id"]
    # B 只看到自己的变体，没有任何选择，也看不到 A 的词目
    b_group = b_conflicts.json()["conflicts"][0]
    assert b_group["chosen"] is None
    assert {v["definition"] for v in b_group["variants"]} == {"B 的译法一", "B 的译法二"}
    assert "A 的生效译法" not in str(b_conflicts.json())


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_client(client):
    """Basic-mode TestClient（conftest client 夹具）+ 术语夹具。"""
    import asyncio

    from lumirss.glossary import GlossaryStore

    async def seed():
        from lumirss.main import app

        store = GlossaryStore(app.state.db)
        v1 = await store.create("GraphQL", "一种查询语言")
        v2 = await store.create("GraphQL", "图查询规范名")
        return v1, v2

    v1, v2 = asyncio.run(seed())
    return client, v1, v2


def test_api_conflicts_choice_and_clear(api_client):
    client, v1, v2 = api_client
    conflicts = client.get("/api/v1/glossary/conflicts")
    assert conflicts.status_code == 200
    group = conflicts.json()["conflicts"][0]
    assert group["term"] == "GraphQL"

    picked = client.post(
        "/api/v1/glossary/conflicts/choice",
        json={"term": "GraphQL", "chosenTermId": v2["id"], "scope": "project"},
    )
    assert picked.status_code == 200
    body = picked.json()
    assert body["chosenTermId"] == v2["id"] and body["scope"] == "project"

    refreshed = client.get("/api/v1/glossary/conflicts").json()["conflicts"][0]
    assert refreshed["chosen"]["chosenTermId"] == v2["id"]

    # 非法：词目与术语不匹配 → 422
    bad = client.post(
        "/api/v1/glossary/conflicts/choice",
        json={"term": "GraphQL", "chosenTermId": "glo-404", "scope": "project"},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "glossary_choice_invalid"

    # source scope 缺 URL → 422
    bad_source = client.post(
        "/api/v1/glossary/conflicts/choice",
        json={"term": "GraphQL", "chosenTermId": v1["id"], "scope": "source"},
    )
    assert bad_source.status_code == 422

    cleared = client.request(
        "DELETE",
        "/api/v1/glossary/conflicts/choice?term=GraphQL&scope=project",
    )
    assert cleared.status_code == 200
    missing = client.request(
        "DELETE",
        "/api/v1/glossary/conflicts/choice?term=GraphQL&scope=project",
    )
    assert missing.status_code == 404
    _ = v1
