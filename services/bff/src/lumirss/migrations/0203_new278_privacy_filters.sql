-- 0203: NEW-278 AI 输入隐私过滤 —— 用户显式勾选的排除字段。
--
-- 每行 = 一个被排除的输入字段（field ∈ new278_privacy_filters.FIELDS：
-- feedTitle / cachedSummary / userNote）。行存在 = 排除生效；无行 =
-- 不过滤。过滤只作用于显式勾选的字段——绝不声称自动识别正文或
-- 笔记中的秘密信息（诚实口径，见服务层 honestyNote）。
-- 正文（body）不在可排除词表内：AI 任务没有正文即无意义，预览会
-- 如实说明。

CREATE TABLE IF NOT EXISTS ai_privacy_exclusions (
    field TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL
);
