"""NEW-387 个人资料包加密导出 —— 用户选择资料与本次口令，生成
本地可解密的加密包，并在创建时做一次解密校验。

依赖判定（诚实记录）：

- uv.lock / pyproject 中没有 pyzipper / pyzipx（WinZip-AES zip）；
- ``cryptography`` 已在锁文件中（fido2 的既有传递依赖，venv 实装）；
- 因此加密腿用 ``cryptography`` 的成熟原语实现：PBKDF2-HMAC-SHA256
  （600,000 次迭代，16B 随机 salt）派生 256 位密钥，AES-256-GCM
  （12B 随机 nonce）整包加密一个标准 zip 载荷。没有自造密码算法——
  全部是密码库原语；容器格式在包头显式自述，任何标准实现可复现解密。

包头（明文自述，非秘密）::

    b"LUMIENC1" | kdf_name(1B) | kdf_iter(4B BE) | salt_len(1B) |
    salt | nonce_len(1B) | nonce | AES-256-GCM(zip_bytes + AAD=包头前缀)

硬规则：

- 口令不写日志（本模块无任何日志语句；请求体日志中间件只记方法/路
  径/状态）；口令不保存配置/数据库（台账只存 KDF 参数、salt、nonce、
  包摘要与解密校验结论——均非秘密）；不自造密码算法；
- 服务端只在创建时用同一口令做一次解密校验（decrypt_verified），
  加密包本体只在创建响应里返回，服务端不保存、无法重建；
- payload ≤4MiB，条目 ≤500（zip 载荷 + JSON 记录清单）。

per-user：资料面是 member 自己的书目库。
"""

import base64
import hashlib
import io
import json
import os
import uuid as _uuid
import zipfile
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from lumirss.new381_bib import BibStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_ITEMS = 500
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MIN_PASSPHRASE_LEN = 8
KDF_NAME = b"P"
KDF_ITERATIONS = 600_000
_MAGIC = b"LUMIENC1"
_SALT_BYTES = 16
_NONCE_BYTES = 12
_CIPH_NAME = "AES-256-GCM"
_KDF_LABEL = "PBKDF2-HMAC-SHA256"


class EncryptedExportInvalid(ValueError):
    """加密导出请求非法（映射 400）。"""


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def build_payload(records: list[dict[str, Any]]) -> bytes:
    """选中书目 → 标准 zip（manifest.json + records.json）。"""
    if not records:
        raise EncryptedExportInvalid("请至少选择一条资料。")
    if len(records) > MAX_ITEMS:
        raise EncryptedExportInvalid(f"一次最多打包 {MAX_ITEMS} 条资料。")
    manifest = {
        "generator": "LumiRSS encrypted export",
        "itemCount": len(records),
        "exportedAt": utc_now(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr(
            "records.json", json.dumps(records, ensure_ascii=False, indent=1)
        )
    payload = buffer.getvalue()
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise EncryptedExportInvalid("资料包超过 4MiB 上限，请缩小选择范围。")
    return payload


def encrypt(payload: bytes, passphrase: str) -> tuple[bytes, dict[str, Any]]:
    """zip 载荷 → LUMIENC1 加密包 + 明文参数（salt/nonce 非秘密）。

    布局：magic(8) | salt_len(1) | salt | kdf 名(1) | 迭代(4 BE) |
    nonce_len(1) | nonce | ciphertext(AESGCM, AAD = 前面全部包头)。
    """
    _require_passphrase(passphrase)
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    key = _derive_key(passphrase, salt)
    header = (
        _MAGIC
        + bytes([len(salt)])
        + salt
        + KDF_NAME[:1]
        + KDF_ITERATIONS.to_bytes(4, "big")
        + bytes([len(nonce)])
        + nonce
    )
    ciphertext = AESGCM(key).encrypt(nonce, payload, header)
    return header + ciphertext, {
        "kdf": _KDF_LABEL,
        "kdfIterations": KDF_ITERATIONS,
        "cipher": _CIPH_NAME,
        "saltHex": salt.hex(),
        "nonceHex": nonce.hex(),
    }


def decrypt(blob: bytes, passphrase: str) -> tuple[bytes, dict[str, Any]]:
    """LUMIENC1 包 → zip 载荷 + 参数（口令错 / 包损坏 → 异常）。"""
    if not blob.startswith(_MAGIC):
        raise EncryptedExportInvalid("不是 LumiRSS 加密包（缺少 LUMIENC1 包头）。")
    try:
        pos = len(_MAGIC)
        salt_len = blob[pos]
        pos += 1
        salt = blob[pos : pos + salt_len]
        pos += salt_len
        # kdf 名 1B + 迭代 4B + nonce 长度 1B
        kdf_byte = blob[pos : pos + 1]
        pos += 1
        iterations = int.from_bytes(blob[pos : pos + 4], "big")
        pos += 4
        nonce_len = blob[pos]
        pos += 1
        nonce = blob[pos : pos + nonce_len]
        pos += nonce_len
        ciphertext = blob[pos:]
        key = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=iterations,
        ).derive(passphrase.encode("utf-8"))
        payload = AESGCM(key).decrypt(nonce, ciphertext, blob[:pos])
    except (IndexError, ValueError) as exc:
        raise EncryptedExportInvalid("加密包格式无法解析。") from exc
    except Exception as exc:  # noqa: BLE001 — InvalidTag 等统一为口令错
        raise EncryptedExportInvalid(
            "解密失败：口令不匹配或包已损坏。"
        ) from exc
    return payload, {
        "kdf": _KDF_LABEL if kdf_byte == KDF_NAME[:1] else f"raw:{kdf_byte!r}",
        "kdfIterations": iterations,
        "cipher": _CIPH_NAME,
    }


def _require_passphrase(passphrase: str) -> None:
    if not isinstance(passphrase, str) or len(passphrase) < MIN_PASSPHRASE_LEN:
        raise EncryptedExportInvalid(
            f"口令至少 {MIN_PASSPHRASE_LEN} 个字符（本次会话使用，不保存）。"
        )


def verify_zip(payload: bytes) -> dict[str, Any]:
    """解密后的一次校验：zip 完整性 + 清单可读（不返回记录内容）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if "manifest.json" not in names or "records.json" not in names:
                raise EncryptedExportInvalid("加密包内容不完整。")
            manifest = json.loads(archive.read("manifest.json"))
            records = json.loads(archive.read("records.json"))
    except zipfile.BadZipFile as exc:
        raise EncryptedExportInvalid("解密后的 zip 载荷已损坏。") from exc
    return {
        "itemCount": int(manifest.get("itemCount", len(records))),
        "names": names,
        "payloadSha256": hashlib.sha256(payload).hexdigest(),
    }


async def create_encrypted_export(
    db: Database, item_ids: list[str], passphrase: str
) -> dict[str, Any]:
    """选中书目 + 本次口令 → 加密包（base64）+ 创建时解密校验结论。"""
    await db.migrate()
    ids = [str(ref).strip() for ref in item_ids if str(ref).strip()]
    records = await BibStore(db).get_records_by_ids(ids)
    found = {record["id"] for record in records}
    missing = [ref for ref in ids if ref not in found]
    payload = build_payload(records)
    blob, params = encrypt(payload, passphrase)
    # 一次解密校验：同一口令立刻回解，验证 zip 完整与清单可读。
    roundtrip_payload, _ = decrypt(blob, passphrase)
    verified = verify_zip(roundtrip_payload)
    export_id = f"encexp-{_uuid.uuid4().hex[:12]}"
    await db.execute(
        "INSERT INTO new387_encrypted_exports"
        " (id, item_count, payload_bytes, kdf, kdf_iterations, cipher, salt_hex,"
        " nonce_hex, payload_sha256, decrypt_verified, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (
            export_id,
            int(verified["itemCount"]),
            len(blob),
            params["kdf"],
            params["kdfIterations"],
            params["cipher"],
            params["saltHex"],
            params["nonceHex"],
            hashlib.sha256(blob).hexdigest(),
            utc_now(),
        ),
    )
    return {
        "id": export_id,
        "itemCount": verified["itemCount"],
        "payloadBytes": len(blob),
        "payloadBase64": base64.b64encode(blob).decode("ascii"),
        "payloadSha256": hashlib.sha256(blob).hexdigest(),
        "decryptVerified": True,
        "format": {
            "magic": _MAGIC.decode("ascii"),
            "kdf": params["kdf"],
            "kdfIterations": params["kdfIterations"],
            "cipher": params["cipher"],
            "note": "口令只用于本次生成与解密校验，Lumi 不保存、不写日志。",
        },
        "missing": missing,
    }


async def list_exports(db: Database) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, item_count, payload_bytes, kdf, kdf_iterations, cipher,"
        " payload_sha256, decrypt_verified, created_at FROM new387_encrypted_exports"
        " ORDER BY created_at DESC, id ASC LIMIT 100"
    )
    return [
        {
            "id": str(row["id"]),
            "itemCount": int(row["item_count"]),
            "payloadBytes": int(row["payload_bytes"]),
            "kdf": str(row["kdf"]),
            "kdfIterations": int(row["kdf_iterations"]),
            "cipher": str(row["cipher"]),
            "payloadSha256": str(row["payload_sha256"]),
            "decryptVerified": bool(row["decrypt_verified"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]
