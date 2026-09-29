-- 0211: NEW-285 个人简报 RSS 发布 —— 用户确认期次的可撤销私有订阅。
--
-- 每用户单行；只存 token 的 SHA-256 哈希（token_hash.py 同一口径），
-- 明文只在 enable/rotate 响应里出现一次。enabled=0 / revoked_at 非空
-- → 公开路由同一 404（撤销立即生效，不泄露存在性）。feed 内容只有
-- 确认期次的摘要卡（标题/摘录/链接 + 编辑来源标记），绝不自动公开
-- 原始私人笔记（本组条目根本不存笔记）。

CREATE TABLE IF NOT EXISTS briefing_feed_tokens (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    rotated_at TEXT,
    revoked_at TEXT
);
