-- 0219: NEW-293 邮件引用折叠 —— 阅读导入邮件时收起重复引用的前文，
-- 用户可逐段展开核对。
--
-- email_quote_reviews：用户对某条引用段的「已核对」标记（按
-- material_id + segment_index 定位；分段本身是纯计算，不落库——
-- 落库的只有用户的核对决定）。

CREATE TABLE IF NOT EXISTS email_quote_reviews (
    material_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    PRIMARY KEY (material_id, segment_index)
);
