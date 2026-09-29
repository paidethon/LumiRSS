-- 0192: NEW-266 分段翻译优先队列 —— 用户指定的先行翻译顺序。
--
-- 用户为某篇条目登记块优先级（当前章节/选段先行，之后可追加其他
-- 段）；每 (entry_ref, block_index) 唯一（重复追加是 no-op，保序）。
-- seq 是每篇内的单调登记序号（登记顺序即执行顺序；同一毫秒内的
-- 批量追加也不会因时间戳并列而乱序）。
-- 执行走显式 run：队列中尚未有成功缓存行的块才发 provider，已有
-- 结果不重复收费。每篇上限 QUEUE_CAP 条。

CREATE TABLE IF NOT EXISTS translation_priority_queue (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    UNIQUE (entry_ref, block_index)
);

CREATE INDEX IF NOT EXISTS idx_translation_priority_queue_ref
    ON translation_priority_queue (entry_ref, seq);
