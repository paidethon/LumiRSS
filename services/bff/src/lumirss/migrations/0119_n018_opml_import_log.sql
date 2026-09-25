-- 0119: N018 OPML 树对照导入 —— 撤销台账（cap 5）。
--
-- 每次树对照 apply 记一行：新建的分类名 + 被移动的 feed（原分类 →
-- 新分类）。undo 按 id 读取一行执行反向操作（feed 移回原分类），
-- 每行至多撤销一次（undone_at 非 NULL 后拒绝）。表保持 ≤5 行：
-- 插入后删除最旧的旧行（有界台账，不是历史审计）。
CREATE TABLE opml_import_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  imported_at TEXT NOT NULL,
  created_category_labels TEXT NOT NULL,  -- JSON 数组：本次新建的分类 label
  moved_feeds TEXT NOT NULL,              -- JSON 数组：[{streamId, feedUrl, fromCategoryId, toCategoryId}]
  undone_at TEXT
);
