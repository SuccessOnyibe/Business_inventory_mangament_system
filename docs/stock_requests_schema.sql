-- Additive migration: existing inventory and movement rows are not changed.
BEGIN;

CREATE TABLE stock_requests (
    request_id UUID PRIMARY KEY,
    operation VARCHAR(30) NOT NULL
        CHECK (operation IN ('stock_received', 'stock_transfer')),
    request_payload JSONB NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
    -- NULL only while the owning transaction is still processing the request.
    response JSONB CHECK (jsonb_typeof(response) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Requests are retained permanently for now. Deleting keys permits replaying stock.
COMMIT;
