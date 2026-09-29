-- 0189: NEW-262 译文人工修订层 —— 逐段「重新翻译前是否保留修订」
-- 的显式决定台账。
--
-- F062 已提供：修订保存（机器原稿 translated_text 原样保留）、修订
-- 历史（N085）、全量覆盖（overwrite_revisions）。NEW-262 补上：
--
-- - 逐段覆盖选择：用户可为单个已修订段显式选择「放弃本段修订并重
--   翻」，其余修订段原样保留；
-- - 本表只追加记录被放弃的决定：被放弃时刻的人工文本与它曾覆盖的
--   机器原稿同时留底（overwritten_text / superseded_machine_text），
--   任何覆盖都不销毁人工修改或机器原稿的历史。
--
-- 与 ai_translation_revision_history（F062 修订换代历史）互补：那张
-- 表记录「修订→修订」的换代，本表记录「修订→放弃重翻」的决定。

CREATE TABLE IF NOT EXISTS translation_revision_decisions (
    id TEXT PRIMARY KEY,
    entry_ref TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('discarded')),
    overwritten_text TEXT NOT NULL,
    superseded_machine_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_translation_revision_decisions_ref
    ON translation_revision_decisions (entry_ref, created_at DESC);
