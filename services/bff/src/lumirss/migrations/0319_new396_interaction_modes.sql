-- 0319: NEW-396 新功能回退偏好 —— 明确可并存的新旧交互选择。
--
-- 每用户每交互面至多一条偏好；mode='new' 即回到新交互（无期限）；
-- mode='classic' 必带 expires_at（登记面给定的兼容期限，默认 90 天）
-- ——到期后读取侧一律按新交互生效并如实标注 expired，旧实现没有
-- 无限期保留。本表不发明新交互面：面注册表在模块内与真实读取路径
-- 一一对应。

CREATE TABLE IF NOT EXISTS interaction_mode_prefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    surface TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('new', 'classic')),
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_interaction_mode_unique
    ON interaction_mode_prefs(user_id, surface);
