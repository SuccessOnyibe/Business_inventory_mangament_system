-- Apply after sales_pricing_schema.sql. Historical payment methods stay unknown.
BEGIN;
ALTER TABLE sales ADD COLUMN payment_method VARCHAR(10)
    CHECK (payment_method IN ('cash', 'pos'));
COMMIT;
