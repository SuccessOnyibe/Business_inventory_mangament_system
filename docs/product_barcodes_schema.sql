-- Apply after credit_schema.sql. Unknown codes stay NULL; existing stock is untouched.
BEGIN;
ALTER TABLE products ADD COLUMN barcode VARCHAR(64);
ALTER TABLE products ADD CONSTRAINT products_barcode_unique UNIQUE (barcode);
ALTER TABLE products ADD CONSTRAINT products_barcode_format
    CHECK (barcode IS NULL OR barcode ~ '^[!-~]{1,64}$');
COMMIT;
