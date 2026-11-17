-- Apply after customers_schema.sql. No existing sale is converted to credit.
BEGIN;
ALTER TABLE stock_requests DROP CONSTRAINT stock_requests_operation_check;
ALTER TABLE stock_requests ADD CONSTRAINT stock_requests_operation_check CHECK (operation IN
 ('stock_received','stock_transfer','sale','reconciliation','checkout','sale_correction','discrepancy_event',
  'stock_adjustment','cash_request','cash_decision','customer_create','customer_update','credit_repayment','repayment_void'));
ALTER TABLE sale_orders DROP CONSTRAINT sale_orders_payment_method_check;
ALTER TABLE sale_orders ADD CONSTRAINT sale_orders_payment_method_check CHECK (payment_method IN ('cash','pos','credit'));
ALTER TABLE sales DROP CONSTRAINT sales_payment_method_check;
ALTER TABLE sales ADD CONSTRAINT sales_payment_method_check CHECK (payment_method IN ('cash','pos','credit'));
ALTER TABLE sale_orders ADD COLUMN customer_id INTEGER REFERENCES customers(id);
ALTER TABLE sale_orders ADD CONSTRAINT credit_customer_required CHECK (payment_method <> 'credit' OR customer_id IS NOT NULL);
ALTER TABLE customers ADD CONSTRAINT customers_id_branch_unique UNIQUE(id, branch_id);
ALTER TABLE sale_orders ADD CONSTRAINT credit_customer_branch_fk FOREIGN KEY(customer_id, branch_id) REFERENCES customers(id, branch_id);
ALTER TABLE sale_orders ADD CONSTRAINT sale_orders_id_branch_unique UNIQUE(id, branch_id);
ALTER TABLE sale_corrections ADD COLUMN debt_reduction NUMERIC(24,2) NOT NULL DEFAULT 0 CHECK (debt_reduction >= 0);
ALTER TABLE sale_corrections ALTER COLUMN refund_method DROP NOT NULL;
ALTER TABLE sale_corrections ADD CONSTRAINT cash_refund_method_required CHECK (refund_total = 0 OR refund_method IS NOT NULL);
CREATE TABLE credit_repayments (
 id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 order_id INTEGER NOT NULL REFERENCES sale_orders(id),
 branch_id INTEGER NOT NULL REFERENCES branches(id),
 amount NUMERIC(24,2) NOT NULL CHECK (amount <> 0),
 payment_method VARCHAR(10) NOT NULL CHECK (payment_method IN ('cash','pos')),
 notes VARCHAR(1000),
 reversal_of INTEGER UNIQUE REFERENCES credit_repayments(id),
 created_by INTEGER NOT NULL REFERENCES users(id),
 recorded_by_name VARCHAR(50) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CHECK ((amount > 0 AND reversal_of IS NULL) OR (amount < 0 AND reversal_of IS NOT NULL))
);
CREATE INDEX credit_repayments_order_idx ON credit_repayments(order_id);
ALTER TABLE credit_repayments ADD CONSTRAINT repayment_order_branch_fk FOREIGN KEY(order_id, branch_id) REFERENCES sale_orders(id, branch_id);
CREATE INDEX credit_repayments_date_idx ON credit_repayments(branch_id, created_at);
CREATE INDEX credit_orders_customer_idx ON sale_orders(customer_id) WHERE payment_method = 'credit';
ALTER TABLE daily_reconciliations ADD COLUMN repayment_count BIGINT NOT NULL DEFAULT 0;
ALTER TABLE daily_reconciliations ADD COLUMN last_repayment_id INTEGER;
COMMIT;
