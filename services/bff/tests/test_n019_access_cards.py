"""N019 来源接入说明卡 —— 结构化 CRUD 往返与「无凭据值」契约。

- 四个结构化字段（acquisition / limits / credentialOwnership /
  maintenance）整卡 upsert 往返；缺席字段 = 清空；
- credentialOwnership 只接受归属标签 self/shared/none（凭据值本身
  属于既有 write-only 边界，绝不入本表）；
- 未知字段键拒绝（422）；schema 没有 secret 字段（对迁移文件断言
  列集合）；列表按 per-user 库隔离。
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database

FEED_URL = "https://source.example/rss"


def run(coroutine):
    return asyncio.run(coroutine)


def test_n019_card_crud_roundtrip(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")

        # 初始：无卡 → 全 null。
        empty = client.get("/api/v1/sources/access-card", params={"feedUrl": FEED_URL})
        assert empty.status_code == 200
        assert empty.json() == {
            "feedUrl": FEED_URL,
            "acquisition": None,
            "limits": None,
            "credentialOwnership": None,
            "maintenance": None,
            "updatedAt": None,
        }

        # 整卡 upsert。
        put = client.put(
            "/api/v1/sources/access-card",
            json={
                "feedUrl": FEED_URL,
                "acquisition": "RSSHub /twitter/user/{id} 路由生成",
                "limits": "上游站点限流：每小时约 100 次",
                "credentialOwnership": "shared",
                "maintenance": "Cookie 失效时联系运营者更换",
            },
        )
        assert put.status_code == 200
        card = put.json()
        assert card["acquisition"].startswith("RSSHub")
        assert card["limits"].startswith("上游站点限流")
        assert card["credentialOwnership"] == "shared"
        assert card["maintenance"].endswith("更换")
        assert card["updatedAt"]

        # 回读一致。
        got = client.get("/api/v1/sources/access-card", params={"feedUrl": FEED_URL})
        assert got.json()["credentialOwnership"] == "shared"

        # 列表出现该卡。
        listed = client.get("/api/v1/sources/access-cards")
        assert [item["feedUrl"] for item in listed.json()["items"]] == [FEED_URL]

        # 缺席字段 = 清空该字段（整卡语义）。
        partial = client.put(
            "/api/v1/sources/access-card",
            json={"feedUrl": FEED_URL, "acquisition": "仅保留获取方式"},
        )
        assert partial.json()["acquisition"] == "仅保留获取方式"
        assert partial.json()["limits"] is None
        assert partial.json()["credentialOwnership"] is None

        # 空卡 = 删除（回到全 null）。
        cleared = client.put(
            "/api/v1/sources/access-card", json={"feedUrl": FEED_URL}
        )
        assert cleared.json()["updatedAt"] is None


def test_n019_unknown_field_key_is_rejected(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.put(
            "/api/v1/sources/access-card",
            json={"feedUrl": FEED_URL, "secretCookie": "should-never-store"},
        )
        # extra=forbid：未知键在模型层直接 422（标准 invalid_request 信封）。
        assert response.status_code == 422
        assert "error" in response.json()


def test_n019_credential_ownership_only_accepts_ownership_labels(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        for bad in ("user:pass@example", "cookie-string", "own"):
            response = client.put(
                "/api/v1/sources/access-card",
                json={"feedUrl": FEED_URL, "credentialOwnership": bad},
            )
            assert response.status_code == 422
        ok = client.put(
            "/api/v1/sources/access-card",
            json={"feedUrl": FEED_URL, "credentialOwnership": "self"},
        )
        assert ok.status_code == 200
        assert ok.json()["credentialOwnership"] == "self"


def test_n019_schema_has_no_credential_value_field():
    """契约断言：迁移定义的列集合里没有任何凭据值字段——凭据归属是
    标签（self/shared/none），不是值。"""
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "lumirss"
        / "migrations"
        / "0117_n019_source_access_cards.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    # 只取语句本体（剥掉 -- 注释）：列集合与「无凭据值字段」都对语句断言。
    statements = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    column_lines = [
        line.strip()
        for line in statements.splitlines()
        if line.strip()
        and not line.strip().startswith("CREATE TABLE")
        and line.strip() != ");"
    ]
    columns = {line.split()[0].lower() for line in column_lines}
    assert columns == {"feed_url", "fields_json", "updated_at"}
    for forbidden in ("secret", "password", "token", "cookie", "credential_value"):
        assert forbidden not in statements.lower().replace("credential_ownership", "")
