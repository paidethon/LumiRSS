-- 0037: F005 来源备注与维护记录 —— Lumi 自有元数据（非 RSS 域数据）。
--
-- 三字段均为自由文本（存原文，渲染转义由 Web 层承担）：
--   note            备注
--   reason          订阅理由
--   maintenance_log 维护记录
-- 级联语义（应用层执行，SQLite 无 FK 到上游）：来源被取消订阅时
-- （DELETE /api/v1/subscriptions/{ref}）同步删除本表对应行，无孤儿。

CREATE TABLE IF NOT EXISTS source_notes (
    subscription_ref TEXT PRIMARY KEY,
    note TEXT,
    reason TEXT,
    maintenance_log TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
