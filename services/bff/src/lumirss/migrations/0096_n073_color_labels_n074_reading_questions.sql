-- 0096: N073 批注颜色语义 + N074 阅读问题清单。
--
-- annotation_color_labels：per-user 颜色语义标签（color 主键 = 批注
-- 调色板原始色名；label 空 = 未命名，Web 端诚实显示原始色名）。
--
-- reading_questions：阅读问题清单（question 必填；status 只在
-- open/done 之间切换）。entry_ref / annotation_id / workspace_id 都是
-- 可选链接（问题可以先记下来，之后再关联来源）。原文删除只影响
-- 展示层的定位可用性，问题文本本身保留（无内容缓存）。

CREATE TABLE IF NOT EXISTS annotation_color_labels (
    color TEXT PRIMARY KEY,
    label TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS reading_questions (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    entry_ref TEXT,
    annotation_id TEXT,
    workspace_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_reading_questions_entry
    ON reading_questions (entry_ref);
CREATE INDEX IF NOT EXISTS idx_reading_questions_annotation
    ON reading_questions (annotation_id);
