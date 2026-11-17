"""Sales: extracted workflows; URLs and transactions are unchanged."""

from decimal import Decimal, ROUND_CEILING
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth import get_current_user, scoped_branch
from database import db_connection
from receipt_helpers import ORDER_COLUMNS, decorate_receipt, order_items, order_response, sale_response
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Sales'])


class SaleCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: int = Field(strict=True, gt=0, le=2147483647)
    product_id: int = Field(strict=True, gt=0, le=2147483647)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    payment_method: Literal['cash', 'pos']
    # Omit unit_price to use the catalogue price; send a lower price for a discount.
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    customer_name: str | None = Field(default=None, max_length=150)
    notes: str | None = None


class CheckoutItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    product_id: int = Field(strict=True, gt=0, le=2147483647)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)


class CheckoutCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: int = Field(strict=True, gt=0, le=2147483647)
    items: list[CheckoutItem] = Field(min_length=1, max_length=100)
    payment_method: Literal['cash', 'pos', 'credit']
    customer_id: int | None = Field(default=None, strict=True, gt=0, le=2147483647)
    customer_name: str | None = Field(default=None, max_length=150)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode='after')
    def distinct_products(self):
        if len({item.product_id for item in self.items}) != len(self.items):
            raise ValueError('Combine quantities for the same product into one item')
        if (self.payment_method == 'credit') != (self.customer_id is not None):
            raise ValueError('Choose a registered customer for credit sales only')
        return self


@router.post('/sales', status_code=201)
def create_sale(sale: SaleCreate, idempotency_key: UUID = Header(),
                user: dict = Depends(get_current_user)):
    scoped_branch(user, sale.branch_id)
    payload = sale.model_dump(mode='json')
    if sale.unit_price is not None:
        payload['unit_price'] = format(sale.unit_price, '.2f')
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'sale', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (sale.branch_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                # Hold the price and discount policy stable until the sale commits.
                cursor.execute(
                    'SELECT name, base_unit, is_active, selling_price, max_discount_percent FROM products WHERE id = %s FOR SHARE;',
                    (sale.product_id,)
                )
                product = cursor.fetchone()
                if product is None:
                    raise HTTPException(status_code=404, detail='Product not found')
                name, base_unit, active, list_price, discount_limit = product
                if not active or list_price is None:
                    raise HTTPException(status_code=409, detail='Product must be active and have a selling price')
                unit_price = list_price if sale.unit_price is None else sale.unit_price
                # Round the minimum UP to a kobo: rounding down could exceed the limit.
                minimum = (list_price * (Decimal('100') - discount_limit) / Decimal('100')).quantize(
                    Decimal('0.01'), rounding=ROUND_CEILING)
                if unit_price < minimum or unit_price > list_price:
                    raise HTTPException(status_code=422, detail='Unit price is outside the permitted discount range')
                cursor.execute(
                    '''UPDATE inventory SET quantity = quantity - %s
                       WHERE branch_id = %s AND product_id = %s AND quantity >= %s RETURNING quantity;''',
                    (sale.quantity, sale.branch_id, sale.product_id, sale.quantity)
                )
                stock = cursor.fetchone()
                if stock is None:
                    raise HTTPException(status_code=409, detail='Insufficient stock')
                # Snapshot prices and units so later catalogue edits cannot rewrite history.
                cursor.execute(
                    '''INSERT INTO sales (branch_id, product_id, quantity, unit_price, list_price,
                           max_discount_percent, product_name, base_unit, customer_name, notes, created_by, payment_method)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id, branch_id, product_id, quantity, unit_price, list_price,
                           max_discount_percent, total_amount, product_name, base_unit,
                           customer_name, notes, created_by, created_at, payment_method;''',
                    (sale.branch_id, sale.product_id, sale.quantity, unit_price, list_price,
                     discount_limit, name, base_unit, sale.customer_name, sale.notes, user['id'], sale.payment_method)
                )
                response = sale_response(cursor.fetchone())
                response['updated_quantity'] = stock[0]
                cursor.execute(
                    '''INSERT INTO stock_movements (branch_id, product_id, quantity_change, movement_type, notes, sale_id)
                       VALUES (%s, %s, %s, 'sale', %s, %s);''',
                    (sale.branch_id, sale.product_id, -sale.quantity, sale.notes, response['id'])
                )
                finish_stock_request(cursor, idempotency_key, response)
    return response


@router.get('/sales')
def list_sales(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
               limit: int = Query(default=100, ge=1, le=500),
               offset: int = Query(default=0, ge=0, le=2147483647),
               user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(
            '''SELECT id, branch_id, product_id, quantity, unit_price, list_price,
                      max_discount_percent, total_amount, product_name, base_unit,
                      customer_name, notes, created_by, created_at, payment_method FROM sales
               WHERE (%s::integer IS NULL OR branch_id = %s)
               ORDER BY id DESC LIMIT %s OFFSET %s;''', (branch_id, branch_id, limit, offset)
        ).fetchall()
    return [sale_response(row) for row in rows]


@router.post('/checkouts', status_code=201)
def create_checkout(checkout: CheckoutCreate, idempotency_key: UUID = Header(),
                    user: dict = Depends(get_current_user)):
    scoped_branch(user, checkout.branch_id)
    # Canonical product ordering also gives every transaction the same lock order.
    items = sorted(checkout.items, key=lambda item: item.product_id)
    payload = checkout.model_dump(mode='json')
    if checkout.customer_id is None:
        payload.pop('customer_id')  # Preserve pre-credit retry payloads.
    payload['items'] = [dict(product_id=item.product_id, quantity=item.quantity,
                           unit_price=format(item.unit_price, '.2f') if item.unit_price is not None else None)
                        for item in items]
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'checkout', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT name FROM branches WHERE id = %s FOR UPDATE;', (checkout.branch_id,))
                branch = cursor.fetchone()
                if branch is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                customer_name = checkout.customer_name
                if checkout.customer_id is not None:
                    cursor.execute('SELECT name, branch_id, is_active FROM customers WHERE id = %s FOR SHARE;', (checkout.customer_id,))
                    customer = cursor.fetchone()
                    if customer is None:
                        raise HTTPException(status_code=404, detail='Customer not found')
                    if customer[1] != checkout.branch_id or not customer[2]:
                        raise HTTPException(status_code=409, detail='Customer must be active in the sale branch')
                    customer_name = customer[0]
                prepared, total = [], Decimal('0')
                for item in items:
                    cursor.execute('''SELECT name, base_unit, is_active, selling_price, max_discount_percent
                        FROM products WHERE id = %s FOR SHARE;''', (item.product_id,))
                    product = cursor.fetchone()
                    if product is None:
                        raise HTTPException(status_code=404, detail=f'Product {item.product_id} not found')
                    name, unit, active, list_price, discount = product
                    if not active or list_price is None:
                        raise HTTPException(status_code=409, detail=f'Product {item.product_id} must be active and priced')
                    price = list_price if item.unit_price is None else item.unit_price
                    minimum = (list_price * (100 - discount) / 100).quantize(Decimal('0.01'), rounding=ROUND_CEILING)
                    if price < minimum or price > list_price:
                        raise HTTPException(status_code=422, detail=f'Product {item.product_id} price exceeds its permitted discount range')
                    prepared.append((item, name, unit, price, list_price, discount))
                    total += price * item.quantity
                # One header represents one customer purchase and one Cash/POS payment.
                cursor.execute(f'''INSERT INTO sale_orders (branch_id, branch_name, created_by, salesperson_name,
                    payment_method, total_amount, item_count, customer_name, notes, customer_id)
                    VALUES (%s, %s, %s, (SELECT username FROM users WHERE id = %s), %s, %s, %s, %s, %s, %s)
                    RETURNING {ORDER_COLUMNS};''', (checkout.branch_id, branch[0], user['id'], user['id'],
                    checkout.payment_method, total, len(items), customer_name, checkout.notes, checkout.customer_id))
                result = order_response(cursor.fetchone())
                balances = {}
                for item, name, unit, price, list_price, discount in prepared:
                    cursor.execute('''UPDATE inventory SET quantity = quantity - %s
                        WHERE branch_id = %s AND product_id = %s AND quantity >= %s RETURNING quantity;''',
                        (item.quantity, checkout.branch_id, item.product_id, item.quantity))
                    stock = cursor.fetchone()
                    if stock is None:
                        raise HTTPException(status_code=409, detail=f'Insufficient stock for product {item.product_id}')
                    balances[item.product_id] = stock[0]
                    # Reuse the existing, constrained sales rows as immutable receipt items.
                    # Any failure below rolls back the header and ALL earlier deductions too.
                    cursor.execute('''INSERT INTO sales (branch_id, product_id, quantity, unit_price, list_price,
                        max_discount_percent, product_name, base_unit, customer_name, notes, created_by,
                        payment_method, created_at, order_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;''',
                        (checkout.branch_id, item.product_id, item.quantity, price, list_price, discount,
                         name, unit, customer_name, checkout.notes, user['id'], checkout.payment_method,
                         result['created_at'], result['id']))
                    sale_id = cursor.fetchone()[0]
                    cursor.execute('''INSERT INTO stock_movements
                        (branch_id, product_id, quantity_change, movement_type, notes, sale_id)
                        VALUES (%s, %s, %s, 'sale', %s, %s);''',
                        (checkout.branch_id, item.product_id, -item.quantity, checkout.notes, sale_id))
                result['items'] = order_items(cursor, result['id'])
                for item in result['items']:
                    item['updated_quantity'] = balances[item['product_id']]
                decorate_receipt(cursor, result)
                finish_stock_request(cursor, idempotency_key, result)
    return result


@router.get('/checkouts')
def list_checkouts(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                   limit: int = Query(default=100, ge=1, le=500),
                   offset: int = Query(default=0, ge=0, le=2147483647),
                   user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        # Include earlier standalone sales, but never count new receipt items twice.
        rows = connection.execute('''SELECT id, branch_id, total_amount, item_count, description,
                   payment_method, customer_name, created_at, receipt_type FROM (
            SELECT id, branch_id, total_amount, item_count, item_count::text || ' item(s)' AS description,
                   payment_method, customer_name, created_at, 'checkout'::text AS receipt_type FROM sale_orders
            UNION ALL
            SELECT id, branch_id, total_amount, 1, product_name, payment_method, customer_name,
                   created_at, 'legacy'::text FROM sales WHERE order_id IS NULL
            ) purchases WHERE (%s::integer IS NULL OR branch_id = %s)
            ORDER BY created_at DESC, receipt_type, id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, limit, offset)).fetchall()
    result = []
    for row in rows:
        record = dict(zip(('id', 'branch_id', 'total_amount', 'item_count', 'description',
                           'payment_method', 'customer_name', 'created_at', 'receipt_type'), row))
        record['total_amount'] = format(record['total_amount'], '.2f')
        record['created_at'] = record['created_at'].isoformat()
        prefix = 'FAS-' if record['receipt_type'] == 'checkout' else 'FAS-S-'
        record['receipt_number'] = f"{prefix}{record['id']:08d}"
        result.append(record)
    return result


@router.get('/checkouts/{order_id}')
def get_checkout(order_id: int = Path(gt=0, le=2147483647), user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        with connection.cursor() as cursor:
            # Hold a coherent receipt/balance view while stock/refund/payment writers wait.
            cursor.execute('''SELECT b.id FROM branches b JOIN sale_orders o ON o.branch_id=b.id
                WHERE o.id=%s FOR SHARE OF b;''', (order_id,))
            cursor.execute(f'SELECT {ORDER_COLUMNS} FROM sale_orders WHERE id = %s;', (order_id,))
            row = cursor.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail='Receipt not found')
            result = order_response(row)
            scoped_branch(user, result['branch_id'])
            result['items'] = order_items(cursor, order_id)
            decorate_receipt(cursor, result)
    return result


@router.get('/sales/{sale_id}/receipt')
def legacy_sale_receipt(sale_id: int = Path(gt=0, le=2147483647), user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        row = connection.execute('''SELECT s.id, s.branch_id, s.product_id, s.quantity, s.unit_price, s.list_price,
            s.max_discount_percent, s.total_amount, s.product_name, s.base_unit, s.customer_name, s.notes,
            s.created_by, s.created_at, s.payment_method, b.name, u.username
            FROM sales s JOIN branches b ON b.id = s.branch_id JOIN users u ON u.id = s.created_by
            WHERE s.id = %s AND s.order_id IS NULL;''', (sale_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Standalone sale not found')
    sale = sale_response(row[:15])
    scoped_branch(user, sale['branch_id'])
    receipt = {**sale, 'receipt_number': f'FAS-S-{sale_id:08d}', 'receipt_type': 'legacy',
            'business_name': 'FESTY AGRIC SERVICES', 'branch_name': row[15], 'salesperson_name': row[16],
            'item_count': 1, 'items': [sale]}
    with db_connection() as connection:
        with connection.cursor() as cursor:
            return decorate_receipt(cursor, receipt)
