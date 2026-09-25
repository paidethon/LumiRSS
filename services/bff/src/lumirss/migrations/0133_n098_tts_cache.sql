-- 0133: N098 音频生成缓存 —— 服务端 TTS 合成结果的 per-user 缓存。
--
-- 键 = (text_hash, voice, model)：同文本 + 同声音 + 同模型命中缓存，
-- 绝不重复调用外部 provider。audio 为 BLOB（单条上限 5MB，应用层
-- 拒绝；总量 50MB LRU，应用层按 last_used_at 裁剪）。per-user 库中
-- 只可能是本人缓存——跨用户物理不可见。
--
-- last_used_at 与 created_at 分离：命中会推进 LRU 位次，但列表展示
-- 的创建时间保持诚实（不被命中改写）。

CREATE TABLE IF NOT EXISTS tts_cache (
    id TEXT PRIMARY KEY,
    text_hash TEXT NOT NULL,
    voice TEXT NOT NULL,
    model TEXT NOT NULL,
    audio BLOB NOT NULL,
    size_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tts_cache_key
    ON tts_cache (text_hash, voice, model);

CREATE INDEX IF NOT EXISTS idx_tts_cache_lru ON tts_cache (last_used_at);
