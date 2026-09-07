"""RSSHub Gate additions: custom site/route credentials, honest env-file
materialization, detect route shape, and the apply script's env parsing.

Values are synthetic; nothing here touches a real RSSHub instance.
"""

import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.rsshub_control import (
    RssHubCustomCredentialError,
    RssHubCustomCredentialStore,
    render_env_file,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))  # noqa: E402
import apply_rsshub_config as applier  # noqa: E402


def run(coroutine):
    return asyncio.run(coroutine)


def _store(tmp_path) -> tuple[RssHubCustomCredentialStore, Database]:
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    return RssHubCustomCredentialStore(db, SecretsStore(tmp_path / "secrets.json")), db


def test_custom_credential_crud_roundtrip(tmp_path):
    store, _ = _store(tmp_path)
    entry = run(
        store.create(
            name="我的微博",
            domain="Weibo.com/",
            env_key="WEIBO_COOKIES",
            kind="cookie",
            value="SUB=x; SUBP=y",
            route="/weibo/search/hotfest",
        )
    )
    assert entry["configured"] is True
    assert entry["domain"] == "weibo.com"  # normalized
    assert entry["envKey"] == "WEIBO_COOKIES"

    entries = run(store.list_entries())
    assert len(entries) == 1 and entries[0]["configured"] is True

    # value replacement + metadata update
    run(store.set_value(entry["id"], "SUB=rotated"))
    updated = run(store.update_metadata(entry["id"], name="微博（新）"))
    assert updated["name"] == "微博（新）"

    run(store.delete(entry["id"]))
    assert run(store.list_entries()) == []
    with pytest.raises(RssHubCustomCredentialError):
        run(store.set_value(entry["id"], "gone"))


def test_custom_credential_validation(tmp_path):
    store, _ = _store(tmp_path)
    with pytest.raises(RssHubCustomCredentialError):
        run(store.create(name="x", domain="https://weibo.com", env_key="K", kind="cookie", value="v"))
    with pytest.raises(RssHubCustomCredentialError):
        run(store.create(name="x", domain="weibo.com", env_key="lower", kind="cookie", value="v"))
    with pytest.raises(RssHubCustomCredentialError):
        run(store.create(name="x", domain="weibo.com", env_key="WEIBO_COOKIES", kind="nonsense", value="v"))
    with pytest.raises(RssHubCustomCredentialError):
        run(store.create(name="", domain="weibo.com", env_key="WEIBO_COOKIES", kind="cookie", value="v"))
    # duplicate env key
    run(store.create(name="a", domain="weibo.com", env_key="WEIBO_COOKIES", kind="cookie", value="v1"))
    with pytest.raises(RssHubCustomCredentialError):
        run(store.create(name="b", domain="douban.com", env_key="WEIBO_COOKIES", kind="cookie", value="v2"))


def test_render_env_file_includes_values_server_side(tmp_path):
    store, db = _store(tmp_path)
    from lumirss.rsshub_control import RssHubControlStore

    control = RssHubControlStore(db, SecretsStore(tmp_path / "secrets.json"))
    run(
        store.create(
            name="豆瓣",
            domain="douban.com",
            env_key="DOUBAN_COOKIE",
            kind="cookie",
            value="itest-douban-cookie-value",
        )
    )
    custom = await_values = run(store.collect_values())
    content = render_env_file(control, run(control.desired()), await_values)
    assert custom.get("DOUBAN_COOKIE") == "itest-douban-cookie-value"
    assert "DOUBAN_COOKIE=itest-douban-cookie-value" in content
    # secret values of the FIXED schema appear too (server-side only)
    assert "CACHE_TYPE=memory" in content


# ---------------------------------------------------------------------------
# apply script env parsing (host-side safety)
# ---------------------------------------------------------------------------


def test_apply_script_env_parsing(tmp_path):
    env_file = tmp_path / "rsshub.env"
    env_file.write_text(
        "# comment\nCACHE_TYPE=memory\nCACHE_EXPIRE=600\nWEIBO_COOKIES=SUB=abc\n",
        encoding="utf-8",
    )
    values = applier.parse_env_file(env_file)
    assert values["CACHE_EXPIRE"] == "600"
    assert values["WEIBO_COOKIES"] == "SUB=abc"

    bad = tmp_path / "bad.env"
    bad.write_text("rm -rf / = 1\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        applier.parse_env_file(bad)

    newline = tmp_path / "nl.env"
    newline.write_text("UA=foo\nbar\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        applier.parse_env_file(newline)


def test_apply_script_service_allowlist_and_health_url(tmp_path):
    argv = applier.main.__wrapped__ if hasattr(applier.main, "__wrapped__") else None
    assert argv is None
    # service allow-list is enforced
    assert "rsshub" in applier.ALLOWED_SERVICES
    # non-loopback health URLs rejected
    with pytest.raises(SystemExit):
        applier.validate_health_url("http://169.254.169.254/latest")
    with pytest.raises(SystemExit):
        applier.validate_health_url("https://127.0.0.1:1200/healthz")
    applier.validate_health_url("http://127.0.0.1:1200/healthz")  # ok
    applier.validate_health_url("http://localhost:1200/healthz")  # ok


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def _client(tmp_path, monkeypatch) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = tmp_path / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    run(Database(db_path).migrate())
    client = TestClient(app)
    client.__enter__()
    app.state.db = Database(db_path)
    app.state.secrets_store = SecretsStore(data_dir / "secrets.json")
    return client


def test_credentials_routes_and_env_file_endpoint(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        created = client.post(
            "/api/v1/rsshub/credentials",
            json={
                "name": "知乎",
                "domain": "zhihu.com",
                "envKey": "ZHIHU_COOKIES_X",
                "kind": "cookie",
                "value": "d2=b",
                "route": "/zhihu/hot",
            },
        )
        assert created.status_code == 201
        listing = client.get("/api/v1/rsshub/credentials").json()
        assert len(listing) == 1 and listing[0]["configured"] is True
        # secret value never listed
        assert "d2=b" not in str(listing)

        # replace value write-only
        replaced = client.put(
            f"/api/v1/rsshub/credentials/{listing[0]['id']}/value",
            json={"value": "rotated-cookie"},
        )
        assert replaced.status_code == 204

        # env-file materialization (server side, values never in response)
        materialized = client.post("/api/v1/rsshub/config/env-file")
        assert materialized.status_code == 200
        payload = materialized.json()
        assert payload["customCredentialCount"] == 1
        env_path = (
            tmp_path / "data" / payload["dirName"] / payload["fileName"]
        )
        assert env_path.is_file()
        assert oct(env_path.stat().st_mode & 0o777) == "0o600"
        content = env_path.read_text()
        assert "rotated-cookie" in content
        assert "rotated-cookie" not in materialized.text

        # delete
        deleted = client.delete(f"/api/v1/rsshub/credentials/{listing[0]['id']}")
        assert deleted.status_code == 204
        assert client.get("/api/v1/rsshub/credentials").json() == []


def test_detect_route_reports_bounded_candidates(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        response = client.get("/api/v1/rsshub/detect")
        assert response.status_code == 200
        payload = response.json()
        assert payload["configured"] is False
        sources = {c["source"] for c in payload["candidates"]}
        assert sources <= {"configured", "compose-dns", "host-loopback"}
        assert len(payload["candidates"]) <= 3
