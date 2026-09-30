-- 0311: NEW-388 个人索引导出台账。
--
-- 目录（externalId/题名/创作者/年份/来源/标签）、聚合标签与来源
-- 清单、逐条校验值。不附摘要/正文——索引导出的字段白名单在模块里，
-- 台账只存条数与整个目录的 sha256 校验值。

CREATE TABLE IF NOT EXISTS new388_index_exports (
    id TEXT PRIMARY KEY,
    record_count INTEGER NOT NULL DEFAULT 0,
    tag_count INTEGER NOT NULL DEFAULT 0,
    source_count INTEGER NOT NULL DEFAULT 0,
    catalog_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
