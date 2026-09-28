-- 0148: NEW-201 订阅接管向导 —— 旧实例导出 → 现有来源映射 → 应用台账。
--
-- 每行 = 一次「确认应用」的台账：批次标签 + 汇总（新建/跳过/移动/
-- 失败逐项计数）+ 逐项结果。预演本身零持久化（POST preview 只读）；
-- 台账用于回看「接管过什么、每项结果如何」。

CREATE TABLE IF NOT EXISTS new201_takeover_batches (
    id TEXT PRIMARY KEY,
    label TEXT,
    summary_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
