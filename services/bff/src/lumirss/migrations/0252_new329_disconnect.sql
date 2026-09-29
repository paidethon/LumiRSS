-- 0252: NEW-329 本地资料断开连接 —— 撤销根授权后停止扫描，并由用户
-- 明确选择副本去留。
--
-- copies_policy：''（未决定，默认——断开后副本原样保留、只读可见）、
-- 'kept'（用户显式选择保留导入副本）、'deleted'（用户显式选择删除
-- 本应用副本，obsidian_root_notes 已清空）。三种状态都绝不触碰源目录。

ALTER TABLE obsidian_root_profiles
    ADD COLUMN copies_policy TEXT NOT NULL DEFAULT '';
