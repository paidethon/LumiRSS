"""Route-level tests for the 0018 API wiring (operations + RSSHub control +
backup/WebDAV endpoints). Every test injects a temp database and secrets store
so the real Lumi/FreshRSS/WebDAV state is never touched.
"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


class _StubOperations:
    async def full_status(self):
        return {
            "lumi": {"status": "healthy", "version": "0.1.0"},
            "sqlite": {"status": "healthy", "schemaVersion": 3},
            "freshrss": {"configured": True, "status": "healthy", "latencyMs": 5, "lastCheckedAt": "2026-09-04T00:00:00+00:00", "error": None},
            "rsshub": {"configured": False, "status": "unconfigured", "latencyMs": None, "lastCheckedAt": "2026-09-04T00:00:00+00:00", "error": None},
        }

    async def ready(self):
        return True, {"status": "ok", "components": {"lumi": {"status": "healthy"}, "sqlite": {"status": "healthy"}, "freshrss": "healthy", "rsshub": "unconfigured"}}


def _client(tmp_path):
    """TestClient with injected temp state; returns (client, restore).

    Q-P2-29: every injected double is REVERTED on restore — the stubbed
    operations_service used to outlive this module, so any later test
    reading /api/v1/operations/status (or /health/ready) saw the stub's
    frozen schemaVersion instead of the real migration state."""
    client = TestClient(app)
    client.__enter__()
    previous = {
        "db": app.state.db,
        "secrets_store": app.state.secrets_store,
        "operations_service": app.state.operations_service,
    }
    app.state.db = Database(tmp_path / "lumi.sqlite")
    app.state.secrets_store = SecretsStore(tmp_path / "secrets.json")
    app.state.operations_service = _StubOperations()

    def restore():
        for name, value in previous.items():
            setattr(app.state, name, value)
        client.__exit__(None, None, None)

    return client, restore


def test_health_ready_ok(tmp_path):
    client, restore = _client(tmp_path)
    try:
        response = client.get("/health/ready")
    finally:
        restore()
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_operations_status_shape(tmp_path):
    client, restore = _client(tmp_path)
    try:
        response = client.get("/api/v1/operations/status")
    finally:
        restore()
    assert response.status_code == 200
    body = response.json()
    assert body["lumi"]["status"] == "healthy"
    assert body["rsshub"]["restartRequired"] in (True, False)
    assert "backup" in body


def test_rsshub_config_schema_groups(tmp_path):
    client, restore = _client(tmp_path)
    try:
        response = client.get("/api/v1/rsshub/config")
    finally:
        restore()
    assert response.status_code == 200
    body = response.json()
    groups = {g["id"] for g in body["groups"]}
    assert {"instance", "cache", "network", "access", "browser", "advanced", "credentials"} <= groups
    assert body["pendingCount"] == 0


def test_rsshub_config_patch_and_restart_required(tmp_path):
    client, restore = _client(tmp_path)
    try:
        patched = client.patch("/api/v1/rsshub/config", json={"values": {"CACHE_EXPIRE": 600}})
        assert patched.status_code == 200
        assert patched.json()["pendingCount"] == 1

        rejected = client.patch("/api/v1/rsshub/config", json={"values": {"FAKE": 1}})
        assert rejected.status_code == 400
        assert rejected.json()["error"]["type"] == "rsshub_unknown_key"
    finally:
        restore()


def test_rsshub_secret_write_only(tmp_path):
    client, restore = _client(tmp_path)
    try:
        put = client.put("/api/v1/rsshub/config/secrets/GITHUB_ACCESS_TOKEN", json={"value": "ghp_secret"})
        assert put.status_code == 204
        # GET never returns the value
        config = client.get("/api/v1/rsshub/config").json()
        items = [i for g in config["groups"] for i in g["items"]]
        github = next(i for i in items if i["key"] == "GITHUB_ACCESS_TOKEN")
        assert github["configured"] is True
        assert "ghp_secret" not in str(config)

        deleted = client.delete("/api/v1/rsshub/config/secrets/GITHUB_ACCESS_TOKEN")
        assert deleted.status_code == 204
    finally:
        restore()


def test_rsshub_config_export_has_no_secret(tmp_path):
    client, restore = _client(tmp_path)
    try:
        client.put("/api/v1/rsshub/config/secrets/ACCESS_KEY", json={"value": "supersecret"})
        response = client.get("/api/v1/rsshub/config/export")
        assert response.status_code == 200
        assert "supersecret" not in response.text
        assert "ACCESS_KEY=<configured>" in response.text
    finally:
        restore()


def test_webdav_settings_roundtrip_redacted(tmp_path):
    client, restore = _client(tmp_path)
    try:
        put = client.put(
            "/api/v1/backups/webdav",
            json={"serverUrl": "https://dav.example.com", "username": "alice", "password": "s3cret"},
        )
        assert put.status_code == 200
        body = put.json()
        assert body["passwordConfigured"] is True
        assert "s3cret" not in put.text

        get = client.get("/api/v1/backups/webdav")
        assert get.json()["username"] == "alice"
        assert "s3cret" not in get.text
    finally:
        restore()


def test_webdav_empty_password_does_not_clear(tmp_path):
    client, restore = _client(tmp_path)
    try:
        client.put(
            "/api/v1/backups/webdav",
            json={"serverUrl": "https://dav.example.com", "username": "alice", "password": "s3cret"},
        )
        response = client.put("/api/v1/backups/webdav", json={"password": ""})
        assert response.status_code == 422
        after = client.get("/api/v1/backups/webdav").json()
        assert after["passwordConfigured"] is True
    finally:
        restore()


def test_webdav_invalid_settings_are_400_not_5xx(tmp_path):
    """AUDIT: client-input WebDAV errors are stable 4xx, not the 502 reserved
    for real upstream failures."""
    client, restore = _client(tmp_path)
    try:
        bad_bodies = [
            {"serverUrl": "   "},  # blank
            {"serverUrl": "ftp://dav.example.com"},  # unsupported scheme
            {"serverUrl": "https://user:pass@dav.example.com"},  # credentials in URL
            {"serverUrl": "not-a-url"},  # no scheme/netloc
            {"serverUrl": "https://dav.example.com", "remoteDir": "/a/../../etc"},  # traversal
        ]
        for body in bad_bodies:
            response = client.put("/api/v1/backups/webdav", json=body)
            assert response.status_code == 400, body
            assert response.json()["error"]["type"] == "webdav_invalid_settings", body
    finally:
        restore()


def test_backups_list_empty(tmp_path):
    client, restore = _client(tmp_path)
    try:
        response = client.get("/api/v1/backups")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        restore()
