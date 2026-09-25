"""N058 阅读样式预设进 portable 同步（BFF 侧）测试。

- PATCH /api/v1/settings 携带 readerPresets → GET 原样回显（版本标签
  schemaVersion 保留；deviceScope 随预设同步）；
- 非法预设（未知 vars 键 / 越界数值 / 非法枚举）→ 400 invalid_app_settings，
  绝不静默入库；
- 预设列表整体替换（幂等 upsert 由客户端归并）。
"""



def _client(client):
    return client


def test_preset_sync_roundtrip(client):
    presets = [
        {
            "id": "preset-a",
            "name": "夜间长文",
            "schemaVersion": 2,
            "vars": {
                "readerFontFamily": "serif",
                "readerFontSize": 21,
                "readerLineHeight": 1.9,
                "readerJustify": True,
                "deviceScope": "all",
            },
        },
        {
            "id": "preset-b",
            "name": "桌面双栏",
            "schemaVersion": 2,
            "vars": {
                "readerContentWidth": 860,
                "readerColumns": 2,
                "deviceScope": "desktop",
            },
        },
    ]
    patched = client.patch(
        "/api/v1/settings", json={"readerPresets": presets}
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["readerPresets"] == presets  # 版本标签原样保留

    fetched = client.get("/api/v1/settings").json()
    assert fetched["readerPresets"] == presets

    # 整体替换幂等：再 PATCH 空列表 → 清空。
    cleared = client.patch("/api/v1/settings", json={"readerPresets": []})
    assert cleared.status_code == 200
    assert cleared.json()["readerPresets"] == []


def test_preset_sync_rejects_invalid_payloads(client):
    bad_bodies = [
        # 未知 vars 键
        [{"id": "x", "name": "坏预设", "schemaVersion": 2, "vars": {"hacker": "<script>"}}],
        # 非法枚举
        [{"id": "x", "name": "坏预设", "schemaVersion": 2, "vars": {"deviceScope": "tv"}}],
        # 非法 schemaVersion
        [{"id": "x", "name": "坏预设", "schemaVersion": 0, "vars": {}}],
        # 未知顶层键（builtin 是设备本地字段，绝不入库）
        [{"id": "x", "name": "坏预设", "schemaVersion": 2, "builtin": True, "vars": {}}],
    ]
    for presets in bad_bodies:
        response = client.patch("/api/v1/settings", json={"readerPresets": presets})
        # 服务端统一 400 invalid_app_settings（严格校验，绝不静默入库）。
        assert response.status_code == 400, (presets, response.text)
        assert response.json()["error"]["type"] == "invalid_app_settings"

    # 失败后文档未被污染。
    fetched = client.get("/api/v1/settings").json()
    assert fetched["readerPresets"] == []


def test_preset_numeric_vars_clamped_to_bounds(client):
    """越界数值收进界内（与 portable 数值键同一归一化口径，响应如实回显）。"""
    response = client.patch(
        "/api/v1/settings",
        json={
            "readerPresets": [
                {
                    "id": "clamp-1",
                    "name": "越界预设",
                    "schemaVersion": 2,
                    "vars": {"readerFontSize": 999, "readerColumns": 9},
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    presets = response.json()["readerPresets"]
    assert presets[0]["vars"]["readerFontSize"] == 28.0
    assert presets[0]["vars"]["readerColumns"] == 3.0
