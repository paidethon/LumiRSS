"""N010 个人数据迁出/迁入向导 — zip 组件、范围预览、导入合并。

覆盖：导出 zip 的组件形状与「绝无秘密」；导出→导入到全新用户的
roundtrip（书签/标签/批注/工作区/日报配置）；冲突=已存在跳过
（skip-existing）；readingState 在无 RSS 绑定时的诚实降级。
"""

import asyncio
import io
import json
import secrets as _secrets
import zipfile

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app
from lumirss.storage import Database

PASSWORD = "wiz-" + _secrets.token_urlsafe(9)
OWNER = "owner"
A_USER = "alice" + _secrets.token_hex(3)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
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
        owner_login = client.post(
            "/api/v1/auth/login", json={"username": OWNER, "password": PASSWORD}
        )
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = client.post(
            "/api/v1/admin/invites", json={"label": A_USER}, headers=owner_headers
        )
        token = invite.json()["token"]
        activation = client.post(
            "/api/v1/auth/activate",
            json={"token": token, "username": A_USER, "password": PASSWORD},
        )
        assert activation.status_code == 200, activation.text
        a_headers = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        yield {
            "client": client,
            "owner": owner_headers,
            "a": a_headers,
            "db_path": tmp_path,
        }


def _owner_id(env) -> str:
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


def _seed_owner_data(env) -> None:
    client = env["client"]
    headers = env["owner"]
    ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"
    assert (
        client.post(
            "/api/v1/library/bookmarks",
            json={"rssItemRef": f"rss:{ref}", "title": "迁移书签", "note": "要点"},
            headers=headers,
        ).status_code
        == 201
    )
    # 标签绑定直接走 store（API 的 assign 要求引用可解析——需要 RSS 绑定，
    # 本套件不触网；标签数据本身在 Lumi 每用户库里）。
    from lumirss.tags import TagStore
    from lumirss.user_scope import user_context

    owner_uid = _owner_id(env)

    async def _seed_tag():
        with user_context(owner_uid):
            await TagStore(app.state.db).attach(f"rss:{ref}", "迁移标签")

    asyncio.run(_seed_tag())
    assert (
        client.post(
            "/api/v1/annotations",
            json={
                "entryRef": ref,
                "anchor": {"start": 0, "end": 4, "text": "正文"},
                "excerpt": "正文前四个字",
                "note": "迁移批注",
            },
            headers=headers,
        ).status_code
        in {200, 201}
    )
    assert (
        client.post(
            "/api/v1/workspaces",
            json={"name": "迁移工作区", "description": "N010"},
            headers=headers,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/gpt-digest/configs",
            json={"name": "迁移日报", "slots": [8, 20]},
            headers=headers,
        ).status_code
        == 201
    )


def _export_zip(env) -> bytes:
    response = env["client"].get("/api/v1/export/lumi-data.zip", headers=env["owner"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    return response.content


def test_scope_lists_component_counts_before_export(env):
    _seed_owner_data(env)
    scope = env["client"].get("/api/v1/export/lumi-data/scope", headers=env["owner"])
    assert scope.status_code == 200
    components = {c["key"]: c for c in scope.json()["components"]}
    assert components["bookmarks"]["count"] == 1
    assert components["tags"]["count"] == 1
    assert components["annotations"]["count"] == 1
    # 工作区 = 稍后读（保留）+ 新建的那个
    assert components["workspaces"]["count"] == 2
    # 日报配置 = 默认配置（id=1）+ 新建的那个
    assert components["digest"]["count"] == 2
    # 无 RSS 绑定：sources / readingState 诚实 unavailable（绝不冒充空集）
    assert components["sources"]["available"] is False
    assert components["readingState"]["available"] is False
    assert components["sources"]["reason"]


def test_export_zip_shape_and_no_secrets(env):
    _seed_owner_data(env)
    data = _export_zip(env)
    archive = zipfile.ZipFile(io.BytesIO(data))
    names = set(archive.namelist())
    assert "manifest.json" in names
    assert {
        "sources.json",
        "readingState.json",
        "annotations.json",
        "tags.json",
        "workspaces.json",
        "bookmarks.json",
        "digest.json",
    } <= names
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["kind"] == "lumirss-lumi-data"
    assert manifest["schema"] == "lumirss-lumi-data-wizard/v1"
    assert manifest["components"]["bookmarks"] == 1
    # 绝无秘密：全包文本不含任何 key/密码/token 形态字段
    blob = b"".join(archive.read(n) for n in names).decode("utf-8").lower()
    for banned in ("api_key", "apikey", "password", "token", "secret", "凭据"):
        assert banned not in blob, banned


def test_import_roundtrip_into_fresh_user_then_skip_existing(env):
    _seed_owner_data(env)
    data = _export_zip(env)

    # A（全新用户）preview：各组件计数、冲突 0
    preview = env["client"].post(
        "/api/v1/import/lumi-data/preview",
        content=data,
        headers={**env["a"], "content-type": "application/zip"},
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    import_id = payload["importId"]
    by_key = {c["key"]: c for c in payload["components"]}
    assert by_key["bookmarks"]["count"] == 1 and by_key["bookmarks"]["conflicts"] == 0
    assert by_key["annotations"]["count"] == 1 and by_key["annotations"]["conflicts"] == 0
    assert by_key["digest"]["count"] == 2 and by_key["digest"]["conflicts"] == 0

    # A apply：合并全部内容组件
    apply = env["client"].post(
        "/api/v1/import/lumi-data/apply",
        json={
            "importId": import_id,
            "components": ["bookmarks", "tags", "annotations", "workspaces", "digest"],
        },
        headers=env["a"],
    )
    assert apply.status_code == 200, apply.text
    results = apply.json()["components"]
    assert results["bookmarks"]["added"] == 1
    assert results["annotations"]["added"] == 1
    assert results["workspaces"]["added"] == 1
    # 默认配置（同名"默认日报"）被跳过，只加新的「迁移日报」
    assert results["digest"]["added"] == 1 and results["digest"]["skipped"] >= 1

    # A 真实可见（每用户库隔离：数据落在 A 的库里）
    a_bookmarks = env["client"].get("/api/v1/library/bookmarks", headers=env["a"]).json()
    items = a_bookmarks.get("items") or a_bookmarks
    assert any(b.get("title") == "迁移书签" for b in items)
    a_tags = env["client"].get("/api/v1/tags", headers=env["a"]).json()
    tag_items = a_tags.get("items") or a_tags.get("tags") or a_tags
    assert json.dumps(tag_items, ensure_ascii=False).find("迁移标签") >= 0
    a_annotations = env["client"].get("/api/v1/annotations", headers=env["a"]).json()
    ann_items = a_annotations.get("items") or a_annotations
    assert any(a.get("note") == "迁移批注" for a in ann_items)

    # 再来一轮：preview 冲突 = 已存在；apply 全部跳过（skip-existing）
    preview2 = env["client"].post(
        "/api/v1/import/lumi-data/preview",
        content=data,
        headers={**env["a"], "content-type": "application/zip"},
    ).json()
    by_key2 = {c["key"]: c for c in preview2["components"]}
    assert by_key2["bookmarks"]["conflicts"] == 1
    assert by_key2["annotations"]["conflicts"] == 1
    apply2 = env["client"].post(
        "/api/v1/import/lumi-data/apply",
        json={
            "importId": preview2["importId"],
            "components": ["bookmarks", "annotations", "digest"],
        },
        headers=env["a"],
    ).json()["components"]
    assert apply2["bookmarks"]["added"] == 0 and apply2["bookmarks"]["skipped"] == 1
    assert apply2["annotations"]["added"] == 0 and apply2["annotations"]["skipped"] == 1
    assert apply2["digest"]["added"] == 0 and apply2["digest"]["skipped"] == 2


def test_import_reading_state_honest_without_binding(env):
    data = _export_zip(env)
    preview = env["client"].post(
        "/api/v1/import/lumi-data/preview",
        content=data,
        headers={**env["a"], "content-type": "application/zip"},
    ).json()
    apply = env["client"].post(
        "/api/v1/import/lumi-data/apply",
        json={"importId": preview["importId"], "components": ["readingState", "sources"]},
        headers=env["a"],
    )
    assert apply.status_code == 200
    results = apply.json()["components"]
    # 无 RSS 绑定：诚实失败计数 + 原因，绝不冒充成功
    assert results["readingState"]["applied"] == 0
    assert results["readingState"]["reason"]
    assert results["sources"]["added"] == 0
    assert results["sources"]["reason"]


def test_import_rejects_bad_zip_and_unknown_session(env):
    bad = env["client"].post(
        "/api/v1/import/lumi-data/preview",
        content=b"not a zip",
        headers={**env["a"], "content-type": "application/zip"},
    )
    assert bad.status_code == 400
    unknown = env["client"].post(
        "/api/v1/import/lumi-data/apply",
        json={"importId": "imp-does-not-exist", "components": ["bookmarks"]},
        headers=env["a"],
    )
    assert unknown.status_code == 404
