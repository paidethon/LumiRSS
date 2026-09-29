"""NEW-376 实例配置草案 — 校验/差异/生效条件先成草案，step-up 应用；
应用走与注册政策端点同一执行点（真实生效）。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new37x_helpers import step_up_headers


def test_new376_draft_validates_and_diffs(ab_env):  # noqa: F811
    """合法草案：当前值/拟值/校验/生效条件齐全；坏键与坏值 422；
    草案阶段注册政策不变。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    before = client.get("/api/v1/admin/registration-policy", headers=owner)
    assert before.status_code == 200

    draft = client.post(
        "/api/v1/admin/config-drafts",
        headers=owner,
        json={"key": "allow_public_registration", "value": "1"},
    )
    assert draft.status_code == 200, draft.text
    payload = draft.json()
    assert payload["currentValue"] == "0"
    assert payload["draftValue"] == "1"
    assert payload["differs"] is True
    assert payload["validation"]["ok"] is True
    assert any("新注册" in note for note in payload["effectiveNotes"])

    bad_key = client.post(
        "/api/v1/admin/config-drafts",
        headers=owner,
        json={"key": "smtp_password", "value": "x"},
    )
    assert bad_key.status_code == 422
    bad_value = client.post(
        "/api/v1/admin/config-drafts",
        headers=owner,
        json={"key": "allow_public_registration", "value": "maybe"},
    )
    assert bad_value.status_code == 422

    after = client.get("/api/v1/admin/registration-policy", headers=owner)
    assert after.status_code == 200  # 草案不生效


def test_new376_apply_requires_step_up(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner = ab_env["owner"]
    draft = client.post(
        "/api/v1/admin/config-drafts",
        headers=owner,
        json={"key": "allow_public_registration", "value": "1"},
    ).json()
    bare = client.post(f"/api/v1/admin/config-drafts/{draft['draftId']}/apply", headers=owner)
    assert bare.status_code == 403
    assert bare.json()["error"]["type"] == "step_up_required"


def test_new376_apply_changes_real_policy(ab_env):  # noqa: F811
    """step-up 应用 → 注册政策真实变为 1（同一执行点）；已收尾草案
    再应用/再废弃 409。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    draft = client.post(
        "/api/v1/admin/config-drafts",
        headers=owner,
        json={"key": "allow_public_registration", "value": "1"},
    ).json()

    applied = client.post(
        f"/api/v1/admin/config-drafts/{draft['draftId']}/apply",
        headers=step_up_headers(client, owner, "config_draft_apply"),
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"

    policy = client.get("/api/v1/admin/registration-policy", headers=owner)
    assert policy.status_code == 200
    assert policy.json()["allowPublicRegistration"] is True

    re_apply = client.post(
        f"/api/v1/admin/config-drafts/{draft['draftId']}/apply",
        headers=step_up_headers(client, owner, "config_draft_apply"),
    )
    assert re_apply.status_code == 409
    re_discard = client.post(
        f"/api/v1/admin/config-drafts/{draft['draftId']}/discard", headers=owner
    )
    assert re_discard.status_code == 409


def test_new376_discard_draft(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner = ab_env["owner"]
    draft = client.post(
        "/api/v1/admin/config-drafts",
        headers=owner,
        json={"key": "allow_public_registration", "value": "1"},
    ).json()
    discarded = client.post(
        f"/api/v1/admin/config-drafts/{draft['draftId']}/discard", headers=owner
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["status"] == "discarded"

    listing = client.get("/api/v1/admin/config-drafts", headers=owner)
    assert any(item["status"] == "discarded" for item in listing.json()["items"])
