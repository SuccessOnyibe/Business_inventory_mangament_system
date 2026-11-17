"""Credit helpers: extracted workflows; URLs and transactions are unchanged."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException


def credit_totals(cursor, order_id):
    cursor.execute('''SELECT total_amount,
        COALESCE((SELECT SUM(amount) FROM credit_repayments WHERE order_id = o.id), 0),
        COALESCE((SELECT SUM(debt_reduction) FROM sale_corrections WHERE order_id = o.id), 0),
        COALESCE((SELECT SUM(refund_total) FROM sale_corrections WHERE order_id = o.id), 0)
        FROM sale_orders o WHERE id = %s AND payment_method = 'credit';''', (order_id,))
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Credit sale not found')
    total, paid, reduced, refunded = row
    return {key:format(value, '.2f') for key,value in dict(repaid=paid, debt_reduced=reduced,
        outstanding=total-paid-reduced, net_collected=paid-refunded, credit_net_total=total-reduced-refunded).items()} | {
            'balance_as_of':datetime.now(ZoneInfo('Africa/Lagos')).isoformat()}
