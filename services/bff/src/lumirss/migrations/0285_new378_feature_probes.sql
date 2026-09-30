-- 0301: NEW-378 实例功能依赖图 —— 每个依赖项保留一次最新本地探测
-- 结果（configured + 脱敏 detail + 实际探测时间）。探测只做本地
-- 配置/文件存在性检查，绝不发外部网络请求，也绝不存秘密值
-- （秘密只有「已配置 / 未配置」两个状态）。

CREATE TABLE IF NOT EXISTS admin_feature_probes (
    dep_key TEXT PRIMARY KEY,
    configured INTEGER NOT NULL CHECK (configured IN (0, 1)),
    detail TEXT NOT NULL,
    probed_at TEXT NOT NULL
);
