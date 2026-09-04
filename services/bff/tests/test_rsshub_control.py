"""Tests for the RSSHub Control Center store + API (0018).

The control plane is schema-driven, typed and allow-listed: known keys are
accepted, unknown keys rejected, wrong types / ranges rejected, secrets are
write-only and never echoed, and desired/effective (applied) semantics
report restartRequired honestly.
"""

import asyncio

import pytest

from lumirss.rsshub_control import (
    RssHubControlError,
    RssHubControlStore,
    SCHEMA,
    export_env,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    secrets = SecretsStore(tmp_path / "secrets.json")
    return RssHubControlStore(db, secrets)


def test_schema_has_required_groups():
    groups = {item.group for item in SCHEMA}
    assert {
        "instance",
        "cache",
        "network",
        "access",
        "browser",
        "advanced",
        "credentials",
    } <= groups


def test_schema_secret_keys_are_write_only():
    secret_items = [item for item in SCHEMA if item.secret]
    assert secret_items, "schema must contain secret (route credential) items"
    for item in secret_items:
        assert item.secret is True


def test_known_key_accepted(store):
    updated = run(store.patch_desired({"CACHE_EXPIRE": 500}))
    assert updated["CACHE_EXPIRE"] == 500


def test_unknown_key_rejected(store):
    with pytest.raises(RssHubControlError):
        run(store.patch_desired({"TOTALLY_FAKE": 1}))


def test_wrong_type_rejected(store):
    with pytest.raises(RssHubControlError):
        run(store.patch_desired({"CACHE_EXPIRE": "300"}))


def test_bool_strict_rejected(store):
    with pytest.raises(RssHubControlError):
        run(store.patch_desired({"DISABLE_IPV6": 1}))


def test_out_of_range_rejected(store):
    with pytest.raises(RssHubControlError):
        run(store.patch_desired({"MEMORY_MAX": 1}))


def test_invalid_enum_rejected(store):
    with pytest.raises(RssHubControlError):
        run(store.patch_desired({"CACHE_TYPE": "filesystem"}))


def test_non_editable_item_rejected(store):
    with pytest.raises(RssHubControlError):
        run(store.patch_desired({"PORT": 9999}))


def test_secret_rejected_on_normal_patch(store):
    with pytest.raises(RssHubControlError):
        run(store.patch_desired({"ACCESS_KEY": "hunter2"}))


def test_restart_required_after_patch_and_cleared_by_apply(store):
    flags = run(store.restart_required_flags())
    assert flags["count"] == 0
    run(store.patch_desired({"CACHE_EXPIRE": 600}))
    flags = run(store.restart_required_flags())
    assert flags["count"] == 1
    assert flags["flags"]["CACHE_EXPIRE"] is True
    run(store.mark_applied())
    flags = run(store.restart_required_flags())
    assert flags["count"] == 0


def test_secret_write_then_configured(store):
    assert store.secret_configured_map()["GITHUB_ACCESS_TOKEN"] is False
    run(store.set_secret("GITHUB_ACCESS_TOKEN", "ghp_abcdef"))
    assert store.secret_configured_map()["GITHUB_ACCESS_TOKEN"] is True


def test_secret_change_bumps_restart_required(store):
    run(store.mark_applied())
    run(store.set_secret("GITHUB_ACCESS_TOKEN", "ghp_one"))
    flags = run(store.restart_required_flags())
    assert flags["pendingSecrets"] is True
    assert flags["count"] >= 1
    run(store.mark_applied())
    assert run(store.restart_required_flags())["pendingSecrets"] is False


def test_secret_delete_clear(store):
    run(store.set_secret("ZHIHU_COOKIES", "cookie-value"))
    assert store.secret_configured_map()["ZHIHU_COOKIES"] is True
    run(store.delete_secret("ZHIHU_COOKIES"))
    assert store.secret_configured_map()["ZHIHU_COOKIES"] is False


def test_unknown_secret_rejected(store):
    with pytest.raises(RssHubControlError):
        run(store.set_secret("NOT_A_SECRET", "x"))
    with pytest.raises(RssHubControlError):
        run(store.set_secret("CACHE_EXPIRE", "x"))


def test_export_never_contains_secret_values(store):
    run(store.set_secret("GITHUB_ACCESS_TOKEN", "ghp_SUPER_SECRET"))
    run(store.patch_desired({"CACHE_EXPIRE": 600}))
    text = export_env(store, run(store.desired()))
    assert "CACHE_EXPIRE=600" in text
    assert "ghp_SUPER_SECRET" not in text
    assert "GITHUB_ACCESS_TOKEN=<configured>" in text
