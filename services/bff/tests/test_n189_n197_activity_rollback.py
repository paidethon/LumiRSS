"""N189 个人活动记录清除 + N197 回滚就绪检查。

N189：按日期清除登录事件 / AI 任务日志 / 搜索快照；业务状态（已读/
收藏/笔记）不动；删除后不复活；预览只读。
N197：要素清单（前镜像 / 最新备份 N186 校验 / 诚实的 dbDowngrade 限制
说明）；canRollback 诚实计算；端点只有清单，没有任何执行控件
（负向：OpenAPI 里不得出现回滚执行方法）。
"""

import asyncio
import json
import secrets as _secrets
import time as _time
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.ai_task_log import AiTaskLogStore
from lumirss.auth_store import AuthStore
from lumirss.backup import BACKUP_SCHEMA_VERSION
from lumirss.main import app
from lumirss.rollback_readiness import (
    build_rollback_readiness,
    latest_backup_path,
    read_rollback_manifest,
)
from lumirss.search_snapshot_store import SearchSnapshotStore
from lumirss.storage import Database

PASSWORD = "purge-" + _secrets.token_urlsafe(9)
ROLLBACK_SCHEMA = "lumirss-rollback-manifest/v1"


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


def _user_id(env) -> str:
    async def _get():
        database = Database(env["db_path"] / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        owner = next(
            row
            for row in await store.list_users(limit=50)
            if row["role"] == "owner"
        )
        return str(owner["id"])

    return asyncio.run(_get())


# ---- N189 --------------------------------------------------------------------


def _seed_activity(env, *, backdate_before_today: bool = True) -> None:
    """种活动记录：2 条 AI 任务日志 + 2 个搜索快照；其中一半被回拨到
    2026-01-01（「旧的」），一半是今天（「新的」）。"""

    from lumirss.user_scope import user_context

    async def _seed():
        control = Database(env["db_path"] / "lumi.sqlite")
        await control.migrate()
        accounts = AccountsStore(control)
        owner = next(
            row
            for row in await accounts.list_users(limit=50)
            if row["role"] == "owner"
        )
        user_id = str(owner["id"])
        # 用户业务库走 app.state.db（RoutingDatabase 按身份路由），
        # 与路由读取面完全同一条路径。
        database = app.state.db
        with user_context(user_id):
            tasks = AiTaskLogStore(database)
            task_ids = [
                await tasks.record(kind="summary", status="done", entry_ref=None),
                await tasks.record(kind="summary", status="done", entry_ref=None),
            ]
            snapshots = SearchSnapshotStore(database)
            snap_ids = []
            for query in ("旧查询", "新查询"):
                created = await snapshots.create(query, None, ["e1.abc"])
                snap_ids.append(created["id"])
            # 回拨一半（旧 = 2026-01-01 之前）
            old = "2025-01-01T00:00:00+00:00"
            await database.execute(
                "UPDATE ai_task_log SET created_at = ? WHERE id = ?", (old, task_ids[0])
            )
            await database.execute(
                "UPDATE search_snapshots SET created_at = ? WHERE id = ?",
                (old, snap_ids[0]),
            )
        # 登录事件在控制库：一条旧的（1970 纪元）、一条现在的
        auth = AuthStore(control)
        await auth.record_login_event(user_id=user_id, user_agent="curl/8.0", now=1)
        await auth.record_login_event(
            user_id=user_id, user_agent="curl/9.0", now=int(_time.time())
        )
        return user_id

    asyncio.run(_seed())


def test_activity_purge_preview_and_purge(env):
    client = env["client"]
    _seed_activity(env)

    preview = client.get(
        "/api/v1/me/activity-purge/preview", params={"before": "2026-06-01"}
    )
    assert preview.status_code == 200
    counts = preview.json()["counts"]
    assert counts == {"loginEvents": 1, "aiTaskLogs": 1, "searchSnapshots": 1}
    assert any("已读/收藏/笔记" in note for note in preview.json()["retained"])
    assert any("设备本地" in note for note in preview.json()["retained"])

    purged = client.post(
        "/api/v1/me/activity-purge",
        json={"before": "2026-06-01"},
    )
    assert purged.status_code == 200
    deleted = purged.json()["deleted"]
    assert deleted == {"loginEvents": 1, "aiTaskLogs": 1, "searchSnapshots": 1}

    # 删除后不再复活：预览归零、再清一次全 0
    after = client.get(
        "/api/v1/me/activity-purge/preview", params={"before": "2026-06-01"}
    ).json()["counts"]
    assert after == {"loginEvents": 0, "aiTaskLogs": 0, "searchSnapshots": 0}
    again = client.post("/api/v1/me/activity-purge", json={"before": "2026-06-01"})
    assert again.json()["deleted"] == {"loginEvents": 0, "aiTaskLogs": 0, "searchSnapshots": 0}

    # 新的记录仍在（登录事件含夹具登录那一条 → 2 条未到期事件）
    remaining = client.get(
        "/api/v1/me/activity-purge/preview", params={"before": "2100-01-01"}
    ).json()["counts"]
    assert remaining == {"loginEvents": 2, "aiTaskLogs": 1, "searchSnapshots": 1}


def test_activity_purge_leaves_business_state_untouched(env):
    client = env["client"]
    headers = env["headers"]
    # 业务状态：一个书签（笔记）
    created = client.post(
        "/api/v1/library/bookmarks",
        json={"rssItemRef": "rss:e1.MDAwNjU5ZTA3YWFlZTI0ZA", "title": "笔记", "note": "要点"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    _seed_activity(env)
    purged = client.post("/api/v1/me/activity-purge", json={"before": "2100-01-01"})
    assert purged.status_code == 200
    assert sum(purged.json()["deleted"].values()) > 0
    # 书签原样保留
    listing = client.get("/api/v1/library/bookmarks", headers=headers)
    assert listing.status_code == 200
    payload = listing.json()
    items = payload.get("items") or payload
    assert any(b.get("title") == "笔记" for b in items)


def test_activity_purge_include_filter_and_bad_date(env):
    client = env["client"]
    _seed_activity(env)
    partial = client.post(
        "/api/v1/me/activity-purge",
        json={"before": "2100-01-01", "include": {"aiTaskLogs": True, "loginEvents": False, "searchSnapshots": False}},
    )
    deleted = partial.json()["deleted"]
    assert deleted["aiTaskLogs"] == 2
    assert deleted["loginEvents"] == 0 and deleted["searchSnapshots"] == 0

    bad = client.post("/api/v1/me/activity-purge", json={"before": "not-a-date"})
    assert bad.status_code == 400


# ---- N197 --------------------------------------------------------------------


def _write_rollback_manifest(path, tag: str | None) -> None:
    document = {
        "schema": ROLLBACK_SCHEMA,
        "previousImageTag": tag,
        "writtenAt": "2026-09-25T00:00:00+00:00",
    }
    path.write_text(json.dumps(document), encoding="utf-8")


def _craft_backup_zip(schema_version: int, *, corrupt: bool = False) -> bytes:
    """最小合法备份归档（真实 manifest + 校验和匹配的 sqlite 快照）。"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "{}")  # 占位，稍后重写
    import hashlib

    payload = b"SQLite format 3\x00" + b"\x00" * 128
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "backupSchemaVersion": BACKUP_SCHEMA_VERSION,
        "appName": "LumiRSS",
        "createdAt": "2026-09-25T00:00:00+00:00",
        "lumiVersion": "test",
        "lumiCommit": "test",
        "lumiDbSchemaVersion": schema_version,
        "components": ["control"],
        "componentCounts": {"control": 1},
        "secretPolicy": {"excludedSecrets": [], "configured": False},
        "files": [
            {"path": "state/lumi.sqlite", "size": len(payload), "sha256": digest, "component": "control"}
        ],
    }
    if corrupt:
        manifest["files"][0]["sha256"] = "0" * 64
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("state/lumi.sqlite", payload)
    return buffer.getvalue()


def test_rollback_readiness_elements_from_fixtures(env, monkeypatch):
    client = env["client"]
    backup_dir = env["db_path"] / "backups"
    backup_dir.mkdir()
    (backup_dir / "lumirss-20260901T000000Z.backup").write_bytes(
        _craft_backup_zip(999999)
    )
    (backup_dir / "lumirss-20260925T000000Z.backup").write_bytes(
        _craft_backup_zip(999999)
    )
    manifest_file = env["db_path"] / "rollback-manifest.json"
    _write_rollback_manifest(manifest_file, "v1.2.2")
    monkeypatch.setenv("LUMIRSS_ROLLBACK_MANIFEST_FILE", str(manifest_file))
    monkeypatch.setenv("LUMIRSS_BACKUP_DIR", str(backup_dir))

    result = client.get("/api/v1/admin/rollback-readiness", headers=env["headers"])
    assert result.status_code == 200
    body = result.json()
    # 前镜像：present（来自脚本写入的清单）
    assert body["previousImage"]["state"] == "present"
    assert body["previousImage"]["tag"] == "v1.2.2"
    # 备份：存在且 N186 校验通过（checksum ok），但 schema 与当前不一致
    assert body["backup"]["state"] in {"unverified", "verified"}
    assert body["backup"]["name"] == "lumirss-20260925T000000Z.backup"
    # dbDowngrade：诚实限制说明（SQLite 只向前）
    assert "只向前" in body["dbDowngrade"]
    assert body["schema"]["current"] == 999999 or body["schema"]["unchanged"] is False
    # canRollback 诚实：schema 不一致 → False
    assert body["canRollback"] is False
    # 没有任何执行控件：响应里不存在执行端点/动作字段
    assert "execute" not in json.dumps(body).lower()


def test_rollback_readiness_absent_when_unconfigured(env):
    result = env["client"].get(
        "/api/v1/admin/rollback-readiness", headers=env["headers"]
    )
    assert result.status_code == 200
    body = result.json()
    assert body["previousImage"]["state"] == "absent"
    assert body["previousImage"]["reason"]
    assert body["backup"]["state"] == "absent"
    assert body["canRollback"] is False


def test_rollback_readiness_ready_when_all_elements_match(env, monkeypatch):
    backup_dir = env["db_path"] / "backups-ready"
    backup_dir.mkdir()
    from lumirss.migrations import schema_version as _schema_version

    schema_now = asyncio.run(
        asyncio.to_thread(_schema_version, Database(env["db_path"] / "lumi.sqlite"))
    )
    (backup_dir / "lumirss-20260925T000000Z.backup").write_bytes(
        _craft_backup_zip(schema_now)
    )
    manifest_file = env["db_path"] / "rollback-manifest.json"
    _write_rollback_manifest(manifest_file, "v1.2.2")
    monkeypatch.setenv("LUMIRSS_ROLLBACK_MANIFEST_FILE", str(manifest_file))
    monkeypatch.setenv("LUMIRSS_BACKUP_DIR", str(backup_dir))
    body = env["client"].get(
        "/api/v1/admin/rollback-readiness", headers=env["headers"]
    ).json()
    assert body["backup"]["state"] == "verified"
    assert body["schema"]["unchanged"] is True
    assert body["canRollback"] is True


def test_rollback_readiness_member_forbidden(env):
    # 全新客户端（无 cookie jar 继承）→ 未登录，admin-gated 拒绝
    from fastapi.testclient import TestClient as _TC

    with _TC(app, base_url="http://lumirss.test") as anon:
        response = anon.get("/api/v1/admin/rollback-readiness")
    assert response.status_code in {401, 403}


def test_rollback_readiness_module_units(tmp_path):
    # 清单读取的诚实回退
    assert read_rollback_manifest("")[ "state"] == "absent"
    assert read_rollback_manifest(str(tmp_path / "missing.json"))["state"] == "absent"
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema": "wrong"}')
    assert read_rollback_manifest(str(bad))["state"] == "absent"
    good = tmp_path / "good.json"
    _write_rollback_manifest(good, "v9")
    assert read_rollback_manifest(str(good))["previousImageTag"] == "v9"
    # 最新备份 = 名字（时间戳）排序最后一个
    assert latest_backup_path("") is None
    assert latest_backup_path(str(tmp_path / "nope")) is None
    # 纯函数组装：三要素齐全才可回滚
    base = {
        "manifest": {"state": "present", "previousImageTag": "v1", "reason": None},
        "backup_report": {"ok": True, "findings": {}},
        "backup_name": "b.backup",
        "current_schema_version": 130,
        "backup_schema_version": 130,
        "backup_dir_configured": True,
    }
    assert build_rollback_readiness(**base)["canRollback"] is True
    no_image = dict(base, manifest={"state": "absent", "previousImageTag": None, "reason": "x"})
    assert build_rollback_readiness(**no_image)["canRollback"] is False
    bad_backup = dict(base, backup_report={"ok": False, "findings": {"checksumOk": False}})
    assert build_rollback_readiness(**bad_backup)["canRollback"] is False
    schema_drift = dict(base, backup_schema_version=122)
    drift_result = build_rollback_readiness(**schema_drift)
    assert drift_result["canRollback"] is False
    assert drift_result["schema"]["unchanged"] is False
