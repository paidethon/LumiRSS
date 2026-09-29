-- 0187: NEW-265 翻译任务预算预估 —— 每人单行的估价参数。
--
-- 预估必须基于真实配置与字数（不伪造精确数字）：待翻文字量来自
-- 用户当前范围的实际块文本；费用单价是用户自己登记的估算参数
-- （价格单位 / 每千字符），未登记 → estimatedCost=null + 诚实说明，
-- 绝不臆造默认价。每用户库一行（id='budget' 单例）。

CREATE TABLE IF NOT EXISTS translation_budget_settings (
    id TEXT PRIMARY KEY CHECK (id = 'budget'),
    price_per_1k_chars REAL,
    currency TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
