-- 0144 (NEW-214): 标签同义词字典 —— 为个人标签登记别名。
-- canonical 存规范标签名（改名时由 NEW-212 的同步逻辑改写指向）；
-- alias 全库唯一（NOCASE），同一别名绝不指向两个规范标签。
-- 本表只影响「录入/搜索提示」，绝不改写文章原文。per-user 库。

CREATE TABLE IF NOT EXISTS new214_tag_synonyms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alias TEXT NOT NULL,
    canonical TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (alias COLLATE NOCASE)
);

CREATE INDEX IF NOT EXISTS idx_new214_synonyms_canonical
  ON new214_tag_synonyms (canonical);
