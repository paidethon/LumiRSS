-- 0201: NEW-276 AI 失败重放诊断 —— 重放血缘（原始失败任务 → 新任务）。
--
-- 脱敏诊断本身从 ai_task_log 行派生（kind/model/input_chars/error_type
-- —— 结构字段，绝不含文章正文或问题内容）；这里只持久化重放动作的
-- 血缘：mode = same（相同配置重试）| modified（修改参数后新建）。

CREATE TABLE IF NOT EXISTS ai_task_replays (
    id TEXT PRIMARY KEY,
    original_task_id TEXT NOT NULL,
    replay_task_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_task_replays_original
    ON ai_task_replays (original_task_id, created_at DESC);
