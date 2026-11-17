-- Apply once after stock_requests_schema.sql. No existing stock rows change.
BEGIN;
CREATE TABLE users (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE
        CHECK (username ~ '^[a-z0-9][a-z0-9_.-]{2,49}$'),
    password_hash TEXT NOT NULL,
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'manager', 'salesperson')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE user_sessions (
    token_hash CHAR(64) PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX user_sessions_user_id_idx ON user_sessions(user_id);
-- Old keys stay reserved. Their NULL owner prevents leaking legacy saved responses.
ALTER TABLE stock_requests ADD COLUMN user_id INTEGER REFERENCES users(id);
COMMIT;
