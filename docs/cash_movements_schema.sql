-- Apply after reports_adjustments_schema.sql. Pending requests do not post money.
BEGIN;
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check CHECK (operation IN
    ('stock_received', 'stock_transfer', 'sale', 'reconciliation', 'checkout', 'sale_correction',
     'discrepancy_event', 'stock_adjustment', 'cash_request', 'cash_decision'));
CREATE TABLE cash_movement_requests (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    branch_name VARCHAR(100) NOT NULL,
    kind VARCHAR(30) NOT NULL CHECK (kind IN ('opening_float', 'cash_added', 'shortage_recovery', 'expense', 'bank_deposit', 'drawer_withdrawal')),
    amount NUMERIC(24,2) NOT NULL CHECK (amount > 0),
    reason VARCHAR(1000) NOT NULL CHECK (btrim(reason) <> ''),
    reference_reconciliation_id INTEGER REFERENCES daily_reconciliations(id),
    requested_by INTEGER NOT NULL REFERENCES users(id),
    requested_by_name VARCHAR(50) NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    status VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_by INTEGER REFERENCES users(id),
    decided_by_name VARCHAR(50),
    decision_note VARCHAR(1000),
    decided_at TIMESTAMPTZ,
    CHECK ((kind = 'shortage_recovery') = (reference_reconciliation_id IS NOT NULL)),
    CHECK ((status = 'pending' AND decided_by IS NULL AND decided_by_name IS NULL AND decided_at IS NULL AND decision_note IS NULL)
        OR (status <> 'pending' AND decided_by IS NOT NULL AND decided_by_name IS NOT NULL AND decided_at IS NOT NULL)),
    CHECK (status <> 'rejected' OR (decision_note IS NOT NULL AND btrim(decision_note) <> ''))
);
CREATE INDEX cash_requests_branch_idx ON cash_movement_requests(branch_id, id DESC);
CREATE TABLE cash_movements (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id INTEGER NOT NULL UNIQUE REFERENCES cash_movement_requests(id),
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    kind VARCHAR(30) NOT NULL CHECK (kind IN ('opening_float', 'cash_added', 'shortage_recovery', 'expense', 'bank_deposit', 'drawer_withdrawal')),
    amount NUMERIC(24,2) NOT NULL CHECK (amount > 0),
    cash_in NUMERIC(24,2) GENERATED ALWAYS AS (CASE WHEN kind IN ('opening_float', 'cash_added', 'shortage_recovery') THEN amount ELSE 0 END) STORED,
    cash_out NUMERIC(24,2) GENERATED ALWAYS AS (CASE WHEN kind IN ('expense', 'bank_deposit', 'drawer_withdrawal') THEN amount ELSE 0 END) STORED,
    expected_cash_effect NUMERIC(24,2) NOT NULL,
    business_date DATE NOT NULL,
    posted_at TIMESTAMPTZ NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_by_name VARCHAR(50) NOT NULL,
    CHECK (business_date = (posted_at AT TIME ZONE 'Africa/Lagos')::date),
    CHECK ((kind IN ('expense','bank_deposit','drawer_withdrawal') AND expected_cash_effect = -amount)
        OR (kind IN ('opening_float','cash_added') AND expected_cash_effect = amount)
        OR (kind = 'shortage_recovery' AND expected_cash_effect IN (0, amount)))
);
CREATE UNIQUE INDEX cash_opening_float_day_idx ON cash_movements(branch_id, business_date) WHERE kind = 'opening_float';
CREATE INDEX cash_movements_branch_date_idx ON cash_movements(branch_id, business_date);
ALTER TABLE daily_reconciliations ADD COLUMN cash_in NUMERIC(30,2) NOT NULL DEFAULT 0;
ALTER TABLE daily_reconciliations ADD COLUMN cash_out NUMERIC(30,2) NOT NULL DEFAULT 0;
ALTER TABLE daily_reconciliations ADD COLUMN cash_movement_effect NUMERIC(30,2) NOT NULL DEFAULT 0;
ALTER TABLE daily_reconciliations ADD COLUMN movement_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE daily_reconciliations ADD COLUMN last_movement_id INTEGER;
COMMIT;
