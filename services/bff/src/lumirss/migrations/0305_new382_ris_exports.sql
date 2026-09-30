-- 0305: NEW-382 RIS 引文导出与往返校验台账。
--
-- 每次导出记录条数、往返重解析后的逐条差异（roundtrip_report_json）
-- 与整体结论。RIS 记录本体在 0304 的 new381_bib_records
-- （source_format='ris'），这里只存导出与校验结论，不复制书目数据。

CREATE TABLE IF NOT EXISTS new382_ris_exports (
    id TEXT PRIMARY KEY,
    record_count INTEGER NOT NULL DEFAULT 0,
    roundtrip_ok INTEGER NOT NULL DEFAULT 0,
    roundtrip_report_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
