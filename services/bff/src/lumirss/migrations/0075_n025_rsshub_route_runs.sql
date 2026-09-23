-- 0072: N025 路由健康时间线（每用户库）。
--
-- 每次 RSSHub 路由 preview/refresh/subscribe 尝试写一行；插入后按
-- route_key 裁剪到最近 20 条（rsshub_route_store.MAX_RUNS_PER_ROUTE）。
-- 行内只有路由键、结果分类与时延等元数据——没有任何凭据/密钥字段；
-- route_key 里的参数值本身已在写入前脱敏（0071 同一规则）。
--
-- status：ok / failed。failure_class 为 N026 稳定分类
-- （rsshub_unreachable / upstream_reject / auth_failure / not_found /
-- rate_limited / no_new_content / network_error），ok 时可为 NULL
-- （新路由 0 条目是正常状态，entry_count=0 + status=ok 如实记录）。

CREATE TABLE IF NOT EXISTS rsshub_route_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_key TEXT NOT NULL,
    ran_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    duration_ms INTEGER NOT NULL,
    entry_count INTEGER,
    failure_class TEXT
);

CREATE INDEX IF NOT EXISTS idx_rsshub_route_runs_key_time
    ON rsshub_route_runs(route_key, ran_at);
