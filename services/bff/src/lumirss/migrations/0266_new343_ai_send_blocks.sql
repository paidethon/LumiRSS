-- 0266: NEW-343 敏感资料标记 —— 用户为个人文章设置的「不得发送至
-- 外部 AI」策略。命中标记的条目在 Lumi 的 AI 发送路径（摘要 / 对话 /
-- 翻译分段 / 对照）被后端阻止并说明原因。
--
-- 诚实边界：只阻止 Lumi 发起的 AI 任务；FreshRSS 侧或其他客户端
-- 直连 provider 的请求不经过 Lumi，无法阻止（API 响应随附说明）。

CREATE TABLE IF NOT EXISTS ai_send_blocks (
    entry_ref TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
