-- 0007: Persistent single-user session authentication.
--
-- The browser password is verified against auth_password.password_hash
-- (bcrypt); the plaintext password is never persisted anywhere. Sessions
-- are high-entropy random tokens issued as cookies; only the SHA-256 of
-- the raw token is stored, so a database leak cannot resurrect sessions.
-- Timestamps are epoch seconds for cheap sliding-renewal arithmetic.

CREATE TABLE IF NOT EXISTS auth_password (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    password_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    user_agent TEXT
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires
    ON auth_sessions(expires_at);
