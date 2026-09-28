-- 0150: NEW-207 RSSHub 参数表单 —— 表单化添加的使用台账。
--
-- 每行 = 一次「验证并添加」：路由 id + 脱敏后的参数（敏感键值 →
-- '***'，与 F047/N021 同一 mask_params 规则——参数原值既不进台账也
-- 不进日志）+ 生成的订阅 URL。表单 schema 与验证是纯派生（Lumi 自有
-- 路由目录，离线零网络）；台账只记「添加过什么」。

CREATE TABLE IF NOT EXISTS new207_rsshub_form_uses (
    id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL,
    params_json TEXT NOT NULL,
    feed_url TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_new207_form_uses_route
    ON new207_rsshub_form_uses (route_id, created_at);
