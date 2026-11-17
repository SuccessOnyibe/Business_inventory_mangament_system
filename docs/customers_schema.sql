-- Apply after receipt_batches_schema.sql. No debt or payment entries are created.
BEGIN;
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check CHECK (operation IN
    ('stock_received','stock_transfer','sale','reconciliation','checkout','sale_correction',
     'discrepancy_event','stock_adjustment','cash_request','cash_decision','customer_create','customer_update'));
CREATE TABLE customers (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    name VARCHAR(150) NOT NULL CHECK (btrim(name) <> ''),
    phone VARCHAR(40),
    notes VARCHAR(1000),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by INTEGER NOT NULL REFERENCES users(id),
    updated_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX customers_branch_idx ON customers(branch_id, id DESC);
CREATE TABLE customer_changes (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    changed_by INTEGER NOT NULL REFERENCES users(id),
    changed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX customer_changes_customer_idx ON customer_changes(customer_id, id);
COMMIT;
