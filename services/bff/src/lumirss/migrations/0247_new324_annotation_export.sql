-- 0247: NEW-324 阅读批注 Markdown 输出 —— 本人批注 → 带来源与稳定
-- 锚点的 Markdown 文件（用户自行保存入库）。
--
-- 导出内容是即时组装的响应体，Lumi 不代写任何文件（尤其绝不写 Vault）；
-- 本表只落导出台账（哪些文章、多少条批注、建议文件名），可追溯、
-- 可重导。per-user（批注本就在各自用户库）。

CREATE TABLE IF NOT EXISTS annotation_markdown_exports (
    id TEXT PRIMARY KEY,
    entry_refs_json TEXT NOT NULL DEFAULT '[]',
    entry_count INTEGER NOT NULL DEFAULT 0,
    annotation_count INTEGER NOT NULL DEFAULT 0,
    filename TEXT NOT NULL,
    created_at TEXT NOT NULL
);
