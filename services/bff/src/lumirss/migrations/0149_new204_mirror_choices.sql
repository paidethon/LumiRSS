-- 0149: NEW-204 订阅镜像比对 —— 用户在两个候选 feed 间的抉择台账。
--
-- 每行 = 一次「确认选用」：两个候选 URL + 用户选了哪边 + 可选理由。
-- 比对本身（POST compare）是只读探测（零持久化）；台账只记决定，
-- 供回看「当时为什么选了这边」。订阅动作仍走既有
-- POST /api/v1/subscriptions（本模块不代订）。

CREATE TABLE IF NOT EXISTS new204_mirror_choices (
    id TEXT PRIMARY KEY,
    url_a TEXT NOT NULL,
    url_b TEXT NOT NULL,
    picked_side TEXT NOT NULL CHECK (picked_side IN ('A', 'B')),
    picked_url TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
