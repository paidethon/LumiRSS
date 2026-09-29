-- 0284: NEW-365 搜索排除词建议审批 —— 用户对某查询确认后的排除词。
--
-- 只有用户显式确认的词才进入本表（建议本身不落库——候选由标记的
-- 不相关结果实时提取）；word 进 GET /search 的 exclude 参数由客户端
-- 应用，删除即撤销。per-user 库表：A 的确认对 B 不可见。
--
-- query_key：查询规范化键（casefold + 压缩空白），同查询跨写法共享
-- 已确认词；(query_key, word) 唯一 —— 重复确认幂等。

CREATE TABLE IF NOT EXISTS search_exclusion_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_key TEXT NOT NULL,
    word TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (query_key, word)
);

CREATE INDEX IF NOT EXISTS idx_search_exclusion_words_query
    ON search_exclusion_words (query_key, id DESC);
