-- 0246: NEW-323 笔记增量同步审批 —— 预览差异 → 用户确认 → 更新镜像。
--
-- 审批台账：preview 阶段零写入（差异计划来自与 rescan 完全相同的
-- _plan() 计算，不动 obsidian_notes）；用户确认后 apply 才是唯一写
-- 镜像的路径。planned_json 存预览清单（新增/修改/删除，各类有界），
-- applied_report_json 存实际应用报告——两者不同步时如实并存（Vault
-- 在两次之间又变了），绝不假装预览即结果。
--
-- 新预览落库时旧 pending 行置 superseded（陈旧计划不再是可执行项）。

CREATE TABLE IF NOT EXISTS obsidian_sync_approvals (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'applied', 'superseded')
    ),
    planned_json TEXT NOT NULL DEFAULT '{}',
    applied_report_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    applied_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_obsidian_sync_approvals_created
    ON obsidian_sync_approvals (created_at DESC);
