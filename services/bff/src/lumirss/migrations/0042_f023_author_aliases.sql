-- 0042: F023 跨来源作者聚合 —— 用户显式建立的作者别名（不同写法归一人）。
--
-- author 值相同天然同组（search_entries.author 精确值聚合）；本表只存
-- 「不同写法 → 同一人」的显式声明，绝不按大小写/同名自动合并。查询
-- 聚合时 alias 并入 canonical 计数；撤销别名 = 删除一行。

CREATE TABLE IF NOT EXISTS author_aliases (
    alias TEXT PRIMARY KEY,
    canonical TEXT NOT NULL,
    created_at TEXT NOT NULL
);
