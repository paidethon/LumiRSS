-- 0210: NEW-284 简报缺刊诊断 —— 生成失败时落库具体缺失输入与执行阶段。
--
-- 每次生成尝试一行：stage(candidates/sections/assemble) + status
-- (failed/ok) + missing_json([{field,reason}])。失败绝不伪装成空白
-- 成功页：422 带同一诊断体，用户补输入后重跑，attempts 留下
-- failed → ok 的完整轨迹（诚实台账）。

CREATE TABLE IF NOT EXISTS briefing_attempts (
    id TEXT PRIMARY KEY,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    inputs_json TEXT NOT NULL DEFAULT '{}',
    missing_json TEXT NOT NULL DEFAULT '[]',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefing_attempts_created
    ON briefing_attempts (created_at DESC);
