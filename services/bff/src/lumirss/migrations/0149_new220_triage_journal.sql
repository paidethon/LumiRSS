-- 0149 (NEW-220): 个人收件箱处理记录 —— 整理轨迹台账。
-- 每次整理保存 from_location → to_location、涉及 refs 与用户给出的
-- 原因；按 created_at（日期）追踪。per-user 库 = 只可能是本人的记录。

CREATE TABLE IF NOT EXISTS new220_triage_journal (
    id TEXT PRIMARY KEY,
    from_location TEXT NOT NULL,
    to_location TEXT NOT NULL,
    refs_json TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_new220_journal_date
  ON new220_triage_journal (created_at);
