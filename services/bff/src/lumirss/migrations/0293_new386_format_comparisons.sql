-- 0309: NEW-386 保存格式对照预览台账。
--
-- 同一批选中资料的 Markdown / HTML / 纯文本三格式逐字段损失对照
-- （lost = 渲染产物中该字段值完全不存在；changed = 存在但被格式
-- 转义/包裹；kept = 原样保留）。对照结果随台账如实落库供回看。

CREATE TABLE IF NOT EXISTS new386_format_comparisons (
    id TEXT PRIMARY KEY,
    item_ids_json TEXT NOT NULL DEFAULT '[]',
    results_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
