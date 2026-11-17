-- Apply after sale_payments_schema.sql. Existing sales/stock are not changed.
BEGIN;
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check
    CHECK (operation IN ('stock_received', 'stock_transfer', 'sale', 'reconciliation'));

CREATE TABLE daily_reconciliations (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    business_date DATE NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    expected_cash NUMERIC(30,2) NOT NULL CHECK (expected_cash >= 0),
    expected_pos NUMERIC(30,2) NOT NULL CHECK (expected_pos >= 0),
    actual_cash NUMERIC(30,2) NOT NULL CHECK (actual_cash >= 0),
    actual_pos NUMERIC(30,2) NOT NULL CHECK (actual_pos >= 0),
    cash_difference NUMERIC(30,2) GENERATED ALWAYS AS (actual_cash - expected_cash) STORED,
    pos_difference NUMERIC(30,2) GENERATED ALWAYS AS (actual_pos - expected_pos) STORED,
    sales_count BIGINT NOT NULL CHECK (sales_count >= 0),
    last_sale_id INTEGER,
    notes TEXT,
    submitted_by INTEGER NOT NULL REFERENCES users(id),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    reviewed_by INTEGER REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    review_notes TEXT,
    UNIQUE (branch_id, business_date, revision),
    CHECK ((reviewed_by IS NULL AND reviewed_at IS NULL AND review_notes IS NULL)
        OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);
COMMIT;
