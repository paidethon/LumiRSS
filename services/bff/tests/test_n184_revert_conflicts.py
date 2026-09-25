"""N184 设置变更差异恢复显式化 — revert 返回 restored + conflicts。

F33 的冲突检测早已存在（被后续修改过的键跳过）；N184 把它显式化：
响应携带 restored（已回退键列表）与 conflicts（键 + 原因），UI 明示。"""


def test_n184_revert_lists_restored_and_conflicts(client):
    # 变更两个键
    client.patch(
        "/api/v1/settings", json={"readerFontSize": 21, "readerJustify": True}
    )
    history = client.get("/api/v1/settings/history").json()["items"]
    entry = next(item for item in history if item["action"] == "update")
    # 其中一个键之后又被改过 → 回退时冲突
    client.patch("/api/v1/settings", json={"readerFontSize": 14})

    revert = client.post(f"/api/v1/settings/history/{entry['id']}/revert")
    assert revert.status_code == 200, revert.text
    body = revert.json()
    # 显式清单：restored = 已回退键；conflict 键 + 原因
    assert body["restored"] == ["readerJustify"]
    conflict_keys = [conflict["key"] for conflict in body["conflicts"]]
    assert conflict_keys == ["readerFontSize"]
    assert all(conflict["reason"].strip() for conflict in body["conflicts"])
    # 值语义：未冲突键回到 before，冲突键保持新值
    assert body["applied"] == {"readerJustify": False}
    current = client.get("/api/v1/settings").json()
    assert current["readerFontSize"] == 14
    assert current["readerJustify"] is False


def test_n184_revert_without_conflicts_has_empty_conflicts(client):
    client.patch("/api/v1/settings", json={"readerFontSize": 21})
    history = client.get("/api/v1/settings/history").json()["items"]
    entry = next(item for item in history if item["action"] == "update")
    revert = client.post(f"/api/v1/settings/history/{entry['id']}/revert")
    assert revert.status_code == 200
    body = revert.json()
    assert body["restored"] == ["readerFontSize"]
    assert body["conflicts"] == []
    current = client.get("/api/v1/settings").json()
    # 未冲突键回到记录的 before 值
    assert current["readerFontSize"] == body["applied"]["readerFontSize"] == 17
