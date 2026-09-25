-- 0125 (E1): N046 队列冲突合并 + N037 补读入队 + N049 分批撤销台账。
--
-- reading_queue 重建（SQLite 无法修改 CHECK）：source 追加 'recovery'
-- （N037 断更恢复补读经 to-queue 入队的行；其余行原样迁移，幂等重放
-- 安全——本迁移只被应用一次，语句序列在单事务内完成）。
--
-- reading_queue_meta 追加 queue_revision（N046）：每队列日一个单调
-- 递增修订号，队列任何变更（add/remove/done/reorder/segment/merge）
-- 都 +1。客户端携带 expectedRevision 而服务端已前进 → 409
-- queue_revision_conflict（响应体带 currentRevision + 逐 ref 的
-- {serverItem, yourItem} 差异提示）；NULL/缺省 0 = 尚无变更。
--
-- backlog_batch_log：N049 按批确认的撤销台账（cap 5，插入时裁最旧）。
--   refs_json = 该批实际置读成功的裸 entryRef 数组（≤200）； undone
--   0→1 单向（撤销一次性；重复撤销 409 backlog_batch_already_undone）。
--   撤销 = 台账 refs 逐条恢复 read=0（适配器 + 投影镜像，set 语义）。

CREATE TABLE reading_queue_new (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    added_at TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    queue_date TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'budget', 'level', 'recovery')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'done', 'removed')),
    segment TEXT
);

INSERT INTO reading_queue_new (id, entry_ref, added_at, position, queue_date, source, status, segment)
  SELECT id, entry_ref, added_at, position, queue_date, source, status, segment FROM reading_queue;

DROP TABLE reading_queue;

ALTER TABLE reading_queue_new RENAME TO reading_queue;

CREATE UNIQUE INDEX ux_reading_queue_day_ref
  ON reading_queue(queue_date, entry_ref);

CREATE INDEX ix_reading_queue_order
  ON reading_queue(queue_date, position);

ALTER TABLE reading_queue_meta ADD COLUMN queue_revision INTEGER NOT NULL DEFAULT 0;

CREATE TABLE backlog_batch_log (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    group_by TEXT NOT NULL,
    batch_key TEXT NOT NULL,
    refs_json TEXT NOT NULL DEFAULT '[]',
    applied_count INTEGER NOT NULL DEFAULT 0,
    undone INTEGER NOT NULL DEFAULT 0 CHECK (undone IN (0, 1))
);

CREATE INDEX ix_backlog_batch_log_created
  ON backlog_batch_log(created_at);
