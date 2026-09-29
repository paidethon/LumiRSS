-- 0245: NEW-319 资料重新提取请求 —— 用户对已存网页发起一次新提取，
-- 旧版保持可读，新版完成后由用户选择。
--
-- 一行 = 一次重提取请求：pending → done/failed 状态真实迁移；done 行
-- 保存新提取的净化正文（与创建剪藏同一 sanitize 边界），在用户显式
-- apply 之前绝不改动 library_clips 的任何列；failed 行如实带原因。
-- apply = 写入 F089 修订槽（revised_content_html），原始 content_html
-- 永不覆盖、笔记锚点不动。请求上限 50 行，超限裁最老（与既有 cap
-- 模式一致）。per-user。

CREATE TABLE IF NOT EXISTS clip_reextractions (
    id TEXT PRIMARY KEY,
    clip_item_uuid TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    title TEXT NOT NULL DEFAULT '',
    content_html TEXT NOT NULL DEFAULT '',
    content_text TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    requested_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_clip_reextractions_clip
    ON clip_reextractions (clip_item_uuid, requested_at DESC);

CREATE TABLE IF NOT EXISTS clip_reextractions_applied (
    reextraction_id TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
