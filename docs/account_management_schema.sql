-- Apply once after auth_schema.sql. Existing accounts/passwords remain unchanged.
BEGIN;
CREATE TABLE login_attempts (
    username VARCHAR(50) PRIMARY KEY,
    failures INTEGER NOT NULL DEFAULT 0 CHECK (failures >= 0),
    window_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_until TIMESTAMPTZ
);
COMMIT;
