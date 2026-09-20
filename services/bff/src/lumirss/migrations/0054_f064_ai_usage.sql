-- 0054: F064 AI 配额事前拦截 — 本地时区窗口调用计数。
--
-- window_key：窗口标识（"day:YYYY-MM-DD" / "month:YYYY-MM"，服务端
-- 本地时区）；window_start：窗口起点 ISO；calls：本窗口已发出的
-- AI 请求数（原子预占即计数：并发安全，失败不回退——保守诚实口径）。

CREATE TABLE ai_usage (
    window_key TEXT PRIMARY KEY,
    window_start TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0
);
