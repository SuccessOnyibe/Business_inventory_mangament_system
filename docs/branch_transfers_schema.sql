-- Apply after account_management_schema.sql. Historical movements remain unchanged.
BEGIN;
ALTER TABLE users ADD COLUMN branch_id INTEGER REFERENCES branches(id);

CREATE TABLE stock_transfers (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_branch_id INTEGER NOT NULL REFERENCES branches(id),
    destination_branch_id INTEGER NOT NULL REFERENCES branches(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'in_transit' CHECK (status IN ('in_transit', 'received')),
    notes TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id),
    confirmed_by INTEGER REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    received_at TIMESTAMPTZ,
    destination_quantity INTEGER CHECK (destination_quantity >= 0),
    CHECK (source_branch_id <> destination_branch_id),
    CHECK ((status = 'in_transit' AND confirmed_by IS NULL AND received_at IS NULL AND destination_quantity IS NULL)
        OR (status = 'received' AND confirmed_by IS NOT NULL AND received_at IS NOT NULL AND destination_quantity IS NOT NULL))
);
CREATE INDEX stock_transfers_destination_idx ON stock_transfers(destination_branch_id, id DESC);
-- Link dispatch and receipt movements to one transfer without rewriting history.
ALTER TABLE stock_movements ADD COLUMN transfer_id INTEGER REFERENCES stock_transfers(id);
CREATE UNIQUE INDEX stock_movements_transfer_type_idx
    ON stock_movements(transfer_id, movement_type) WHERE transfer_id IS NOT NULL;
COMMIT;
