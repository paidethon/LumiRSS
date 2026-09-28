"""FIX-196 / FIX-204：回滚清单钉住「实际在跑」的镜像 + 快照时刻 schema。

FIX-204：./lumirss snapshot_for_rollback 现在把快照时刻 RUNNING 容器的
镜像 ID（可变 tag 会漂移，运行容器的镜像 ID 才是事实）与
preUpdateSchemaVersion 写进 rollback manifest；本文件验证 BFF 侧对这些
新字段的读取口径（只透传、类型不对如实 None、旧格式清单语义不变）。

FIX-196：GET /admin/rollback-readiness 的响应以纯增量字段暴露这些事实
（previousImage.imageIdBff/imageIdWeb/imageIdsPinned、schema.preUpdate），
canRollback 的三要素语义完全不变；admin 端点本身零改动（OpenAPI 无漂移）。

边界（红线不动）：本端点只有清单，没有任何回滚执行控件。
"""

import asyncio
import json
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app
from lumirss.rollback_readiness import (
    build_rollback_readiness,
    read_rollback_manifest,
)

PASSWORD = "rollback-" + _secrets.token_urlsafe(9)
ROLLBACK_SCHEMA = "lumirss-rollback-manifest/v1"

ID_BFF = "sha256:" + "a" * 64
ID_WEB = "sha256:" + "b" * 64


def _write_manifest(path, document: dict) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _full_manifest(tag: str = "v2.0.0") -> dict:
    return {
        "schema": ROLLBACK_SCHEMA,
        "previousImageTag": tag,
        "previousImageIdBff": ID_BFF,
        "previousImageIdWeb": ID_WEB,
        "preUpdateSchemaVersion": 139,
        "runId": "run-abc123",
        "writtenAt": "2026-09-28T00:00:00+00:00",
    }


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_ROLLBACK_MANIFEST_FILE", "")
    monkeypatch.setenv("LUMIRSS_BACKUP_DIR", "")
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    with TestClient(app, base_url="http://lumirss.test") as client:
        async def _set_password():
            from lumirss.storage import Database

            database = Database(tmp_path / "lumi.sqlite")
            await database.migrate()
            store = AccountsStore(database)
            owner = next(
                row
                for row in await store.list_users(limit=50)
                if row["role"] == "owner"
            )
            await store.set_password_hash(str(owner["id"]), hash_password(PASSWORD))

        asyncio.run(_set_password())
        response = client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
        )
        assert response.status_code == 200
        headers = {"cookie": response.headers["set-cookie"].split(";")[0]}
        yield {"client": client, "headers": headers, "db_path": tmp_path}


# ---- FIX-204：清单读取口径 -----------------------------------------------------


def test_read_manifest_surfaces_pinned_ids_and_schema(tmp_path):
    manifest = tmp_path / "rollback-manifest.json"
    _write_manifest(manifest, _full_manifest())
    data = read_rollback_manifest(str(manifest))
    assert data["state"] == "present"
    assert data["previousImageTag"] == "v2.0.0"
    assert data["previousImageIdBff"] == ID_BFF
    assert data["previousImageIdWeb"] == ID_WEB
    assert data["preUpdateSchemaVersion"] == 139
    assert data["runId"] == "run-abc123"
    assert data["writtenAt"] == "2026-09-28T00:00:00+00:00"


def test_read_manifest_legacy_format_defaults_to_none(tmp_path):
    """旧格式清单（FIX-204 之前只有 tag）：state 仍 present，新字段如实 None。"""
    manifest = tmp_path / "rollback-manifest.json"
    _write_manifest(
        manifest,
        {
            "schema": ROLLBACK_SCHEMA,
            "previousImageTag": "v1.2.2",
            "writtenAt": "2026-09-25T00:00:00+00:00",
        },
    )
    data = read_rollback_manifest(str(manifest))
    assert data["state"] == "present"
    assert data["previousImageTag"] == "v1.2.2"
    assert data["previousImageIdBff"] is None
    assert data["previousImageIdWeb"] is None
    assert data["preUpdateSchemaVersion"] is None
    assert data["runId"] is None


def test_read_manifest_rejects_wrong_typed_new_fields(tmp_path):
    """类型不对的新字段（bool 冒充 int、int 冒充 ID）如实降级为 None，
    不抛出、不冒充事实；tag 仍有效。"""
    manifest = tmp_path / "rollback-manifest.json"
    _write_manifest(
        manifest,
        {
            "schema": ROLLBACK_SCHEMA,
            "previousImageTag": "v9",
            "previousImageIdBff": 12345,
            "previousImageIdWeb": True,
            "preUpdateSchemaVersion": "139",
        },
    )
    data = read_rollback_manifest(str(manifest))
    assert data["state"] == "present"
    assert data["previousImageIdBff"] is None
    assert data["previousImageIdWeb"] is None
    assert data["preUpdateSchemaVersion"] is None


def test_read_manifest_absent_states_carry_no_fabricated_fields(tmp_path):
    assert read_rollback_manifest("")["state"] == "absent"
    assert read_rollback_manifest(str(tmp_path / "missing.json"))["state"] == "absent"
    bad = tmp_path / "bad.json"
    bad.write_text("not-json")
    data = read_rollback_manifest(str(bad))
    assert data["state"] == "absent"
    # absent 形状稳定：新字段键存在且为 None（响应形状不随状态分支漂移）。
    for key in ("previousImageIdBff", "previousImageIdWeb", "preUpdateSchemaVersion"):
        assert data[key] is None


# ---- FIX-196：端点增量字段 + canRollback 语义不变 -------------------------------


def test_readiness_exposes_pinned_ids_and_preupdate_schema(env, monkeypatch):
    manifest_file = env["db_path"] / "rollback-manifest.json"
    _write_manifest(manifest_file, _full_manifest())
    monkeypatch.setenv("LUMIRSS_ROLLBACK_MANIFEST_FILE", str(manifest_file))
    body = env["client"].get(
        "/api/v1/admin/rollback-readiness", headers=env["headers"]
    ).json()
    assert body["previousImage"]["state"] == "present"
    assert body["previousImage"]["tag"] == "v2.0.0"
    assert body["previousImage"]["imageIdBff"] == ID_BFF
    assert body["previousImage"]["imageIdWeb"] == ID_WEB
    assert body["previousImage"]["imageIdsPinned"] is True
    assert body["schema"]["preUpdate"] == 139
    # 仍然只有清单：没有执行控件。
    assert "execute" not in json.dumps(body).lower()


def test_readiness_legacy_manifest_keeps_canrollback_semantics(env, monkeypatch):
    """旧格式清单：新字段为 None / False，三要素 canRollback 语义不变。"""
    backup_dir = env["db_path"] / "backups"
    backup_dir.mkdir()
    manifest_file = env["db_path"] / "rollback-manifest.json"
    _write_manifest(
        manifest_file,
        {
            "schema": ROLLBACK_SCHEMA,
            "previousImageTag": "v1.2.2",
            "writtenAt": "2026-09-25T00:00:00+00:00",
        },
    )
    monkeypatch.setenv("LUMIRSS_ROLLBACK_MANIFEST_FILE", str(manifest_file))
    monkeypatch.setenv("LUMIRSS_BACKUP_DIR", str(backup_dir))
    body = env["client"].get(
        "/api/v1/admin/rollback-readiness", headers=env["headers"]
    ).json()
    assert body["previousImage"]["imageIdsPinned"] is False
    assert body["previousImage"]["imageIdBff"] is None
    assert body["schema"]["preUpdate"] is None
    # 备份缺失（目录里没有 *.backup）→ canRollback 仍诚实为 False。
    assert body["backup"]["state"] == "absent"
    assert body["canRollback"] is False


def test_build_rollback_readiness_additive_fields_do_not_flip_verdict():
    """纯函数：清单带钉住 ID 时 canRollback 判定与不带时完全一致。"""
    base = {
        "backup_report": {"ok": True, "findings": {}},
        "backup_name": "b.backup",
        "current_schema_version": 139,
        "backup_schema_version": 139,
        "backup_dir_configured": True,
    }
    legacy = dict(base, manifest={"state": "present", "previousImageTag": "v1", "reason": None})
    pinned = dict(
        base,
        manifest={
            "state": "present",
            "previousImageTag": "v1",
            "previousImageIdBff": ID_BFF,
            "previousImageIdWeb": ID_WEB,
            "preUpdateSchemaVersion": 139,
            "reason": None,
        },
    )
    without_ids = build_rollback_readiness(**legacy)
    with_ids = build_rollback_readiness(**pinned)
    assert without_ids["canRollback"] is True
    assert with_ids["canRollback"] is True
    assert with_ids["previousImage"]["imageIdsPinned"] is True
    assert with_ids["previousImage"]["imageIdBff"] == ID_BFF
    assert with_ids["schema"]["preUpdate"] == 139
    # schema 漂移的判定同样不受新字段影响。
    drift = build_rollback_readiness(**dict(pinned, backup_schema_version=122))
    assert drift["canRollback"] is False
    assert drift["schema"]["unchanged"] is False
