-- 0320: NEW-397 实例服务状态 —— 真实本地检测台账。
--
-- 每次检测（control 库连通、FreshRSS/RSSHub 配置面等）追加一行，
-- 读取侧每面取最新一条 = 「最近检测时间」。检测只用本地事实
-- （SELECT 1 / 配置字段存在性），不做网络探测、不计算可用率百分比
-- ——没有的数据绝不出现。每面保留最近 20 条历史，防台账无限增长。

CREATE TABLE IF NOT EXISTS service_status_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    surface TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_service_status_surface_time
    ON service_status_checks(surface, checked_at DESC);
