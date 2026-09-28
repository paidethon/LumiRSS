-- 0147 (NEW-218): 资料引用关系检查 —— 「保留失效标记」的用户决定。
-- 检查器跳过已登记 keep 的引用（不再反复报警），解除后恢复检查。
-- per-user 库 = 只可能是本人的笔记/集合/关联。

CREATE TABLE IF NOT EXISTS new218_stale_keeps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_name TEXT NOT NULL,
    locator TEXT NOT NULL,
    ref TEXT NOT NULL,
    marked_at TEXT NOT NULL,
    UNIQUE (domain_name, locator, ref)
);
