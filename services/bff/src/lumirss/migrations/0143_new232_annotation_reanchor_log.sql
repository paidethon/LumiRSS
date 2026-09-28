-- 0143: NEW-232 失效标注重定位 —— 手动重锚历史（append-only）。
--
-- 用户在原文更新后手动选择新段落重新锚定旧批注：旧锚点 JSON 与旧
-- 摘录先完整写入本表再改批注本体。只追加、不删除、不封顶——
-- 「保留旧引文与旧位置」是硬要求（与 N071 repair_log 的 cap 10
-- 不同：那是自动修复的滚动窗口；本表是用户显式动作的永久台账）。

CREATE TABLE IF NOT EXISTS annotation_reanchor_log (
    id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL,
    old_anchor_json TEXT NOT NULL,
    old_excerpt TEXT NOT NULL,
    new_anchor_json TEXT NOT NULL,
    new_excerpt TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    reanchored_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_annotation_reanchor_log
    ON annotation_reanchor_log (annotation_id, reanchored_at DESC);
