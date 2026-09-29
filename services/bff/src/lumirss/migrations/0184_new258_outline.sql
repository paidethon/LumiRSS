-- 0184: NEW-258 研究大纲编排。
--
-- research_outline_sections：章节大纲（position 决定顺序）。
-- research_outline_items：挂进章节的素材行——kind='quote' 选定引文
-- （citation 记出处文字）/ 'note' 笔记 / 'summary' 小结。
--
-- 排序诚实边界：不实现拖拽（本部署无 DnD 基建），提供 move up/down
-- 与「分配到章节」两个显式动作；接口 note 字段向用户如实说明
-- 「顺序调整 = 上移/下移 + 分配，不是拖拽」。

CREATE TABLE IF NOT EXISTS research_outline_sections (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_outline_sections
    ON research_outline_sections (project_id, position ASC);

CREATE TABLE IF NOT EXISTS research_outline_items (
    id TEXT PRIMARY KEY,
    section_id TEXT NOT NULL,
    kind TEXT NOT NULL
        CHECK (kind IN ('quote', 'note', 'summary')),
    content TEXT NOT NULL,
    citation TEXT,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_outline_items
    ON research_outline_items (section_id, position ASC);
