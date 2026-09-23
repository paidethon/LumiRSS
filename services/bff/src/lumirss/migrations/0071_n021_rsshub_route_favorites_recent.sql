-- 0071: N021 路由收藏与最近使用（每用户库）。
--
-- route_key = 模板 id + 参数签名（见 rsshub_route_store.compute_route_key），
-- 参数只存「键 + 脱敏后的值」：F047 敏感参数（token/key/secret/sign/code/
-- password 类键名）在写入前替换为 '***' 哨兵——原始值永不入库、永不出
-- 服务端。收藏/最近使用是跨设备的服务端状态，不是浏览器本地存储。

CREATE TABLE IF NOT EXISTS rsshub_route_favorites (
    route_key TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    params_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rsshub_route_recent (
    route_key TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    last_used_at TEXT NOT NULL,
    last_success_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_rsshub_route_recent_used
    ON rsshub_route_recent(last_used_at DESC);
