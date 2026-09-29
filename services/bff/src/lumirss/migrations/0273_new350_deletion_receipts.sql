-- 0273: NEW-350 个人数据删除范围预览与处理回执 —— 确认注销时实际
-- 执行的处理逐类留痕（类别 / 动作 / 数量），retained 清单与回执同存
-- （回执是已发生事实，不是承诺）。

CREATE TABLE IF NOT EXISTS deletion_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_at TEXT NOT NULL,
    scheduled_deletion_at TEXT,
    actions_json TEXT NOT NULL,
    retained_json TEXT NOT NULL
);
