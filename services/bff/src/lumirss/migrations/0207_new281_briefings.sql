-- 0207: NEW-281 个人简报编排台 —— 用户自选文章排成的「简报期次」。
--
-- briefings = 一期简报（draft → confirmed；确认后才可被 RSS 发布(285)、
-- EML 导出(289)、追加更正(290)）。range_from/range_to 是文章选取窗口
-- （ISO UTC，to 开区间）。sections_json = 栏目定义 [{key,label}]，顺序
-- 即栏目顺序；条目挂在 section_key 上。
--
-- briefing_items.provenance（NEW-287）：manual=人工选入 / rule=规则推荐，
-- 编辑面如实区分，读者能看到编辑来源。pulled_back（NEW-283）：迟到文章
-- 被手动调回本期时置 1——系统绝不静默改写窗口归属。
--
-- 边界：条目只存摘要卡（标题/来源/链接/摘录 ≤200 字），不 shadow-copy
-- FreshRSS 正文，也不存任何私人笔记——RSS/EML 面没有可泄露的笔记。

CREATE TABLE IF NOT EXISTS briefings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    range_from TEXT NOT NULL DEFAULT '',
    range_to TEXT NOT NULL DEFAULT '',
    sections_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'compose',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS briefing_items (
    id TEXT PRIMARY KEY,
    briefing_id TEXT NOT NULL,
    entry_ref TEXT NOT NULL,
    item_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    feed_title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    section_key TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    provenance TEXT NOT NULL DEFAULT 'manual',
    pulled_back INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefing_items_issue
    ON briefing_items (briefing_id, position ASC);
CREATE INDEX IF NOT EXISTS idx_briefing_items_entry
    ON briefing_items (entry_ref);
CREATE INDEX IF NOT EXISTS idx_briefings_status
    ON briefings (status, created_at DESC);
