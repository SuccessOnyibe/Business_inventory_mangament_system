"""Receipt helpers: extracted workflows; URLs and transactions are unchanged."""

from decimal import Decimal

from credit_helpers import credit_totals


def sale_response(row):
    keys = ('id', 'branch_id', 'product_id', 'quantity', 'unit_price', 'list_price',
            'max_discount_percent', 'total_amount', 'product_name', 'base_unit',
            'customer_name', 'notes', 'created_by', 'created_at', 'payment_method')
    result = dict(zip(keys, row))
    for field in ('unit_price', 'list_price', 'max_discount_percent', 'total_amount'):
        result[field] = format(result[field], '.2f')
    result['created_at'] = result['created_at'].isoformat()
    result['currency'] = 'NGN'
    return result


ORDER_COLUMNS = 'id, branch_id, branch_name, created_by, salesperson_name, payment_method, total_amount, item_count, customer_name, notes, created_at, customer_id'


def order_response(row):
    keys = ('id', 'branch_id', 'branch_name', 'created_by', 'salesperson_name', 'payment_method',
            'total_amount', 'item_count', 'customer_name', 'notes', 'created_at', 'customer_id')
    result = dict(zip(keys, row))
    result['total_amount'] = format(result['total_amount'], '.2f')
    result['created_at'] = result['created_at'].isoformat()
    result.update(receipt_number=f"FAS-{result['id']:08d}", receipt_type='checkout', currency='NGN',
                  business_name='FESTY AGRIC SERVICES')
    return result


def order_items(cursor, order_id):
    cursor.execute('''SELECT id, product_id, product_name, base_unit, quantity, unit_price,
        list_price, max_discount_percent, total_amount FROM sales WHERE order_id = %s ORDER BY id;''', (order_id,))
    result = []
    for row in cursor.fetchall():
        item = dict(zip(('id', 'product_id', 'product_name', 'base_unit', 'quantity', 'unit_price',
                         'list_price', 'max_discount_percent', 'total_amount'), row))
        for key in ('unit_price', 'list_price', 'max_discount_percent', 'total_amount'):
            item[key] = format(item[key], '.2f')
        result.append(item)
    return result


CORRECTION_COLUMNS = ('id', 'order_id', 'legacy_sale_id', 'branch_id', 'branch_name',
    'original_receipt_number', 'kind', 'reason', 'refund_method', 'refund_total',
    'created_by', 'approved_by_name', 'customer_name', 'created_at', 'debt_reduction')


CORRECTION_SELECT = ', '.join(CORRECTION_COLUMNS)


def correction_response(row):
    record = dict(zip(CORRECTION_COLUMNS, row))
    record['refund_total'] = format(record['refund_total'], '.2f')
    record['debt_reduction'] = format(record['debt_reduction'], '.2f')
    record['corrected_total'] = format(Decimal(record['refund_total']) + Decimal(record['debt_reduction']), '.2f')
    record['created_at'] = record['created_at'].isoformat()
    record.update(receipt_number=f"FAS-C-{record['id']:08d}", receipt_type='correction',
                  business_name='FESTY AGRIC SERVICES', currency='NGN')
    return record


def correction_details(cursor, correction_id):
    cursor.execute(f'SELECT {CORRECTION_SELECT} FROM sale_corrections WHERE id = %s;', (correction_id,))
    record = correction_response(cursor.fetchone())
    cursor.execute('''SELECT id, sale_id, product_id, product_name, base_unit, quantity, unit_price,
        refund_amount, restock FROM sale_correction_items WHERE correction_id = %s ORDER BY id;''', (correction_id,))
    record['items'] = []
    for row in cursor.fetchall():
        item = dict(zip(('id', 'sale_id', 'product_id', 'product_name', 'base_unit', 'quantity',
                         'unit_price', 'total_amount', 'restock'), row))
        item['unit_price'] = format(item['unit_price'], '.2f')
        item['total_amount'] = format(item['total_amount'], '.2f')
        record['items'].append(item)
    return record


def decorate_receipt(cursor, receipt):
    """Annotate, never rewrite, original receipt quantities/prices and timestamps."""
    target = 'order_id' if receipt['receipt_type'] == 'checkout' else 'legacy_sale_id'
    cursor.execute(f'SELECT {CORRECTION_SELECT} FROM sale_corrections WHERE {target} = %s ORDER BY id;', (receipt['id'],))
    corrections = [correction_response(row) for row in cursor.fetchall()]
    cursor.execute('''SELECT sale_id, SUM(quantity) FROM sale_correction_items
        WHERE sale_id = ANY(%s) GROUP BY sale_id;''', ([item['id'] for item in receipt['items']],))
    returned = dict(cursor.fetchall())
    for item in receipt['items']:
        item['returned_quantity'] = int(returned.get(item['id'], 0))
        item['remaining_quantity'] = item['quantity'] - item['returned_quantity']
    refund = sum((Decimal(record['corrected_total']) for record in corrections), Decimal('0'))
    receipt.update(corrections=corrections, corrected_total=format(refund, '.2f'),
                   refunded_total=format(sum((Decimal(c['refund_total']) for c in corrections), Decimal('0')), '.2f'),
                   net_total=format(Decimal(receipt['total_amount']) - refund, '.2f'))
    receipt['status'] = ('voided' if any(record['kind'] == 'void' for record in corrections) else
        'returned' if all(item['remaining_quantity'] == 0 for item in receipt['items']) else
        'partially_returned' if corrections else 'completed')
    if receipt.get('payment_method') == 'credit':
        receipt.update(credit_totals(cursor, receipt['id']))
    return receipt
