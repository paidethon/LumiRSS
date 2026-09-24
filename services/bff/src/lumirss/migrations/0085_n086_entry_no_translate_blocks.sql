-- 0085: N086 不翻译片段标记。
--
-- entry_no_translate_blocks：按 (entry_ref, block_index) 的「不翻译」
-- 持久标记（source_overrides 式的每条目块级标注；不是段缓存行上的
-- 标志 —— 标记是用户意图，跨引擎/语言/源文变体共享）。generate 对
-- 标记块不再请求 provider：已有缓存译文照常展示；没有则诚实显示
-- 原文。每条目上限 200 块（存储有界）。

CREATE TABLE IF NOT EXISTS entry_no_translate_blocks (
    entry_ref TEXT NOT NULL,
    block_index INTEGER NOT NULL,
    marked_at TEXT NOT NULL,
    PRIMARY KEY (entry_ref, block_index)
);
