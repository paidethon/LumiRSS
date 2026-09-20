-- 0066: §13.4 安全整改——bearer token 哈希化存储的标记列。
--
-- 五个凭据落点中的四个表列改为只存 SHA-256 hex（gpt_digest feed token
-- 在 secrets.json 文件，不在 SQLite）。存量明文的迁移不在 SQL 里做
-- （SQLite 无 sha256）：0066 只加「已哈希」标记列（默认 0 = 旧明文），
-- 服务端启动时由 token_backfill.backfill_token_hashes 用 Python 逐行
-- 原地哈希并置 1；写入路径（创建/轮换）哈希后以 1 落库。回填前窗口
-- 内校验走 verify_token 的旧明文兼容分支——旧链接/旧 bearer 永不失效。
ALTER TABLE mail_bridge_lists ADD COLUMN secret_is_hash INTEGER NOT NULL DEFAULT 0;
ALTER TABLE inbox_sources ADD COLUMN secret_is_hash INTEGER NOT NULL DEFAULT 0;
ALTER TABLE saved_searches ADD COLUMN feed_secret_is_hash INTEGER NOT NULL DEFAULT 0;
ALTER TABLE api_sources ADD COLUMN secret_is_hash INTEGER NOT NULL DEFAULT 0;
