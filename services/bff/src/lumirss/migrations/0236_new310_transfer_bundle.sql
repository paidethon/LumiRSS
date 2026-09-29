-- 0236: NEW-310 接入配置转移包 —— 导出不含秘密的 API 映射与调度
-- 配置；导入时为每个 credentialRef 重新选择本实例凭据引用（映射到
-- 既有来源 = 合并进该来源保留其凭据；generate = 新建并铸造新凭据；
-- 未选择 = 跳过并如实报告）。
--
-- api_transfer_imports 以包摘要（canonical JSON sha256）去重 ——
-- 同一包二次导入返回 409 already_imported，不产生重复来源。

CREATE TABLE IF NOT EXISTS api_transfer_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_digest TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    created_count INTEGER NOT NULL,
    merged_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0
);
