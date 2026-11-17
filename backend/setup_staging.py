"""Initialize an EMPTY Neon staging database with sample data, never local records."""
import getpass
from pathlib import Path
import re

import psycopg
from psycopg.conninfo import conninfo_to_dict

from auth import hash_password
from create_user import NewUser

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = (
    'stock_requests_schema.sql', 'auth_schema.sql', 'account_management_schema.sql',
    'branch_transfers_schema.sql', 'sales_pricing_schema.sql', 'sale_payments_schema.sql',
    'reconciliation_schema.sql', 'checkout_schema.sql', 'sale_corrections_schema.sql',
    'reports_adjustments_schema.sql', 'cash_movements_schema.sql',
    'receipt_batches_schema.sql', 'customers_schema.sql', 'credit_schema.sql',
    'product_barcodes_schema.sql',
)


def staging_target(connection_string):
    """Reject local/production targets before opening a connection."""
    settings = conninfo_to_dict(connection_string)
    host = settings.get('host', '')
    if (not host.endswith('.neon.tech') or ',' in host or settings.get('hostaddr')
            or settings.get('service') or settings.get('dbname') != 'festy_staging'
            or settings.get('sslmode') not in ('require', 'verify-ca', 'verify-full')):
        raise ValueError('Use a Neon connection for festy_staging with SSL enabled.')
    if '-pooler.' in host:
        raise ValueError('Turn off connection pooling for initial schema setup.')
    return settings


def initialize_staging(connection, admin):
    """Schema, sample rows and the private Admin account commit together."""
    with connection.transaction():
        connection.execute('SELECT pg_advisory_xact_lock(768920113)')
        occupied = connection.execute("""SELECT EXISTS (
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'
              AND c.relkind IN ('r','p','v','m','S','f'))""").fetchone()[0]
        if occupied:
            raise ValueError('Database is not empty. Nothing was changed.')
        connection.execute((ROOT / 'docs/products_schema.sql').read_text())
        connection.execute((ROOT / 'deployment/base_schema.sql').read_text())
        for filename in MIGRATIONS:
            script = (ROOT / 'docs' / filename).read_text()
            # The outer transaction owns commit/rollback for the entire setup.
            script = re.sub(r'^\s*(?:BEGIN|COMMIT);\s*$', '', script, flags=re.MULTILINE)
            connection.execute(script)
        for name in ('Main Branch', 'Branch 2 - Wharehouse', 'Branch 3 - Odeh'):
            connection.execute('INSERT INTO branches (name, type) VALUES (%s, %s)',
                               (name, 'General'))
        user_id = connection.execute("""INSERT INTO users (username, password_hash, role)
            VALUES (%s, %s, 'admin') RETURNING id""",
            (admin.username, hash_password(admin.password.get_secret_value()))).fetchone()[0]
        # Clearly labelled sample items; no customer, price or stock data is copied.
        for name, category, unit in (
                ('SAMPLE - Feed', 'Feed', 'bag'),
                ('SAMPLE - Veterinary item', 'Medicine', 'vial'),
                ('SAMPLE - Poultry equipment', 'Equipment', 'piece')):
            product_id = connection.execute("""INSERT INTO products
                (name, category, base_unit, selling_price) VALUES (%s,%s,%s,100)
                RETURNING id""", (name, category, unit)).fetchone()[0]
            connection.execute('INSERT INTO inventory (branch_id,product_id,quantity) VALUES (1,%s,10)',
                               (product_id,))
            connection.execute("""INSERT INTO stock_movements
                (branch_id,product_id,quantity_change,movement_type,notes,received_by,received_by_name)
                VALUES (1,%s,10,'stock_received','STAGING SAMPLE ONLY',%s,%s)""",
                (product_id, user_id, admin.username))


def main():
    print('Sample-data setup for an empty Neon database named festy_staging.')
    # Secret input avoids shell history, command arguments and source files.
    connection_string = getpass.getpass('Neon DIRECT connection string (hidden): ')
    try:
        settings = staging_target(connection_string)
        username = input('Staging Admin username: ').strip()
        password = getpass.getpass('Choose an Admin password (12-128 characters): ')
        if password != getpass.getpass('Confirm password: '):
            raise ValueError('Passwords do not match.')
        admin = NewUser(username=username, password=password)
        with psycopg.connect(**settings, connect_timeout=15) as connection:
            initialize_staging(connection, admin)
    except Exception:
        # Driver/validation messages can contain the URL or password; do not echo them.
        print('Setup failed. Check the staging target, empty database, username and password. No partial setup was saved.')
        return 1
    print('Staging database ready with sample products and your Admin account.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
