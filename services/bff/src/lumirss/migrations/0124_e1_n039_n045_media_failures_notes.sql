-- 0124 (E1): N039 附件失效检测 + N045 阅读中断便签。
--
-- entry_media_failures：读者上报的失效附件（图片/图集等外链媒体）。
--   (entry_ref, kind, src) 唯一 —— 重复上报 upsert：仅刷新 last_seen_at
--   与命中计数（幂等，绝不翻倍）；每条目最多保留 50 行，超限按
--   last_seen_at 最旧裁剪（插入时执行）。src 存原始 URL；首次上报的
--   first_seen_at 恒定（单项重新加载的 cache-bust 只发生在读取侧，
--   本表绝不改写 src）。kind 仅作呈现分类（image|media|other），
--   不参与任何自动重试——本表没有也不允许有后台重试路径。
--
-- reading_notes：N045 阅读中断便签（每条目一行，entry_ref 主键）。
--   note ≤200 字符（路由层校验）；para_id = 留便签时所在段落锚点
--   （与 F056 reading-progress 的 paraId 同构，重开时定位展示）；
--   updated_at 服务器时间，PUT 恒覆盖（latest-wins，无冲突分支——
--   单行单用户语义）。

CREATE TABLE entry_media_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_ref TEXT NOT NULL,
    kind TEXT NOT NULL,
    src TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE (entry_ref, kind, src)
);

CREATE INDEX ix_entry_media_failures_entry
  ON entry_media_failures(entry_ref, last_seen_at);

CREATE TABLE reading_notes (
    entry_ref TEXT PRIMARY KEY,
    note TEXT NOT NULL,
    para_id TEXT,
    updated_at TEXT NOT NULL
);
