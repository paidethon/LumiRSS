-- 0318: NEW-395 版本功能体验清单 —— 用户级「了解/暂不使用」标记。
--
-- 清单本体是 docs/release-notes.json（N198 只读加载器，随发布更新，
-- 按当前角色过滤 adminOnly）——本表只存每个成员对每个功能项的
-- 显式标记，绝不自建功能清单（防止清单漂移成虚构）。唯一约束
-- (user_id, feature_id)，重复标记 = 覆盖。

CREATE TABLE IF NOT EXISTS feature_experience_marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    feature_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('learned', 'later')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_marks_unique
    ON feature_experience_marks(user_id, feature_id);
