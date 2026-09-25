-- 0098: N111 目标卡扩展 + N112 材料状态扩展（每库一次）。
--
-- N111 目标卡扩展：workspace_goals 增加自由文本目标陈述（goal_text）与
-- 完成条件清单（conditions_json = 字符串数组 JSON，与 N101 组顺序/
-- F083 模板 config 同构的 JSON 列方案）。数值目标（target_count）原样
-- 保留——两者并存：数字驱动进度条，文本/条件驱动「为什么而读」。
-- 完成条件的勾选状态是设备本机呈现态（Web localStorage），服务端只存
-- 条目文本本身，绝不存勾选状态。
--
-- N112 材料状态扩展：workspace_item_status.status 枚举从
-- todo/reading/done 扩展为 + excerpted（待摘录）/ needs_verification
--（待验证）。SQLite 的列级 CHECK 无法 ALTER，沿用 0018 mail_seen 的
-- 前向重建法（建新表 → 拷贝 → 换名 → 重建索引）；行数据（workspace_id,
-- item_ref, status, updated_at）1:1 迁移，绝不丢既有状态。看板状态是
-- Lumi 自有元数据，本迁移不触碰 FreshRSS 任何数据。

-- N111 --------------------------------------------------------------------

ALTER TABLE workspace_goals ADD COLUMN goal_text TEXT;

ALTER TABLE workspace_goals ADD COLUMN conditions_json TEXT;

-- N112 --------------------------------------------------------------------
-- 新表携带扩展后的 CHECK；旧表更名后删除（无其他表引用
-- workspace_item_status，FK 只指向 workspaces，重建安全）。

CREATE TABLE workspace_item_status_n112 (
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    item_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('todo', 'reading', 'done', 'excerpted', 'needs_verification')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, item_ref)
);

INSERT INTO workspace_item_status_n112 (workspace_id, item_ref, status, updated_at)
  SELECT workspace_id, item_ref, status, updated_at FROM workspace_item_status;

DROP TABLE workspace_item_status;

ALTER TABLE workspace_item_status_n112 RENAME TO workspace_item_status;

CREATE INDEX idx_workspace_item_status_status
    ON workspace_item_status (workspace_id, status);
