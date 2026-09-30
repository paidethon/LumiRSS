"""NEW-390 迁移结果逐项对账 — added/matched/failed/missing 判定、
逐条确认（无一键全收）、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def _create(client, who, expected, results, source="manual"):
    return client.post(
        "/api/v1/preservation/reconciliations",
        json={
            "expectedItemIds": expected,
            "results": results,
            "source": source,
        },
        headers=who,
    )


def test_new390_statuses_and_missing_detection(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    response = _create(
        client,
        a,
        expected=["ext-1", "ext-2", "ext-3", "ext-4"],
        results=[
            {"externalId": "ext-1", "title": "甲", "status": "added", "detail": ""},
            {"externalId": "ext-2", "title": "乙", "status": "matched",
             "detail": "已存在"},
            {"externalId": "ext-3", "title": "丙", "status": "failed",
             "detail": "字段超长"},
            # ext-4 不在结果里 → missing 自动判定
        ],
    )
    assert response.status_code == 201, response.text
    recon = response.json()
    assert recon["counts"] == {"added": 1, "matched": 1, "failed": 1, "missing": 1}
    assert recon["pendingCount"] == 4
    assert recon["status"] == "open"
    missing = next(
        entry for entry in recon["results"] if entry["status"] == "missing"
    )
    assert missing["externalId"] == "ext-4"
    assert "没有出现" in missing["detail"]
    # 非法状态码归一为 failed（不静默丢弃）
    weird = _create(
        client, a, expected=["x"], results=[{"externalId": "x", "status": "???"}]
    )
    assert weird.json()["counts"]["failed"] == 1


def test_new390_itemized_confirm_flow(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    recon = _create(
        client,
        a,
        expected=["ext-1", "ext-2", "ext-3"],
        results=[
            {"externalId": "ext-1", "title": "甲", "status": "added", "detail": ""},
            {"externalId": "ext-2", "title": "乙", "status": "matched",
             "detail": ""},
        ],
    ).json()
    assert recon["counts"]["missing"] == 1
    # 逐条确认：一次只确认一条
    first = client.post(
        f"/api/v1/preservation/reconciliations/{recon['id']}/confirm",
        json={"externalIds": ["ext-1"]},
        headers=a,
    ).json()
    assert first["acceptedNow"] == 1
    assert first["pendingCount"] == 2
    assert first["status"] == "open"
    # 未知条目确认是显式 no-op（不误收）
    second = client.post(
        f"/api/v1/preservation/reconciliations/{recon['id']}/confirm",
        json={"externalIds": ["ext-1", "not-in-list"]},
        headers=a,
    ).json()
    assert second["acceptedNow"] == 0
    assert second["pendingCount"] == 2
    # 逐条确认剩余 → 完成
    third = client.post(
        f"/api/v1/preservation/reconciliations/{recon['id']}/confirm",
        json={"externalIds": ["ext-2", "ext-3"]},
        headers=a,
    ).json()
    assert third["pendingCount"] == 0
    assert third["status"] == "completed"
    assert sorted(third["confirmed"]) == ["ext-1", "ext-2", "ext-3"]


def test_new390_validation_and_ledger(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    empty = _create(client, a, expected=[], results=[])
    assert empty.status_code == 400
    listing = client.get("/api/v1/preservation/reconciliations", headers=a).json()
    assert listing["reconciliations"] == []
    recon = _create(client, a, expected=["e1"], results=[]).json()
    listing = client.get("/api/v1/preservation/reconciliations", headers=a).json()
    assert listing["reconciliations"][0]["id"] == recon["id"]
    missing_detail = client.get(
        "/api/v1/preservation/reconciliations/recon-nope", headers=a
    )
    assert missing_detail.status_code == 404
    unknown_confirm = client.post(
        "/api/v1/preservation/reconciliations/recon-nope/confirm",
        json={"externalIds": ["e1"]},
        headers=a,
    )
    assert unknown_confirm.status_code == 404


def test_new390_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    recon = _create(client, a, expected=["e1"], results=[]).json()
    # B 看不到 A 的对账单，也不能确认它
    assert client.get(
        f"/api/v1/preservation/reconciliations/{recon['id']}", headers=b
    ).status_code == 404
    denied = client.post(
        f"/api/v1/preservation/reconciliations/{recon['id']}/confirm",
        json={"externalIds": ["e1"]},
        headers=b,
    )
    assert denied.status_code == 404
    # A 的确认状态不受 B 的尝试影响
    still = client.get(
        f"/api/v1/preservation/reconciliations/{recon['id']}", headers=a
    ).json()
    assert still["pendingCount"] == 1
    b_listing = client.get("/api/v1/preservation/reconciliations", headers=b).json()
    assert b_listing["reconciliations"] == []
