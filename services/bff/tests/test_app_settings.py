"""Tests for the portable app settings API (0017 Gate 3/6).

All tests use a temp database injected onto app.state.db — no real Lumi
SQLite file is ever touched. The portable settings carry no secrets by
design; assertions focus on allow-list behavior, strict validation,
durability and the FreshRSS ownership boundary.
"""

import secrets as _secrets
import sqlite3

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database

# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
SMUGGLED_KEY = "sk-" + _secrets.token_urlsafe(8)


def _client(db_path):
    """A TestClient with a temp database injected (lifespan resets state)."""
    return TestClient(app), db_path


def test_settings_revision_round_trip_and_conflict(tmp_path):
    """0021: GET exposes a revision; PATCH with the matching baseRevision
    succeeds and bumps it; a stale baseRevision is refused with the stable
    409 app_settings_conflict; omitting baseRevision stays last-write-wins."""
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")

        first = client.get("/api/v1/settings").json()
        assert isinstance(first["revision"], int) and first["revision"] >= 0

        patched = client.patch(
            "/api/v1/settings",
            json={"themeMode": "dark", "baseRevision": first["revision"]},
        )
        assert patched.status_code == 200
        second = patched.json()
        assert second["themeMode"] == "dark"
        assert second["revision"] != first["revision"]

        # Stale baseRevision → stable 409, nothing applied.
        stale = client.patch(
            "/api/v1/settings",
            json={"themeMode": "light", "baseRevision": first["revision"]},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["type"] == "app_settings_conflict"
        assert client.get("/api/v1/settings").json()["themeMode"] == "dark"

        # Current baseRevision → accepted.
        fresh = client.patch(
            "/api/v1/settings",
            json={"themeMode": "light", "baseRevision": second["revision"]},
        )
        assert fresh.status_code == 200
        assert fresh.json()["themeMode"] == "light"

        # No baseRevision (older client) → last-write-wins as before.
        legacy = client.patch("/api/v1/settings", json={"themeMode": "dark"})
        assert legacy.status_code == 200

        # Invalid baseRevision shape → stable 400.
        bad = client.patch("/api/v1/settings", json={"baseRevision": -1})
        assert bad.status_code == 400
        assert bad.json()["error"]["type"] == "invalid_app_settings"


def test_get_settings_returns_defaults_when_nothing_stored(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.get("/api/v1/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == 1
    assert body["stored"] is False
    assert body["themeMode"] == "system"
    assert body["accentColor"] == "#6d78e8"
    assert body["uiFontSize"] == 16
    assert body["reduceMotion"] is False
    assert body["readerFontSize"] == 17.0
    assert body["readerLineHeight"] == 1.85
    assert body["readerParagraphSpacing"] == 0.85
    assert body["readerContentWidth"] == 760.0
    assert body["readerPageMargin"] == 32.0
    assert body["scrollMarkUnread"] is False


def test_patch_round_trips_and_reports_stored(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.patch(
            "/api/v1/settings",
            json={
                "themeMode": "dark",
                "readerFontSize": 20,
                "readerLineHeight": 2.0,
                "readerContentWidth": 900,
                "readerPageMargin": 48,
                "scrollMarkUnread": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["stored"] is True
        assert body["themeMode"] == "dark"
        assert body["readerFontSize"] == 20.0
        assert body["readerLineHeight"] == 2.0
        assert body["readerContentWidth"] == 900.0
        assert body["readerPageMargin"] == 48.0
        assert body["scrollMarkUnread"] is True
        # untouched fields keep defaults
        assert body["readerFontFamily"] == "system"

        reread = client.get("/api/v1/settings")
        assert reread.status_code == 200
        assert reread.json()["stored"] is True
        assert reread.json()["readerFontSize"] == 20.0


def test_patch_is_partial_and_merge_keeps_prior_values(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        client.patch("/api/v1/settings", json={"readerFontSize": 24})
        response = client.patch("/api/v1/settings", json={"readerLineHeight": 1.4})

    body = response.json()
    assert body["readerFontSize"] == 24.0
    assert body["readerLineHeight"] == 1.4


def test_empty_payload_is_a_no_op(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.patch("/api/v1/settings", json={})

    assert response.status_code == 200
    assert response.json()["stored"] is True


def test_settings_survive_app_restart(tmp_path):
    path = tmp_path / "lumi.sqlite"
    with TestClient(app) as client:
        app.state.db = Database(path)
        client.patch("/api/v1/settings", json={"readerFontSize": 22})

    with TestClient(app) as client:
        app.state.db = Database(path)
        response = client.get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["stored"] is True
    assert response.json()["readerFontSize"] == 22.0


def test_patch_rejects_unknown_keys(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.patch(
            "/api/v1/settings",
            json={"apiKey": SMUGGLED_KEY, "readerFontSize": 18},
        )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_app_settings"


def test_patch_rejects_wrong_types(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        # string for a number
        assert (
            client.patch("/api/v1/settings", json={"readerFontSize": "20"}).status_code
            == 400
        )
        # int for a strict bool
        assert (
            client.patch("/api/v1/settings", json={"reduceMotion": 1}).status_code == 400
        )
        # string for a bool
        assert (
            client.patch("/api/v1/settings", json={"readerJustify": "true"}).status_code
            == 400
        )
        # number for an enum
        assert client.patch("/api/v1/settings", json={"themeMode": 3}).status_code == 400


def test_patch_rejects_out_of_range_numbers(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        for field, value in (
            ("readerFontSize", 5),
            ("readerFontSize", 100),
            ("readerLineHeight", 0.5),
            ("readerLineHeight", 9.0),
            ("readerParagraphSpacing", -1.0),
            ("readerParagraphSpacing", 5.0),
            ("readerContentWidth", 100),
            ("readerContentWidth", 10000),
            ("readerPageMargin", 0),
            ("readerPageMargin", 400),
        ):
            response = client.patch("/api/v1/settings", json={field: value})
            assert response.status_code == 400, f"{field}={value}"
            assert response.json()["error"]["type"] == "invalid_app_settings"


def test_patch_rejects_non_finite_numbers(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        for payload in (
            '{"readerFontSize": NaN}',
            '{"readerFontSize": Infinity}',
            '{"readerLineHeight": -Infinity}',
        ):
            response = client.patch(
                "/api/v1/settings",
                content=payload,
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 400, payload
            assert response.json()["error"]["type"] == "invalid_app_settings"


def test_patch_rejects_malformed_json_body(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        for payload in ("{", "[1,2]", '"string"'):
            response = client.patch(
                "/api/v1/settings",
                content=payload,
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 400, payload


def test_numeric_values_are_normalized_onto_the_step_grid(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        # float artifacts from JS sliders must not reach the store
        response = client.patch(
            "/api/v1/settings",
            json={"readerLineHeight": 1.8500000000000001, "readerFontSize": 17},
        )

    body = response.json()
    assert body["readerLineHeight"] == 1.85
    assert body["readerFontSize"] == 17.0


def test_delete_resets_to_defaults(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        client.patch("/api/v1/settings", json={"readerFontSize": 28, "themeMode": "dark"})

        deleted = client.delete("/api/v1/settings")
        assert deleted.status_code == 204

        reread = client.get("/api/v1/settings")
        assert reread.status_code == 200
        body = reread.json()
        assert body["stored"] is False
        assert body["readerFontSize"] == 17.0
        assert body["themeMode"] == "system"


def test_corrupted_stored_document_falls_back_to_defaults(tmp_path):
    path = tmp_path / "lumi.sqlite"
    db = Database(path)
    with TestClient(app) as client:
        app.state.db = db
        client.get("/api/v1/settings")  # ensures schema exists
    # write garbage directly into the row
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO lumi_settings (key, value, updated_at) VALUES ('app.settings', 'not-json{', '2026-09-03T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()

    with TestClient(app) as client:
        app.state.db = Database(path)
        response = client.get("/api/v1/settings")

    assert response.status_code == 200
    body = response.json()
    assert body["stored"] is True
    assert body["readerFontSize"] == 17.0


def test_future_schema_version_falls_back_to_defaults(tmp_path):
    path = tmp_path / "lumi.sqlite"
    db = Database(path)
    with TestClient(app) as client:
        app.state.db = db
        client.get("/api/v1/settings")
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
        ('app.settings', '{"schemaVersion": 99, "readerFontSize": 25}', '2026-09-03T00:00:00+00:00'),
    )
    connection.commit()
    connection.close()

    with TestClient(app) as client:
        app.state.db = Database(path)
        response = client.get("/api/v1/settings")

    assert response.status_code == 200
    assert response.json()["readerFontSize"] == 17.0


def test_patch_rejects_invalid_hex_colors(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        assert client.patch("/api/v1/settings", json={"accentColor": "red"}).status_code == 400
        assert (
            client.patch(
                "/api/v1/settings", json={"readerBackgroundCustom": "#ffff"}
            ).status_code
            == 400
        )


def test_settings_response_contains_no_secret_fields(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.get("/api/v1/settings")

    text = response.text
    for marker in ("apiKey", "api_key", "password", "token", "secret", "credential"):
        assert marker not in text


def test_sqlite_never_shadows_rss_domain_data(tmp_path):
    path = tmp_path / "lumi.sqlite"
    with TestClient(app) as client:
        app.state.db = Database(path)
        client.get("/api/v1/settings")
        client.patch("/api/v1/settings", json={"readerFontSize": 20})

    connection = sqlite3.connect(path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    connection.close()
    for forbidden in ("feeds", "entries", "categories", "subscriptions", "read_state", "starred"):
        assert forbidden not in tables


def test_rejects_unknown_top_level_document_fields_on_read(tmp_path):
    path = tmp_path / "lumi.sqlite"
    db = Database(path)
    with TestClient(app) as client:
        app.state.db = db
        client.get("/api/v1/settings")
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
        ('app.settings', '{"schemaVersion": 1, "readerFontSize": 20, "evilKey": "x"}', '2026-09-03T00:00:00+00:00'),
    )
    connection.commit()
    connection.close()

    with TestClient(app) as client:
        app.state.db = Database(path)
        response = client.get("/api/v1/settings")

    # extra="forbid" → document rejected wholesale → safe defaults
    assert response.status_code == 200
    assert response.json()["readerFontSize"] == 17.0
