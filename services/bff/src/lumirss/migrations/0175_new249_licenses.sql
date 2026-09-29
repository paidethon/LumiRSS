-- 0175: NEW-249 资料引用许可证提示 —— 用户许可证记录。
--
-- license_records：用户为一条资料记录的许可证信息。info_source 区分
-- 「用户记录」（用户自行登记的判断）与「来源页面明示」（用户在来源
-- 页面看到的显式声明）；license_text 为空串 = 明确记录「未声明」。
-- 没有记录 = 未知（查询时如实标 unknown，绝不猜默认许可证）。
-- 汇编导出提示只转述这些记录，不构成法律意见。

CREATE TABLE IF NOT EXISTS license_records (
    target_ref TEXT PRIMARY KEY,
    license_text TEXT NOT NULL DEFAULT '',
    info_source TEXT NOT NULL CHECK (info_source IN ('user_record', 'source_explicit')),
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
