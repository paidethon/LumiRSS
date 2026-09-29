-- 0228: NEW-302 API 分页试抓台 —— 用受限页数验证已配置接口的分页
-- 契约；每来源只保留最近一次试抓结果（诊断快照，不参与发布）。
--
-- pages 列是逐页摘要 JSON（页号/脱敏 URL 形状/条数/错误）；
-- duplicate_pages = 与更早页载荷完全相同的页数；gap_pages = 拉取
-- 失败（缺失）的页数。试抓永不自动无限抓取（应用层硬上限 5 页）。

CREATE TABLE IF NOT EXISTS api_pagination_probes (
    source_uuid TEXT PRIMARY KEY,
    probed_at TEXT NOT NULL,
    stop_reason TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    item_count INTEGER NOT NULL,
    duplicate_pages INTEGER NOT NULL DEFAULT 0,
    gap_pages INTEGER NOT NULL DEFAULT 0,
    pages TEXT NOT NULL
);
