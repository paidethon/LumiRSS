-- 0208: NEW-282 简报去重审批 —— 已在以前期次收录的条目，收录前必须
-- 由用户显式决定：include(重收) / defer(仅列后续) / skip(跳过)。
--
-- 没有决定就提交 → 409 审批拦截（绝不静默重收或静默丢条目）。决定
-- 逐条落库（append 记录，保留 prior_issue 指向以前哪一期收过）。
-- defer 的条目进入「后续清单」：后续任何一期重新收录该条目后，清单
-- 里自然消失（应用层过滤，不删历史决定行）。

CREATE TABLE IF NOT EXISTS briefing_dup_decisions (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_in_issue TEXT NOT NULL DEFAULT '',
    prior_issue TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_briefing_dup_decisions_entry
    ON briefing_dup_decisions (entry_ref, decided_at DESC);
