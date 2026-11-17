-- Apply after branch_transfers_schema.sql. Existing products start unpriced.
BEGIN;
ALTER TABLE products ADD COLUMN selling_price NUMERIC(12,2) CHECK (selling_price > 0);
ALTER TABLE products ADD COLUMN max_discount_percent NUMERIC(5,2) NOT NULL DEFAULT 0
    CHECK (max_discount_percent BETWEEN 0 AND 100);

-- Extend the request ledger without removing any existing keys or responses.
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check
    CHECK (operation IN ('stock_received', 'stock_transfer', 'sale'));

CREATE TABLE sales (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12,2) NOT NULL CHECK (unit_price >= 0),
    list_price NUMERIC(12,2) NOT NULL CHECK (list_price > 0),
    max_discount_percent NUMERIC(5,2) NOT NULL CHECK (max_discount_percent BETWEEN 0 AND 100),
    total_amount NUMERIC(22,2) GENERATED ALWAYS AS (quantity::numeric * unit_price) STORED,
    product_name VARCHAR(150) NOT NULL,
    base_unit VARCHAR(30) NOT NULL,
    customer_name VARCHAR(150),
    notes TEXT,
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (unit_price <= list_price),
    CHECK (unit_price * 100 >= list_price * (100 - max_discount_percent))
);
CREATE INDEX sales_branch_id_idx ON sales(branch_id, id DESC);
ALTER TABLE stock_movements ADD COLUMN sale_id INTEGER REFERENCES sales(id);
CREATE UNIQUE INDEX stock_movements_sale_idx ON stock_movements(sale_id) WHERE sale_id IS NOT NULL;
COMMIT;
