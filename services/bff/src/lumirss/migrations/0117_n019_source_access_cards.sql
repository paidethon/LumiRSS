-- 0117: N019 来源接入说明卡 —— per-feed 结构化接入元数据。
--
-- 与 F005 source_notes（自由文本）互补：接入说明卡是**结构化字段**，
-- 供来源设置对话框渲染成卡片。故意没有 secret/credential value 列：
-- 凭据归属只存「归属标签」（self/shared/none），凭据值本身属于
-- RSSHub 凭据库（secrets_store，write-only）等既有安全边界，绝不
-- 进入本表。per-user 库隔离保证用户只看到自己的卡。
CREATE TABLE source_access_cards (
  feed_url TEXT PRIMARY KEY,
  fields_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
