-- 0126: N118 工作区自动收集规则 —— 手动触发的匹配收集。
--
-- 规则是「来源条件 + 上限 + 开关」，绝不存条目内容：应用（apply）时
-- 从派生投影（search_entries）实时匹配，命中以 item_ref 引用进工作区
--（幂等，绝不复制内容——ADR 0004）。added_count 记录本规则累计新增
-- 数（max_items 是终身上限，不是每次配额）。规则随工作区删除级联消失。
-- enabled=0（暂停）时 apply/preview 调用方诚实跳过；本表绝不是后台
-- 抓取器的状态——没有后台任务读它（文档化语义：手动按钮触发）。
CREATE TABLE workspace_collect_rules (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    source_feed_url TEXT,
    source_tag TEXT,
    keyword TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    max_items INTEGER NOT NULL DEFAULT 100,
    added_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX ix_workspace_collect_rules_ws ON workspace_collect_rules(workspace_id, created_at);
