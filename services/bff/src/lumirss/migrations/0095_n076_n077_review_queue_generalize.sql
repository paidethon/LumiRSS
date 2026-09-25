-- 0097: N076 学习卡片入复习 + N077 复习来源追踪。
--
-- review_queue 从「批注专属」泛化为「复习项」（item_kind）：
-- - annotation_id 从 NOT NULL UNIQUE 改为可空 UNIQUE（SQLite UNIQUE
--   允许多个 NULL）——存量行全部是批注项，原样迁移；
-- - knowledge_card_id 可空 UNIQUE：知识卡片（N076）走同一到期/揭示
--   流程，排期幂等由该列承载；
-- - item_kind CHECK ('annotation'|'knowledge_card')，默认 'annotation'
--   （存量行 = 批注项，诚实延续）；
-- - last_viewed_at（N077）：揭示答案的时刻（来源追踪），只记录时间，
--   不缓存任何原文内容——原文删除后复习项只显示「来源不可用」。
--
-- SQLite 不能直接改列约束：重建表 + 复制 + 原名替换（单文件事务内）。

CREATE TABLE review_queue_generalized (
    id TEXT PRIMARY KEY,
    annotation_id TEXT UNIQUE,
    knowledge_card_id TEXT UNIQUE,
    item_kind TEXT NOT NULL DEFAULT 'annotation' CHECK (item_kind IN ('annotation', 'knowledge_card')),
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'due' CHECK (status IN ('due', 'done')),
    completed_at TEXT,
    last_viewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT INTO review_queue_generalized
    (id, annotation_id, knowledge_card_id, item_kind, due_at, status, completed_at, last_viewed_at, created_at)
SELECT
    id, annotation_id, NULL, 'annotation', due_at, status, completed_at, NULL, created_at
FROM review_queue;

DROP TABLE review_queue;

ALTER TABLE review_queue_generalized RENAME TO review_queue;
