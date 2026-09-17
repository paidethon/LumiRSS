-- 0033: F23 列表标题按需翻译 —— 显式请求的单条标题译文缓存。
--
-- 缓存身份 = (title_hash, language, model, prompt_version)：标题内容、
-- 目标语言与模型参与身份（内容/设置变化自然失效）。只存标题与译文，
-- 不复制正文；只由显式单条请求写入（不会滚动一次就全库收费）。

CREATE TABLE IF NOT EXISTS title_translations (
    title_hash TEXT NOT NULL,
    language TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    original_title TEXT NOT NULL,
    translated_title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (title_hash, language, model, prompt_version)
);
