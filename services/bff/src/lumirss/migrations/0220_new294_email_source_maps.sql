-- 0220: NEW-294 通讯订阅来源映射 —— 用户把某发件地址映射为个人资料
-- 来源；之后同来源邮件自动归入该视图。
--
-- email_source_maps：from_addr（小写）唯一 → source_label；导入流水线
-- 命中即写 email_materials.source_label（0217 列），清单视图按
-- source 过滤即「该来源视图」。没有行 = 不归源（诚实默认）。

CREATE TABLE IF NOT EXISTS email_source_maps (
    from_addr TEXT PRIMARY KEY,
    source_label TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
