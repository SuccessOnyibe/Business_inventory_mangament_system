"""Create a fresh UI-test database on the disposable local PostgreSQL instance."""
import os
from pathlib import Path

from psycopg import sql

from auth import hash_password
from database import get_connection


def main():
    # Refuse the normal business server. This helper is for our isolated QA cluster.
    if os.getenv('DB_HOST') != '127.0.0.1' or os.getenv('DB_PORT') != '55439':
        raise RuntimeError('UI fixtures require the disposable server on 127.0.0.1:55439')
    name = os.environ['UI_TEST_DATABASE']
    if not name.startswith('inventory_ui_test_') or not name.removeprefix('inventory_ui_test_').isalnum():
        raise RuntimeError('Expected a uniquely named inventory_ui_test_ database')
    password = os.environ['UI_TEST_PASSWORD']
    with get_connection() as connection:
        connection.autocommit = True
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    os.environ['DB_NAME'] = name
    docs = Path(__file__).resolve().parents[2] / 'docs'
    with get_connection() as connection:
        connection.autocommit = True
        connection.execute('''
            CREATE TABLE branches (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name VARCHAR(100) NOT NULL, type VARCHAR(50) NOT NULL);
        ''')
        connection.execute((docs / 'products_schema.sql').read_text())
        connection.execute('''
            CREATE TABLE inventory (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                branch_id INTEGER NOT NULL REFERENCES branches(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
                CONSTRAINT unique_branch_product UNIQUE (branch_id, product_id));
            CREATE TABLE stock_movements (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                branch_id INTEGER NOT NULL REFERENCES branches(id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity_change INTEGER NOT NULL CHECK (quantity_change <> 0),
                movement_type VARCHAR(30) NOT NULL, notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
        ''')
        for migration in ('stock_requests_schema.sql', 'auth_schema.sql', 'account_management_schema.sql',
                          'branch_transfers_schema.sql', 'sales_pricing_schema.sql', 'sale_payments_schema.sql',
                          'reconciliation_schema.sql', 'checkout_schema.sql', 'sale_corrections_schema.sql',
                          'reports_adjustments_schema.sql', 'cash_movements_schema.sql', 'receipt_batches_schema.sql', 'customers_schema.sql', 'credit_schema.sql', 'product_barcodes_schema.sql'):
            connection.execute((docs / migration).read_text())
        connection.execute("INSERT INTO branches (name, type) VALUES ('Main Branch', 'General'), ('Branch 2', 'General')")
        connection.execute("INSERT INTO products (name, category, base_unit, selling_price, max_discount_percent) VALUES ('Chikun Starter Feed', 'Feed', 'bag', 25000, 5)")
        connection.execute('INSERT INTO inventory (branch_id, product_id, quantity) VALUES (1, 1, 1000)')
        for username, role, branch in (('ui_admin', 'admin', None), ('ui_seller', 'salesperson', 2)):
            connection.execute('INSERT INTO users (username, password_hash, role, branch_id) VALUES (%s, %s, %s, %s)',
                               (username, hash_password(password), role, branch))
    print('Fresh isolated UI fixture created; no business database was used.')


if __name__ == '__main__':
    main()
