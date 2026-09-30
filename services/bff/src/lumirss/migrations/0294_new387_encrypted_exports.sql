-- 0310: NEW-387 个人资料包加密导出台账。
--
-- 硬规则：口令绝不落库、绝不写日志、绝不进配置。台账只存派生参数
-- （KDF 名称/迭代、salt、nonce、算法名）与创建时的一次解密校验结论、
-- 包摘要——这些足以让用户在别处复现解密，且不含任何秘密。
-- 加密包本体只在创建响应里返回给用户，不在服务端保存。

CREATE TABLE IF NOT EXISTS new387_encrypted_exports (
    id TEXT PRIMARY KEY,
    item_count INTEGER NOT NULL DEFAULT 0,
    payload_bytes INTEGER NOT NULL DEFAULT 0,
    kdf TEXT NOT NULL,
    kdf_iterations INTEGER NOT NULL,
    cipher TEXT NOT NULL,
    salt_hex TEXT NOT NULL,
    nonce_hex TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL DEFAULT '',
    decrypt_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
