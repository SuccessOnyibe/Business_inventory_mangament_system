-- Apply after sale_corrections_schema.sql. Existing financial/stock records stay intact.
BEGIN;
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check CHECK (operation IN
    ('stock_received', 'stock_transfer', 'sale', 'reconciliation', 'checkout', 'sale_correction',
     'discrepancy_event', 'stock_adjustment'));
CREATE TABLE discrepancy_events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reconciliation_id INTEGER NOT NULL REFERENCES daily_reconciliations(id),
    action VARCHAR(20) NOT NULL CHECK (action IN ('investigate', 'resolve', 'reopen')),
    explanation VARCHAR(2000) NOT NULL CHECK (btrim(explanation) <> ''),
    resolution_action VARCHAR(2000),
    responsible_user_id INTEGER NOT NULL REFERENCES users(id),
    responsible_name VARCHAR(50) NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_by_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((action = 'resolve' AND resolution_action IS NOT NULL AND btrim(resolution_action) <> '')
        OR (action <> 'resolve' AND resolution_action IS NULL))
);
CREATE INDEX discrepancy_events_record_idx ON discrepancy_events(reconciliation_id, id DESC);
CREATE TABLE stock_adjustments (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    branch_name VARCHAR(100) NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name VARCHAR(150) NOT NULL,
    base_unit VARCHAR(30) NOT NULL,
    mode VARCHAR(20) NOT NULL CHECK (mode IN ('physical_count', 'damage', 'expiry', 'correction')),
    quantity_before INTEGER NOT NULL CHECK (quantity_before >= 0),
    quantity_after INTEGER NOT NULL CHECK (quantity_after >= 0),
    quantity_change INTEGER GENERATED ALWAYS AS (quantity_after - quantity_before) STORED,
    reason VARCHAR(1000) NOT NULL CHECK (btrim(reason) <> ''),
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_by_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (mode = 'physical_count' OR quantity_after <> quantity_before),
    CHECK (mode NOT IN ('damage', 'expiry') OR quantity_after < quantity_before)
);
ALTER TABLE stock_movements ADD COLUMN stock_adjustment_id INTEGER REFERENCES stock_adjustments(id);
CREATE UNIQUE INDEX stock_movements_adjustment_idx ON stock_movements(stock_adjustment_id)
    WHERE stock_adjustment_id IS NOT NULL;
COMMIT;
