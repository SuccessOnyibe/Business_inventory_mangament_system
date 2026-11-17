-- Phase 1: immutable delivery labels, not current per-batch stock balances.
-- Apply after cash_movements_schema.sql. Existing rows remain unknown/null.
BEGIN;
ALTER TABLE stock_movements ADD COLUMN batch_number VARCHAR(100);
ALTER TABLE stock_movements ADD COLUMN expires_on DATE;
ALTER TABLE stock_movements ADD COLUMN received_by INTEGER REFERENCES users(id);
ALTER TABLE stock_movements ADD COLUMN received_by_name VARCHAR(50);
ALTER TABLE stock_movements ADD CONSTRAINT receipt_batch_nonblank
    CHECK (batch_number IS NULL OR btrim(batch_number) <> '');
ALTER TABLE stock_movements ADD CONSTRAINT receipt_labels_only
    CHECK (movement_type = 'stock_received' OR
        (batch_number IS NULL AND expires_on IS NULL AND received_by IS NULL AND received_by_name IS NULL));
CREATE INDEX stock_receipt_history_idx ON stock_movements(branch_id, id DESC)
    WHERE movement_type = 'stock_received';
COMMIT;
