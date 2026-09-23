-- 0071 / N006: 通行密钥（WebAuthn passkeys）。
--
-- 表在控制库（与 users / auth_sessions 同库）：通行密钥是身份凭据，
-- 登录流程发生在会话建立之前，按用户隔离（user_id 必填）。
--
-- webauthn_credentials：只存验证所需材料——
--   id          = credential id 的 base64url（浏览器回传即此形态）；
--   public_key  = COSE 公钥（CBOR）的 base64url。私钥永远不出 authenticator，
--                 这里没有任何可复放的秘密；
--   sign_count  = 断言计数器（克隆检测：新计数必须严格大于已存计数，
--                 已存 >0 时）。计数恒为 0 的 passkey（部分平台 authenticator）
--                 不做计数检测，这是 WebAuthn 规范允许的诚实状态。
-- 响应面永远只回 id/label/created_at/last_used_at（无公钥本体）。
CREATE TABLE IF NOT EXISTS webauthn_credentials (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    public_key TEXT NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    last_used_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_webauthn_credentials_user
    ON webauthn_credentials(user_id);

-- webauthn_challenges：一次性挑战（register|login，TTL ~5 分钟）。
-- 消费即删除（原子 DELETE WHERE challenge = ? AND expires_at > now），
-- 重放天然失败；不存任何绑定之外的状态。
CREATE TABLE IF NOT EXISTS webauthn_challenges (
    challenge TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL CHECK (purpose IN ('register', 'login')),
    expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webauthn_challenges_expires
    ON webauthn_challenges(expires_at);
