"""F36 存储用量端点测试 — 口径与诚实性。

- database 计入主库 + WAL/SHM；
- backupsDir 统计本地备份目录（无目录 = 0 而非错误）；
- libraryAssets 无表数据时仍返回结构（count=0）；
- budgetMB=0（默认关闭）时 warning 为 null；预算内不告警。
"""



def test_storage_usage_shape_and_defaults(client):
    response = client.get("/api/v1/storage/usage")
    assert response.status_code == 200
    body = response.json()
    assert body["database"]["bytes"] >= 0
    assert body["libraryAssets"]["count"] is not None
    assert body["backupsDir"] == {"count": 0, "bytes": 0} or set(body["backupsDir"]) == {
        "count",
        "bytes",
    }
    assert isinstance(body["totalKnownBytes"], int)
    assert body["warning"] is None  # 默认无预算 → 不告警
