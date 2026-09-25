-- 0120: N028 路由升级兼容检查 — 管理员级预升级探测报告。
--
-- 每次检查 = 对运营者自己的 RSSHub 路由集合（当前实例）做一次有界
-- preview 探测，落一行报告：target_image 是运营者声明的目标镜像
-- （检查时新镜像尚未运行 → 报告视图按 pending 呈现）；checked_image
-- 是当前目录快照（rsshub_routes.generated.json _meta.rsshubImage）
-- 的固定 sha —— 逐路由状态永远锚定到这个已知的镜像证据上。
--
-- 范围（诚实边界，文档化于端点 docstring）：检查只覆盖管理员本人
-- 用户库可见的路由键（订阅 URL 反推 + 收藏/最近使用），绝不跨用户
-- 聚合逐条路由内容；报告行保存在管理员自己的用户库里（本迁移落在
-- 每用户库），keep-last-3。
--
-- routes_json：[{routeKey, status(ok|failed|skipped), entryCount,
-- failureClass, origin}]——参数在采集层已脱敏，绝无敏感值可入行。

CREATE TABLE IF NOT EXISTS rsshub_upgrade_checks (
    id INTEGER PRIMARY KEY,
    ran_at TEXT NOT NULL,
    target_image TEXT,
    checked_image TEXT,
    route_count INTEGER NOT NULL,
    ok_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    skipped_count INTEGER NOT NULL,
    routes_json TEXT NOT NULL
);
