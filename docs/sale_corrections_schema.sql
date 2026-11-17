-- Apply after checkout_schema.sql. Original sales, receipt items, and stock stay intact.
BEGIN;
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check
    CHECK (operation IN ('stock_received', 'stock_transfer', 'sale', 'reconciliation', 'checkout', 'sale_correction'));
CREATE TABLE sale_corrections (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id INTEGER REFERENCES sale_orders(id),
    legacy_sale_id INTEGER REFERENCES sales(id),
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    branch_name VARCHAR(100) NOT NULL,
    original_receipt_number VARCHAR(40) NOT NULL,
    kind VARCHAR(10) NOT NULL CHECK (kind IN ('void', 'return')),
    reason VARCHAR(1000) NOT NULL CHECK (btrim(reason) <> ''),
    refund_method VARCHAR(10) NOT NULL CHECK (refund_method IN ('cash', 'pos')),
    refund_total NUMERIC(24,2) NOT NULL CHECK (refund_total >= 0),
    created_by INTEGER NOT NULL REFERENCES users(id),
    approved_by_name VARCHAR(50) NOT NULL,
    customer_name VARCHAR(150),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK ((order_id IS NOT NULL) <> (legacy_sale_id IS NOT NULL))
);
CREATE INDEX sale_corrections_order_idx ON sale_corrections(order_id);
CREATE INDEX sale_corrections_legacy_idx ON sale_corrections(legacy_sale_id);
CREATE INDEX sale_corrections_branch_date_idx ON sale_corrections(branch_id, created_at);
CREATE TABLE sale_correction_items (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    correction_id INTEGER NOT NULL REFERENCES sale_corrections(id),
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name VARCHAR(150) NOT NULL,
    base_unit VARCHAR(30) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    refund_amount NUMERIC(22,2) GENERATED ALWAYS AS (quantity::numeric * unit_price) STORED,
    restock BOOLEAN NOT NULL,
    UNIQUE (correction_id, sale_id)
);
CREATE INDEX sale_correction_items_sale_idx ON sale_correction_items(sale_id);
ALTER TABLE stock_movements ADD COLUMN correction_item_id INTEGER REFERENCES sale_correction_items(id);
CREATE UNIQUE INDEX stock_movements_correction_item_idx ON stock_movements(correction_item_id)
    WHERE correction_item_id IS NOT NULL;

-- A later-day refund may make that day's net collections negative.
ALTER TABLE daily_reconciliations DROP CONSTRAINT daily_reconciliations_expected_cash_check;
ALTER TABLE daily_reconciliations DROP CONSTRAINT daily_reconciliations_expected_pos_check;
ALTER TABLE daily_reconciliations DROP CONSTRAINT daily_reconciliations_actual_cash_check;
ALTER TABLE daily_reconciliations DROP CONSTRAINT daily_reconciliations_actual_pos_check;
ALTER TABLE daily_reconciliations ADD COLUMN gross_cash NUMERIC(30,2) NOT NULL DEFAULT 0;
ALTER TABLE daily_reconciliations ADD COLUMN gross_pos NUMERIC(30,2) NOT NULL DEFAULT 0;
ALTER TABLE daily_reconciliations ADD COLUMN refund_cash NUMERIC(30,2) NOT NULL DEFAULT 0 CHECK (refund_cash >= 0);
ALTER TABLE daily_reconciliations ADD COLUMN refund_pos NUMERIC(30,2) NOT NULL DEFAULT 0 CHECK (refund_pos >= 0);
ALTER TABLE daily_reconciliations ADD COLUMN refund_count BIGINT NOT NULL DEFAULT 0 CHECK (refund_count >= 0);
ALTER TABLE daily_reconciliations ADD COLUMN last_correction_id INTEGER;
-- Populate only new snapshot fields; original submitted/reviewed amounts do not change.
UPDATE daily_reconciliations SET gross_cash = expected_cash, gross_pos = expected_pos;
COMMIT;
