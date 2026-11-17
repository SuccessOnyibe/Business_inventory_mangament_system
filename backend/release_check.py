"""Read-only operational checks; no customer details or secrets are printed."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from database import get_connection


def inspect_release():
    errors, warnings = [], []
    with get_connection() as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        connection.execute("SET LOCAL statement_timeout='15s'")
        for table in ('customers','customer_changes','credit_repayments','cash_movements','sale_corrections'):
            if connection.execute('SELECT to_regclass(%s)', ('public.'+table,)).fetchone()[0] is None:
                errors.append('Missing schema table: '+table)
        if errors:
            return dict(errors=errors,warnings=warnings)
        if not connection.execute("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='products' AND column_name='barcode')").fetchone()[0]:
            return dict(errors=['Missing product barcode schema'],warnings=warnings)
        checks = [
            ('No active Admin account', "SELECT count(*)=0 FROM users WHERE is_active AND role='admin'"),
            ('Active salesperson without branch', "SELECT EXISTS(SELECT 1 FROM users WHERE is_active AND role='salesperson' AND branch_id IS NULL)"),
            ('Negative inventory', 'SELECT EXISTS(SELECT 1 FROM inventory WHERE quantity<0)'),
            ('Unvalidated database constraints', "SELECT EXISTS(SELECT 1 FROM pg_constraint WHERE connamespace='public'::regnamespace AND NOT convalidated)"),
            ('Credit ledger balance outside valid range', """SELECT EXISTS(SELECT 1 FROM sale_orders o
                WHERE payment_method='credit' AND (
                    total_amount - COALESCE((SELECT SUM(amount) FROM credit_repayments WHERE order_id=o.id),0)
                      - COALESCE((SELECT SUM(debt_reduction) FROM sale_corrections WHERE order_id=o.id),0)<0
                    OR COALESCE((SELECT SUM(amount) FROM credit_repayments WHERE order_id=o.id),0)
                      <COALESCE((SELECT SUM(refund_total) FROM sale_corrections WHERE order_id=o.id),0)))"""),
        ]
        for message, query in checks:
            if connection.execute(query).fetchone()[0]: errors.append(message)
        if connection.execute('SELECT EXISTS(SELECT 1 FROM products WHERE is_active AND selling_price IS NULL)').fetchone()[0]:
            warnings.append('Some active products need prices before selling')
        if connection.execute("SELECT EXISTS(SELECT 1 FROM stock_transfers WHERE status='in_transit')").fetchone()[0]:
            warnings.append('Transfers remain in transit; confirm physical deliveries during the walkthrough')
    return dict(errors=errors,warnings=warnings)


if __name__ == '__main__':
    try:
        result=inspect_release()
    except Exception as error:
        result=dict(errors=['Read-only check could not complete: '+type(error).__name__],warnings=[])
    result['checked_at']=datetime.now(ZoneInfo('Africa/Lagos')).isoformat()
    result['ready_for_local_use']=not result['errors']
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['ready_for_local_use'] else 1)
