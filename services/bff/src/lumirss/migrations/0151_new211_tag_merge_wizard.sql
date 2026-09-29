-- 0142 (NEW-211): 标签合并向导 —— 多个个人标签 → 单一目标标签的原子合并，
-- 每次合并在同一事务内落一行可撤销的映射记录（源标签 + 全部绑定快照）。
-- 与 N150 单行槽位不同：本表保留最近 10 条记录（插入时裁最旧），撤销按
-- log id 定向，24h 窗口内有效。per-user 库 = 只可能是本人的标签。

CREATE TABLE IF NOT EXISTS new211_merge_logs (
    id TEXT PRIMARY KEY,
    target_tag_id INTEGER NOT NULL,
    target_name TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
