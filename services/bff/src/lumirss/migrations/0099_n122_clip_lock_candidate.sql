-- 0101 (N122): 剪藏版本锁定 + 候选版本。
-- locked = 1 时：任何自动再提取只落候选（candidate_*），绝不覆盖当前
-- 展示版本（revised_content_html 优先，否则原始 content_html）；
-- 对展示内容的覆盖式写入（PATCH revision / 应用候选）→ 409 clip_locked。
ALTER TABLE library_clips ADD COLUMN locked INTEGER NOT NULL DEFAULT 0;

ALTER TABLE library_clips ADD COLUMN candidate_content_html TEXT;
ALTER TABLE library_clips ADD COLUMN candidate_content_text TEXT;
ALTER TABLE library_clips ADD COLUMN candidate_title TEXT;
ALTER TABLE library_clips ADD COLUMN candidate_fetched_at TEXT;
