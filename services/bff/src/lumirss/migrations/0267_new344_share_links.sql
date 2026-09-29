-- 0267: NEW-344 共享链接使用范围 —— 发布链接前限定可见范围：
-- titles（仅标题目录）/ excerpt（选段）/ full（完整授权正文）。
-- token 只存 SHA-256（token_hash 同一口径），明文一次性返回。
-- scope 创建后不可变（改范围 = 重建链接）。
-- 私人笔记 / 标注永远不在共享载荷里（表结构上就没有这些字段）。

CREATE TABLE IF NOT EXISTS share_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    scope TEXT NOT NULL,
    excerpt_chars INTEGER NOT NULL DEFAULT 200,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS share_link_items (
    link_id INTEGER NOT NULL,
    entry_ref TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (link_id, entry_ref)
);
