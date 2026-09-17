"""F33 设置变更历史 — 记录/冲突跳过/回退语义测试。"""


from lumirss.settings_history import compute_diff


def run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


def test_f33_patch_records_history_and_revert_skips_conflicts(client):
    # 基线：当前 fontSize=17
    client.patch("/api/v1/settings", json={"readerFontSize": 19})
    # 变更两个键 → 历史记录一条（只含变化键）
    response = client.patch(
        "/api/v1/settings", json={"readerFontSize": 21, "readerJustify": True}
    )
    assert response.status_code == 200
    history = client.get("/api/v1/settings/history").json()["items"]
    update_entry = next(item for item in history if item["action"] == "update")
    assert set(update_entry["diff"].keys()) == {"readerFontSize", "readerJustify"}
    assert update_entry["diff"]["readerFontSize"]["before"] == 19
    assert update_entry["diff"]["readerFontSize"]["after"] == 21

    # 回退该条 → 应用 before 值
    revert = client.post(f"/api/v1/settings/history/{update_entry['id']}/revert")
    assert revert.status_code == 200, revert.text
    result = revert.json()
    assert result["applied"] == {"readerFontSize": 19, "readerJustify": False}
    assert result["skipped"] == {}
    current = client.get("/api/v1/settings").json()
    assert current["readerFontSize"] == 19
    assert current["readerJustify"] is False


def test_f33_revert_skips_keys_changed_later(client):
    client.patch("/api/v1/settings", json={"readerFontSize": 21})
    history = client.get("/api/v1/settings/history").json()["items"]
    entry = next(item for item in history if "readerFontSize" in item["diff"])
    # 该键之后又被改过（新修改）→ 回退跳过，不覆盖新修改
    client.patch("/api/v1/settings", json={"readerFontSize": 14})
    revert = client.post(f"/api/v1/settings/history/{entry['id']}/revert")
    assert revert.status_code == 200
    body = revert.json()
    assert body["applied"] == {}
    assert body["skipped"] == {"readerFontSize": 14}
    current = client.get("/api/v1/settings").json()
    assert current["readerFontSize"] == 14  # 新修改保持不变


def test_f33_history_capped_at_20(client):
    for i in range(25):
        client.patch("/api/v1/settings", json={"readerFontSize": 12 + (i % 10)})
    history = client.get("/api/v1/settings/history?limit=20").json()["items"]
    assert len(history) <= 20


def test_f33_compute_diff_ignores_schema_version():
    before = {"schemaVersion": 1, "readerFontSize": 17}
    after = {"schemaVersion": 1, "readerFontSize": 19}
    diff = compute_diff(before, after)
    assert diff == {"readerFontSize": {"before": 17, "after": 19}}
