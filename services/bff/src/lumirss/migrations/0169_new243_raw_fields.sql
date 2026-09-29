-- 0169: NEW-243 原始 feed 字段查看器 —— 错误映射报告。
--
-- raw_field_reports：用户在字段查看器里对某个字段的「应用映射有误」
-- 报告（哪个字段、问题描述、用户期望）。只追加台账；查看器本体是
-- 派生读（search_entries 投影的脱敏展示），不落库。

CREATE TABLE IF NOT EXISTS raw_field_reports (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    field_key TEXT NOT NULL,
    problem TEXT NOT NULL,
    expected TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_field_reports_entry
    ON raw_field_reports (entry_ref, created_at DESC);
