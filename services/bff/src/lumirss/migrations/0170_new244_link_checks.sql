-- 0170: NEW-244 链接存活复核 —— 复核结果台账。
--
-- link_recheck_results：每批复核把每条资料的结果追加一行。四档诚实
-- 分类：ok（正常）/ redirect（重定向，报 final_url）/ dead（已失效，
-- 404/410）/ unknown（无法判断——超时、网络错误、需要登录、被限流、
-- SSRF 拦截、资料本身没有 URL）。无法判断不冒充失效；raw 细分状态
-- 保留在 detail 里。探测复用 F087 LinkCheckService（并发≤4、HEAD→
-- 有界 GET、8s 超时、SSRF 校验、绝不改写书签 URL）。

CREATE TABLE IF NOT EXISTS link_recheck_results (
    id TEXT PRIMARY KEY,
    target_ref TEXT NOT NULL,
    url TEXT,
    status TEXT NOT NULL CHECK (status IN ('ok', 'redirect', 'dead', 'unknown')),
    http_status INTEGER,
    final_url TEXT,
    detail TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_link_recheck_ref
    ON link_recheck_results (target_ref, checked_at DESC);
