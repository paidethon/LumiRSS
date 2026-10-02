-- 0326: R18 RSSHub 导入来源映射 —— 每用户库。
--
-- OPML 导入策略切换（原生地址 → RSSHub 地址）的可追溯台账：
-- original_url 永不改写（撤销回原生的依据）；rsshub_url 是当前
-- 实际订阅地址；status: active | reverted（撤销映射，保留历史）。
-- kept_old_source: 原 URL 已在订阅中且按「保留旧源 + 关联新源」
-- 处理时为 1（FreshRSS 条目 id 内嵌 feed 地址、已读/收藏状态无法
-- 跨源安全迁移，故绝不自动退订旧源——诚实边界，报告说明）。
--
-- 凭据不落库：路由路径里可能携带的敏感查询参数在生成订阅地址时
-- 已被 build_path 的段编码约束；本表不存任何凭据字段。

CREATE TABLE IF NOT EXISTS rsshub_source_mappings (
    id INTEGER PRIMARY KEY,
    mapping_uuid TEXT NOT NULL UNIQUE,
    original_url TEXT NOT NULL,
    rsshub_url TEXT NOT NULL,
    namespace TEXT,
    route_path TEXT,
    strategy TEXT NOT NULL,
    kept_old_source INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    reverted_at TEXT
);
