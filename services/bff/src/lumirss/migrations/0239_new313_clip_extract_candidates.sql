-- 0239: NEW-313 剪藏正文候选对照 —— 同一次抓取的两种正文提取结果并列
-- 展示，用户选择更完整的版本。
--
-- strategy='article'（正文评分提取）/ 'fulltext'（保真全文兜底）都来自
-- 同一次有界抓取的同一份原始 HTML；保存前都过 sanitize_html 边界。
-- chosen 单选（每剪藏至多一个应用版本）：应用 = 写入 F089 修订槽
-- （revised_content_html），原始 content_html 永不覆盖、笔记锚点
-- （revised_note / 批注 / lumi_notes）一字不动。per-user。

CREATE TABLE IF NOT EXISTS clip_extract_candidates (
    id TEXT PRIMARY KEY,
    clip_item_uuid TEXT NOT NULL,
    strategy TEXT NOT NULL CHECK (strategy IN ('article', 'fulltext')),
    title TEXT NOT NULL DEFAULT '',
    content_html TEXT NOT NULL,
    content_text TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    chosen INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clip_extract_candidates
    ON clip_extract_candidates (clip_item_uuid, created_at DESC);
