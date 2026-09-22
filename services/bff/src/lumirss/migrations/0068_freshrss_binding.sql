-- 0068: 每用户 FreshRSS 绑定（O154）。
--
-- 每个用户库最多一行（id=1）：该用户自己的 FreshRSS 地址与用户名。
-- API 密码不出现在 SQLite——按 AD-0018-6 写入该用户的 secrets.json
-- （freshrss_api_password 键，0600）。旧单用户 env 凭据在 owner 迁移
-- 时写入 owner 用户库，之后读路径一律以绑定为准，无 env 回退。
CREATE TABLE IF NOT EXISTS freshrss_binding (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    base_url TEXT NOT NULL,
    username TEXT NOT NULL,
    public_url TEXT NOT NULL DEFAULT '',
    bound_at INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'pool'
);
