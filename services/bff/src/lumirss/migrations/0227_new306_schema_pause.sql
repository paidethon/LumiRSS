-- 0232: NEW-306 API 抓取变更预警 —— 上游字段结构与用户确认过的基线
-- 不一致且影响必要字段时，暂停该来源的写入（保留 last-known-good，
-- 不再发布新条目），直到用户确认新映射（resume）。
--
-- write_paused：0/1；pause_reason：暂停时的人类可读 JSON 摘要
-- （missing/type_changed 列表）。两列加在 per-user 库 api_sources。

ALTER TABLE api_sources ADD COLUMN write_paused INTEGER NOT NULL DEFAULT 0;
ALTER TABLE api_sources ADD COLUMN pause_reason TEXT;
