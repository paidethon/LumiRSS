"""R21 translation-engine migration tests — retired LibreTranslate engine.

The engine enum is now ``ai | browser``. A stored legacy
``translation.engine = libretranslate`` must be rewritten to ``ai`` on
the first AI-settings read, the dead ``translation.libretranslate_*``
config keys removed, and a one-time portable marker
``translationMigratedFromLibre = true`` recorded for the browser's
single "self-hosted translation was removed" notice. Re-running must be
a no-op, and non-libre engines must never be touched.

All upstream network is mocked/not involved: the migration is pure
local SQLite.
"""

import asyncio

from lumirss.ai_settings import AiSettingsStore
from lumirss.app_settings import AppSettingsStore
from lumirss.storage import Database

run = asyncio.run

_ENGINE_KEY = "translation.engine"


def _store(db: Database) -> AiSettingsStore:
    return AiSettingsStore(db)


def _seed(db: Database, key: str, value: str) -> None:
    run(db.migrate())
    run(
        db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) "
            "VALUES (?, ?, '2026-01-01T00:00:00Z') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    )


async def _kv_value(db: Database, key: str) -> str | None:
    row = await db.fetch_one(
        "SELECT value FROM lumi_settings WHERE key = ?", (key,)
    )
    return None if row is None else str(row["value"])


def test_legacy_engine_migrates_to_ai_with_marker(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _seed(db, _ENGINE_KEY, "libretranslate")
    _seed(db, "translation.libretranslate_url", "http://lumirss-libretranslate:5000")
    _seed(db, "translation.libretranslate_status", "ok")

    values = run(_store(db).load())
    # 引擎改写为 ai（读取即观察到迁移结果）
    assert values[_ENGINE_KEY] == "ai"
    # 旧 libretranslate 配置键删除（退役配置，非用户内容）
    assert run(_kv_value(db, "translation.libretranslate_url")) is None
    assert run(_kv_value(db, "translation.libretranslate_status")) is None
    # 一次性提示标记落进 portable 设置
    document, _stored = run(AppSettingsStore(db).load())
    assert document.translationMigratedFromLibre is True
    # 其他用户数据键不受影响
    assert values["ai.model"] == ""


def test_migration_is_idempotent_on_reread(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _seed(db, _ENGINE_KEY, "libretranslate")

    store = _store(db)
    first = run(store.load())
    assert first[_ENGINE_KEY] == "ai"
    document, _stored = run(AppSettingsStore(db).load())
    assert document.translationMigratedFromLibre is True

    # 再跑（新引擎已是 ai）→ 无进一步变化
    second = run(store.load())
    assert second[_ENGINE_KEY] == "ai"
    again, _stored = run(AppSettingsStore(db).load())
    assert again.model_dump() == document.model_dump()
    assert run(_kv_value(db, _ENGINE_KEY)) == "ai"


def test_non_libre_engines_are_never_touched(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _seed(db, _ENGINE_KEY, "browser")
    values = run(_store(db).load())
    assert values[_ENGINE_KEY] == "browser"
    document, _stored = run(AppSettingsStore(db).load())
    # 未迁移用户不带提示标记
    assert document.translationMigratedFromLibre is False

    db2 = Database(tmp_path / "lumi2.sqlite")
    # 默认（从未写过引擎）→ 保持默认 ai，无标记
    values2 = run(_store(db2).load())
    assert values2[_ENGINE_KEY] == "ai"
    document2, _stored = run(AppSettingsStore(db2).load())
    assert document2.translationMigratedFromLibre is False


def test_migrated_engine_flows_through_settings_api(tmp_path, client):
    """API 层：迁移后的读取经 GET /settings/ai 观察到 engine=ai，且
    libretranslate 字段不再出现在视图中。"""
    from lumirss.main import app

    db = app.state.db
    _seed(db, _ENGINE_KEY, "libretranslate")
    _seed(db, "translation.libretranslate_url", "http://lumirss-libretranslate:5000")

    response = client.get("/api/v1/settings/ai")
    assert response.status_code == 200
    body = response.json()
    assert body["translationEngine"] == "ai"
    assert "libretranslateUrl" not in body
    assert "libretranslateStatus" not in body
