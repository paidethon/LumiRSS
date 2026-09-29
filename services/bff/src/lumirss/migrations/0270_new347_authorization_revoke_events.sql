-- 0270: NEW-347 单项授权撤销中心 —— 各凭据面的撤销动作留痕
-- （kind + ref + 时间）。凭据本体仍在各自主存储（本表不复制任何
-- 令牌材料；清单从各存储实时读取）。

CREATE TABLE IF NOT EXISTS authorization_revoke_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    ref TEXT NOT NULL,
    revoked_at TEXT NOT NULL
);
