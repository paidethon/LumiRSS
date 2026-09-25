-- 0121: N030 路由可复用参数方案 — 每用户私有参数预设。
--
-- 方案 = {route_key, template_id, name, params_json}：保存 RSSHub
-- 路由参数组合，之后可一键回填参数表单（create-draft）。安全属性与
-- 收藏/最近使用一致（rsshub_route_store.mask_params 同一规则）：
-- 敏感键（token/key/secret/sign/code/password）的值入库前替换为
-- '***' 哨兵，has_sensitive 标记该方案含敏感参数——应用（回填）时
-- 这些键必须重新输入（UI 需重新绑定），真实值从不落盘。
--
-- cap 20 行/用户（插入时裁剪策略由 store 层执行：超限拒绝创建，
-- 稳定错误 rsshub_param_preset_limit）。表落在每用户库（本迁移对
-- 每个用户库生效），账户间天然隔离。

CREATE TABLE IF NOT EXISTS rsshub_param_presets (
    id TEXT PRIMARY KEY,
    route_key TEXT NOT NULL,
    template_id TEXT NOT NULL,
    name TEXT NOT NULL,
    params_json TEXT NOT NULL,
    has_sensitive INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rsshub_param_presets_created
    ON rsshub_param_presets(created_at DESC, id);
