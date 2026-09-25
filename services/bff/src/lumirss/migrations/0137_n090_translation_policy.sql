-- 0137: N090 翻译隐私路由 —— per-source 翻译策略。
--
-- translation_policy：NULL = 默认（跟随全局翻译引擎设置）；
-- 'local_only' = 该来源正文只允许浏览器本机翻译（Translator API），
-- BFF 段落生成端点对该来源的服务端拒绝（403 local_only_policy，
-- F066 ai_disabled 同款服务端执行点判定，UI 隐藏不算数）。

ALTER TABLE source_overrides ADD COLUMN translation_policy TEXT;
