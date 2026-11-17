-- Apply after reconciliation_schema.sql. Existing single-product sales stay intact.
BEGIN;
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check
    CHECK (operation IN ('stock_received', 'stock_transfer', 'sale', 'reconciliation', 'checkout'));
CREATE TABLE sale_orders (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    branch_id INTEGER NOT NULL REFERENCES branches(id),
    branch_name VARCHAR(100) NOT NULL,
    created_by INTEGER NOT NULL REFERENCES users(id),
    salesperson_name VARCHAR(50) NOT NULL,
    payment_method VARCHAR(10) NOT NULL CHECK (payment_method IN ('cash', 'pos')),
    total_amount NUMERIC(24,2) NOT NULL CHECK (total_amount >= 0),
    item_count INTEGER NOT NULL CHECK (item_count BETWEEN 1 AND 100),
    customer_name VARCHAR(150),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX sale_orders_branch_date_idx ON sale_orders(branch_id, created_at);
ALTER TABLE sales ADD COLUMN order_id INTEGER REFERENCES sale_orders(id);
CREATE UNIQUE INDEX sales_order_product_idx ON sales(order_id, product_id) WHERE order_id IS NOT NULL;
COMMIT;
