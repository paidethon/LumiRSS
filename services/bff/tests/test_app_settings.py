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


def test_patch_round_trips_2026_mobile_batch_keys(tmp_path):
    """2026-09 移动端专项新增 portable 键：默认值 + PATCH 往返 + 枚举拒绝。"""
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        defaults = client.get("/api/v1/settings").json()
        assert defaults["readerAutoMarkRead"] is True
        assert defaults["glassEffect"] == "auto"
        assert defaults["listDensity"] == "standard"
        assert defaults["timelineOrder"] == "newest"

        response = client.patch(
            "/api/v1/settings",
            json={
                "readerAutoMarkRead": False,
                "glassEffect": "off",
                "swipeBackGesture": False,
                "listDensity": "comfortable",
                "listShowSnippet": False,
                "listShowCover": False,
                "listTimeFormat": "absolute",
                "listGroupByFeed": True,
                "timelineOrder": "oldest",
                "cardSwipeAction": "readLater",
                "readerShowReadingProgress": False,
                "readerCodeWrap": True,
                "readerPagedMode": True,
                "searchHighlightMatches": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["readerAutoMarkRead"] is False
        assert body["glassEffect"] == "off"
        assert body["swipeBackGesture"] is False
        assert body["listDensity"] == "comfortable"
        assert body["listShowSnippet"] is False
        assert body["listShowCover"] is False
        assert body["listTimeFormat"] == "absolute"
        assert body["listGroupByFeed"] is True
        assert body["timelineOrder"] == "oldest"
        assert body["cardSwipeAction"] == "readLater"
        assert body["readerShowReadingProgress"] is False
        assert body["readerCodeWrap"] is True
        assert body["readerPagedMode"] is True
        assert body["searchHighlightMatches"] is False

        # 枚举键拒绝越界值（invalid_app_settings → 400）。
        rejected = client.patch("/api/v1/settings", json={"glassEffect": "sparkle"})
        assert rejected.status_code == 400
        rejected = client.patch("/api/v1/settings", json={"cardSwipeAction": "delete"})
        assert rejected.status_code == 400


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


# ---- R25 云端同步扩展（原 device-local 用户偏好上云） ----


def test_r25_new_keys_defaults_and_round_trip(tmp_path):
    """R25：布局/工具栏/阅读模式/朗读/其余偏好键——默认值 + PATCH 往返。"""
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        defaults = client.get("/api/v1/settings").json()
        assert defaults["sidebarWidth"] == 240
        assert defaults["timelineWidth"] == 400
        assert defaults["sidebarCollapsed"] is False
        assert defaults["readerReadingMode"] == "scroll"
        assert defaults["readerTapZoneAxis"] == "horizontal"
        assert defaults["readerTapZoneSize"] == "small"
        assert defaults["readerToolbarDesktopOrder"] == []
        assert defaults["speechVoiceURI"] == ""
        assert defaults["speechRate"] == 1.0
        assert defaults["speechStopMode"] == "article"
        assert defaults["customCss"] == ""
        assert defaults["filterRules"] == []
        assert defaults["dimRead"] is False
        assert defaults["readerFontWeight"] == 400
        assert defaults["readerBreakReminderMinutes"] == 45

        response = client.patch(
            "/api/v1/settings",
            json={
                "dimRead": True,
                "groupByDate": True,
                "unreadOnly": True,
                "customCss": ".lumi-reader p { letter-spacing: 0.01em; }",
                "readerPresetId": "custom-preset-1",
                "pauseReadingProgress": True,
                "translationLinkedScroll": True,
                "dictApiUrl": "https://dict.example/lookup?q={word}",
                "readerKeyNav": True,
                "filterRules": [
                    {
                        "id": "rule-1",
                        "keyword": "赞助",
                        "feedId": None,
                        "type": "keyword",
                        "enabled": True,
                    }
                ],
                "readerFontWeight": 600,
                "readerImageMaxWidth": "75%",
                "readerCaptionMode": "hover",
                "readerCodeFontSize": "l",
                "readerBreakReminderMinutes": 30,
                "readerContentWidthMode": "viewport",
                "readerContentWidthViewport": 80,
                "readerIndentLists": True,
                "readerIndentQuotes": True,
                "readerLineBreakStrict": True,
                "readerBionic": True,
                "readerBlockRemoteImages": True,
                "sidebarWidth": 280,
                "sidebarCollapsed": True,
                "timelineWidth": 440,
                "timelineCollapsed": True,
                "readerReadingMode": "paged",
                "readerTapZoneAxis": "vertical",
                "readerTapZoneSize": "large",
                "readerToolbarDesktopOrder": [
                    "star",
                    "-share",
                    "ai",
                    "more",
                ],
                "readerToolbarMobileOrder": ["more", "-print", "star"],
                "speechVoiceURI": "urn:example:voice",
                "speechRate": 1.25,
                "speechSleepTimerMinutes": 10,
                "speechSkipCode": True,
                "speechSkipTables": True,
                "speechSkipFootnotes": True,
                "speechSkipCaptions": True,
                "speechSkipLinkOnly": True,
                "speechLexicon": [{"match": "API", "replace": "A.P.I."}],
                "speechBilingualAlternate": True,
                "speechBilingualGap": "short",
                "speechVoiceURIZh": "urn:example:zh",
                "speechVoiceURIEn": "urn:example:en",
                "speechStopMode": "queue",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["dimRead"] is True
        assert body["customCss"].startswith(".lumi-reader")
        assert body["filterRules"] == [
            {
                "id": "rule-1",
                "keyword": "赞助",
                "feedId": None,
                "type": "keyword",
                "enabled": True,
            }
        ]
        assert body["readerFontWeight"] == 600
        assert body["readerImageMaxWidth"] == "75%"
        assert body["readerCaptionMode"] == "hover"
        assert body["readerCodeFontSize"] == "l"
        assert body["readerBreakReminderMinutes"] == 30
        assert body["readerContentWidthMode"] == "viewport"
        assert body["readerContentWidthViewport"] == 80
        assert body["readerIndentLists"] is True
        assert body["readerIndentQuotes"] is True
        assert body["readerLineBreakStrict"] is True
        assert body["readerBionic"] is True
        assert body["readerBlockRemoteImages"] is True
        assert body["sidebarWidth"] == 280
        assert body["timelineWidth"] == 440
        assert body["readerReadingMode"] == "paged"
        assert body["readerTapZoneAxis"] == "vertical"
        assert body["readerTapZoneSize"] == "large"
        # '-id' 隐藏占位原样透传（R11 申报语义）
        assert body["readerToolbarDesktopOrder"] == ["star", "-share", "ai", "more"]
        assert body["readerToolbarMobileOrder"] == ["more", "-print", "star"]
        assert body["speechVoiceURI"] == "urn:example:voice"
        assert body["speechRate"] == 1.25
        assert body["speechSleepTimerMinutes"] == 10
        assert body["speechSkipCode"] is True
        assert body["speechLexicon"] == [{"match": "API", "replace": "A.P.I."}]
        assert body["speechBilingualGap"] == "short"
        assert body["speechStopMode"] == "queue"

        reread = client.get("/api/v1/settings").json()
        assert reread["sidebarWidth"] == 280
        assert reread["readerReadingMode"] == "paged"
        assert reread["speechRate"] == 1.25
        assert reread["readerToolbarDesktopOrder"] == ["star", "-share", "ai", "more"]


def test_r25_toolbar_order_validation(tmp_path):
    """order 键：'^[a-z0-9-]+$' 格式 + 容量上限；'-id' 占位合法。"""
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        ok = client.patch(
            "/api/v1/settings",
            json={"readerToolbarDesktopOrder": ["star", "-ai", "more"]},
        )
        assert ok.status_code == 200

        bad_char = client.patch(
            "/api/v1/settings",
            json={"readerToolbarDesktopOrder": ["star", "AI!"]},
        )
        assert bad_char.status_code == 400
        assert bad_char.json()["error"]["type"] == "invalid_app_settings"

        uppercase = client.patch(
            "/api/v1/settings",
            json={"readerToolbarMobileOrder": ["Star"]},
        )
        assert uppercase.status_code == 400

        too_many = client.patch(
            "/api/v1/settings",
            json={"readerToolbarDesktopOrder": [f"tag-{i}" for i in range(65)]},
        )
        assert too_many.status_code == 400

        too_long = client.patch(
            "/api/v1/settings",
            json={"readerToolbarDesktopOrder": ["a" * 65]},
        )
        assert too_long.status_code == 400


def test_r25_speech_and_int_bounds_validation(tmp_path):
    """语速档位外拒绝；布局宽度钳制 + 非法类型拒绝。"""
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        off_grid = client.patch("/api/v1/settings", json={"speechRate": 1.3})
        assert off_grid.status_code == 400
        as_string = client.patch("/api/v1/settings", json={"speechRate": "1.25"})
        assert as_string.status_code == 400
        bad_sleep = client.patch(
            "/api/v1/settings", json={"speechSleepTimerMinutes": 7}
        )
        assert bad_sleep.status_code == 400
        bad_lexicon = client.patch(
            "/api/v1/settings",
            json={"speechLexicon": [{"match": "", "replace": "x"}]},
        )
        assert bad_lexicon.status_code == 400

        # JS 侧可能带来小数：round 归整；越界钳制到边界
        clamped = client.patch(
            "/api/v1/settings",
            json={"sidebarWidth": 279.6, "timelineWidth": 999},
        )
        assert clamped.status_code == 200
        assert clamped.json()["sidebarWidth"] == 280
        assert clamped.json()["timelineWidth"] == 460

        wrong_type = client.patch("/api/v1/settings", json={"sidebarWidth": "280"})
        assert wrong_type.status_code == 400
        boolean = client.patch("/api/v1/settings", json={"timelineWidth": True})
        assert boolean.status_code == 400


def test_r25_stored_keys_track_explicit_overrides_only(tmp_path):
    """storedKeys = 显式存过的键；存储保持 overrides-only（R25 升级语义）。"""
    path = tmp_path / "lumi.sqlite"
    with TestClient(app) as client:
        app.state.db = Database(path)
        fresh = client.get("/api/v1/settings").json()
        assert fresh["storedKeys"] == []

        patched = client.patch(
            "/api/v1/settings", json={"readerFontSize": 22, "sidebarWidth": 280}
        ).json()
        assert patched["storedKeys"] == ["readerFontSize", "sidebarWidth"]

        # 未触碰的键不入 storedKeys（值仍是全量文档里的模型默认）
        assert patched["readerReadingMode"] == "scroll"
        reread = client.get("/api/v1/settings").json()
        assert reread["storedKeys"] == ["readerFontSize", "sidebarWidth"]

    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT value FROM lumi_settings WHERE key = 'app.settings'"
    ).fetchone()
    connection.close()
    import json as _json

    stored = _json.loads(row[0])
    # overrides-only：未 PATCH 的键（含本轮新增键）绝不写入存储行
    assert set(stored) == {"readerFontSize", "sidebarWidth"}


def test_r25_legacy_document_new_keys_stay_unset(tmp_path):
    """升级场景：旧文档只存过旧键 → 新键不在 storedKeys（客户端保留本地值）。"""
    path = tmp_path / "lumi.sqlite"
    db = Database(path)
    with TestClient(app) as client:
        app.state.db = db
        client.get("/api/v1/settings")
    connection = sqlite3.connect(path)
    connection.execute(
        "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
        (
            "app.settings",
            '{"schemaVersion": 1, "readerFontSize": 22, "themeMode": "dark"}',
            "2026-09-03T00:00:00+00:00",
        ),
    )
    connection.commit()
    connection.close()

    with TestClient(app) as client:
        app.state.db = Database(path)
        body = client.get("/api/v1/settings").json()
        assert body["stored"] is True
        assert body["storedKeys"] == ["readerFontSize", "schemaVersion", "themeMode"]
        # 新键的值仍随全量文档返回（模型默认），但 storedKeys 告知「未显式存过」
        assert body["sidebarWidth"] == 240
        assert "sidebarWidth" not in body["storedKeys"]

        # 升级客户端随后 PATCH 本地值 → 键变为显式
        seeded = client.patch("/api/v1/settings", json={"sidebarWidth": 288}).json()
        assert "sidebarWidth" in seeded["storedKeys"]
        reread = client.get("/api/v1/settings").json()
        assert reread["sidebarWidth"] == 288
        assert reread["readerFontSize"] == 22.0
