-- 0186: NEW-260 研究分享脱敏预览。
--
-- research_share_confirmations：用户逐项确认后的「可带出清单」快照
-- （manifest JSON：允许带出的笔记/附件、成员名是否匿名化）。只存
-- 清单快照——本能力不产出任何真实分享包/导出文件（诚实边界：
-- 预览与确认都是核对工具，不是发布管道）。

CREATE TABLE IF NOT EXISTS research_share_confirmations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    manifest TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_share_confirmations
    ON research_share_confirmations (project_id, created_at DESC);
