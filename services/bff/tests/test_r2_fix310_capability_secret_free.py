"""FIX-310 — 能力/配置响应绝不回传共享 AI Provider 秘密（BASELINE_OK）。

共享 Provider（管理员/操作者配置的 default key 与 profile key）解析后，
面向普通用户的三个能力/配置读面只给「可用选项 + 脱敏标识」：

- GET /api/v1/settings/ai        —— 配置视图：key 只以
  ``keyConfigured``/``envKeyConfigured``/``defaultKeyConfigured``/
  ``purposeStatus.*.keyConfigured`` 布尔出现；
- GET /api/v1/settings/ai/profiles —— 配置档列表：metadata +
  ``keyConfigured`` 布尔，never keys；
- GET /api/v1/ai/purpose-options  —— 用途可选面：profileId/label/model/
  eligible 等标识，never keys。

用合成密钥（"x"*24 形态，非真实凭据）写入 default 与 profile 两级秘密，
断言三个响应的原始 JSON 全文都不含秘密原文——未来任何字段把
``effective_config().api_key`` 带出响应都会在这里爆红。
"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

# 合成密钥（"x"*24 形态；非真实凭据，安全扫描要求无凭据形状字面量）。
SYNTHETIC_DEFAULT_KEY = "x" * 24
SYNTHETIC_PROFILE_KEY = "y" * 24

CAPABILITY_GETS = (
    "/api/v1/settings/ai",
    "/api/v1/settings/ai/profiles",
    "/api/v1/ai/purpose-options?purpose=chat",
    "/api/v1/ai/purpose-options?purpose=summary",
)


def _configure_shared_provider(tmp_path, client: TestClient) -> str:
    """写入两级合成秘密（default + profile），返回 profile id。"""
    app.state.db = Database(tmp_path / "lumi.sqlite")
    app.state.secrets_store = SecretsStore(tmp_path / "secrets.json")

    put_key = client.put(
        "/api/v1/settings/ai/key", json={"value": SYNTHETIC_DEFAULT_KEY}
    )
    assert put_key.status_code == 204, put_key.text

    created = client.post(
        "/api/v1/settings/ai/profiles",
        json={"label": "共享档", "baseUrl": "https://ai.local/v1", "model": "m1"},
    )
    assert created.status_code == 201, created.text
    profile_id = str(created.json()["id"])

    put_secret = client.put(
        f"/api/v1/settings/ai/profiles/{profile_id}/secret",
        json={"value": SYNTHETIC_PROFILE_KEY},
    )
    assert put_secret.status_code == 204, put_secret.text
    return profile_id


def test_capability_responses_never_contain_secret_material(tmp_path):
    with TestClient(app) as client:
        profile_id = _configure_shared_provider(tmp_path, client)
        for url in CAPABILITY_GETS:
            response = client.get(url)
            assert response.status_code == 200, (url, response.text)
            # 原始 JSON 全文不含任一合成秘密（任何字段回传即爆红）。
            assert SYNTHETIC_DEFAULT_KEY not in response.text, url
            assert SYNTHETIC_PROFILE_KEY not in response.text, url
            assert "x" * 24 not in response.text, url

        body = client.get("/api/v1/settings/ai").json()
        # 秘密只以「已配置」布尔出现（脱敏标识语义本身成立）。
        # 未映射 purpose 的 chat 走 default 解析（default key 已配置）。
        assert body["defaultKeyConfigured"] is True
        assert body["purposeStatus"]["chat"]["profileId"] == "default"
        assert body["purposeStatus"]["chat"]["keySource"] == "default_secret"
        assert body["purposeStatus"]["chat"]["keyConfigured"] is True

        profiles = client.get("/api/v1/settings/ai/profiles").json()
        assert profiles[0]["id"] == profile_id
        assert profiles[0]["keyConfigured"] is True

        options = client.get("/api/v1/ai/purpose-options?purpose=chat").json()
        option = next(o for o in options["options"] if o["profileId"] == profile_id)
        assert option["keyConfigured"] is True
        assert option["eligible"] is True


def test_purpose_status_resolution_reports_source_without_key(tmp_path):
    """purposeStatus 的解析口径（source/profileLabel/keySource）全部是
    标识，不含秘密值——响应模型即契约。"""
    with TestClient(app) as client:
        profile_id = _configure_shared_provider(tmp_path, client)
        mapped = client.put(
            "/api/v1/settings/ai/purposes", json={"chat": profile_id}
        )
        assert mapped.status_code == 200, mapped.text
        response = client.get("/api/v1/settings/ai")
        assert response.status_code == 200
        assert SYNTHETIC_PROFILE_KEY not in response.text
        status = response.json()["purposeStatus"]["chat"]
        assert status["source"] == "profile"
        assert status["keySource"] == "profile_secret"
        assert status["keyConfigured"] is True
