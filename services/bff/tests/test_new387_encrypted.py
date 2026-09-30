"""NEW-387 个人资料包加密导出 — 依赖判定下的加密实现、口令硬规则、
创建时解密校验、错误口令拒绝、A/B 隔离。

依赖判定（与实现一致，如实检验）：uv.lock 无 pyzipper/pyzipx；
``cryptography`` 是既有锁内依赖 → 用 PBKDF2-HMAC-SHA256(600k) +
AES-256-GCM 的密码库原语，不自造算法。
"""

import base64
import json

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new381_fixtures import ZOTERO_RDF

PASSPHRASE = "迁移-口令-2026"


def _seed_two(client, who):
    created = client.post(
        "/api/v1/preservation/zotero/import",
        content=ZOTERO_RDF.encode("utf-8"),
        headers={**who, "content-type": "application/octet-stream"},
    )
    assert created.status_code == 201
    records = client.get("/api/v1/preservation/records", headers=who).json()["records"]
    return [record["id"] for record in records]


def _create(client, who, ids, passphrase=PASSPHRASE):
    return client.post(
        "/api/v1/preservation/encrypted-exports",
        json={"itemIds": ids, "passphrase": passphrase},
        headers=who,
    )


def test_new387_create_verifies_and_payload_decryptable(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    ids = _seed_two(client, a)
    response = _create(client, a, ids)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decryptVerified"] is True
    assert body["itemCount"] == 2
    assert body["format"]["cipher"] == "AES-256-GCM"
    assert "PBKDF2" in body["format"]["kdf"]
    # 用户拿到的包可以用标准原语解回（响应里带参数；包本体 base64）
    blob = base64.b64decode(body["payloadBase64"])
    assert blob.startswith(b"LUMIENC1")
    # 用 verify 端点（即用即弃口令）回传校验
    verify = client.post(
        "/api/v1/preservation/encrypted-exports/verify",
        json={"payloadBase64": body["payloadBase64"], "passphrase": PASSPHRASE},
        headers=a,
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["decryptVerified"] is True
    assert verify.json()["itemCount"] == 2


def test_new387_wrong_passphrase_rejected(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    ids = _seed_two(client, a)
    created = _create(client, a, ids).json()
    verify = client.post(
        "/api/v1/preservation/encrypted-exports/verify",
        json={"payloadBase64": created["payloadBase64"], "passphrase": "错-口令-999"},
        headers=a,
    )
    assert verify.status_code == 400
    assert verify.json()["error"]["type"] == "decrypt_failed"
    # 包体损坏同样拒绝
    corrupted = client.post(
        "/api/v1/preservation/encrypted-exports/verify",
        json={
            "payloadBase64": base64.b64encode(
                b"LUMIENC1-broken-blob"
            ).decode(),
            "passphrase": PASSPHRASE,
        },
        headers=a,
    )
    assert corrupted.status_code == 400


def test_new387_passphrase_never_persisted(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    ids = _seed_two(client, a)
    _create(client, a, ids)
    listing = client.get("/api/v1/preservation/encrypted-exports", headers=a).json()
    assert len(listing["exports"]) == 1
    blob = json.dumps(listing)
    # 台账只存参数与摘要：口令与包本体都不出现
    assert PASSPHRASE not in blob
    assert "payloadBase64" not in blob
    entry = listing["exports"][0]
    assert entry["kdf"] and entry["cipher"] and entry["payloadSha256"]
    assert entry["decryptVerified"] is True


def test_new387_validation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a = ab_env["client"], ab_env["a"]
    short = _create(client, a, [], "short")
    assert short.status_code == 400  # 口令过短
    no_items = _create(client, a, [], PASSPHRASE)
    assert no_items.status_code == 400  # 没有资料
    not_base64 = client.post(
        "/api/v1/preservation/encrypted-exports/verify",
        json={"payloadBase64": "@@not base64@@", "passphrase": PASSPHRASE},
        headers=a,
    )
    assert not_base64.status_code == 400


def test_new387_ab_isolation(ab_env):  # noqa: F811 — pytest 夹具注入
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    ids = _seed_two(client, a)
    _create(client, a, ids)
    # B 的台账为空——A 的加密导出对 B 不可见
    assert client.get("/api/v1/preservation/encrypted-exports", headers=b).json()[
        "exports"
    ] == []
    # B 无法用自己的书目解出 A 的包（资料面隔离：B 库无这些 id）
    b_view = client.get("/api/v1/preservation/records", headers=b).json()
    assert b_view["records"] == []
