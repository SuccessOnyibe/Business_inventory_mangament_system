"""Sale corrections: extracted workflows; URLs and transactions are unchanged."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Query
from psycopg.errors import NumericValueOutOfRange
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from auth import get_current_user, require_stock_manager, scoped_branch
from credit_helpers import credit_totals
from database import db_connection
from receipt_helpers import CORRECTION_SELECT, correction_details, correction_response
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Sale Corrections'])


class CorrectionItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sale_id: int = Field(strict=True, gt=0, le=2147483647)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    restock: bool = Field(strict=True)


class SaleCorrectionCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    receipt_type: Literal['checkout', 'legacy']
    receipt_id: int = Field(strict=True, gt=0, le=2147483647)
    kind: Literal['void', 'return']
    reason: str = Field(min_length=1, max_length=1000)
    refund_method: Literal['cash', 'pos'] | None = None
    items: list[CorrectionItem] | None = Field(default=None, max_length=100)

    @field_validator('reason')
    @classmethod
    def require_reason(cls, value):
        if not value.strip():
            raise ValueError('A correction reason is required')
        return value.strip()

    @model_validator(mode='after')
    def validate_items(self):
        if self.kind == 'void' and self.items:
            raise ValueError('A void cancels the entire receipt; do not supply items')
        if self.kind == 'return' and not self.items:
            raise ValueError('Select at least one item to return')
        if self.items and len({item.sale_id for item in self.items}) != len(self.items):
            raise ValueError('Each sale item can appear once per return')
        return self


@router.post('/sale-corrections', status_code=201)
def create_sale_correction(request: SaleCorrectionCreate, idempotency_key: UUID = Header(),
                           user: dict = Depends(require_stock_manager)):
    payload = request.model_dump(mode='json')
    payload['items'] = sorted(payload['items'] or [], key=lambda item: item['sale_id'])
    with db_connection() as connection:
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    previous = begin_stock_request(cursor, idempotency_key, 'sale_correction', payload, user['id'])
                    if previous is not None:
                        return previous
                    checkout = request.receipt_type == 'checkout'
                    parent = 'sale_orders' if checkout else 'sales'
                    standalone = '' if checkout else ' AND order_id IS NULL'
                    cursor.execute(f'SELECT branch_id FROM {parent} WHERE id = %s{standalone};', (request.receipt_id,))
                    found = cursor.fetchone()
                    if found is None:
                        raise HTTPException(status_code=404, detail='Receipt not found')
                    branch_id = found[0]
                    # All stock/refund/snapshot writers lock the branch first.
                    cursor.execute('SELECT name FROM branches WHERE id = %s FOR UPDATE;', (branch_id,))
                    branch_name = cursor.fetchone()[0]
                    cursor.execute(f'SELECT payment_method, customer_name FROM {parent} WHERE id = %s FOR UPDATE;', (request.receipt_id,))
                    original_method, customer = cursor.fetchone()
                    refund_method = request.refund_method or (original_method if original_method != 'credit' else None)
                    if refund_method is None and original_method != 'credit':
                        raise HTTPException(status_code=422, detail='Original payment is unknown; choose the actual Cash/POS refund method')
                    cursor.execute(f'''SELECT id, product_id, quantity, unit_price, product_name, base_unit
                        FROM sales WHERE {'order_id' if checkout else 'id'} = %s ORDER BY id FOR UPDATE;''', (request.receipt_id,))
                    original = {row[0]: row for row in cursor.fetchall()}
                    cursor.execute('''SELECT sale_id, SUM(quantity) FROM sale_correction_items
                        WHERE sale_id = ANY(%s) GROUP BY sale_id;''', (list(original),))
                    returned = dict(cursor.fetchall())
                    if request.kind == 'void' and returned:
                        raise HTTPException(status_code=409, detail='Receipt already corrected; return remaining items instead')
                    selected = ([CorrectionItem(sale_id=row[0], quantity=row[2], restock=True) for row in original.values()]
                                if request.kind == 'void' else request.items)
                    for item in selected:
                        if item.sale_id not in original:
                            raise HTTPException(status_code=422, detail='Return item does not belong to this receipt')
                        if item.quantity > original[item.sale_id][2] - returned.get(item.sale_id, 0):
                            raise HTTPException(status_code=409, detail='Quantity exceeds the unreturned quantity')
                    total = sum((original[item.sale_id][3] * item.quantity for item in selected), Decimal('0'))
                    debt_reduction = Decimal('0')
                    if original_method == 'credit':
                        debt_reduction = min(total, Decimal(credit_totals(cursor, request.receipt_id)['outstanding']))
                    refund_amount = total - debt_reduction
                    if refund_amount > 0 and refund_method is None:
                        raise HTTPException(status_code=422, detail='Choose the actual Cash/POS refund method for the paid portion')
                    receipt_number = f"{'FAS-' if checkout else 'FAS-S-'}{request.receipt_id:08d}"
                    cursor.execute('''INSERT INTO sale_corrections (order_id, legacy_sale_id, branch_id,
                        branch_name, original_receipt_number, kind, reason, refund_method, refund_total,
                        created_by, approved_by_name, customer_name, debt_reduction)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            (SELECT username FROM users WHERE id = %s), %s, %s) RETURNING id;''',
                        (request.receipt_id if checkout else None, None if checkout else request.receipt_id,
                         branch_id, branch_name, receipt_number, request.kind, request.reason, refund_method,
                         refund_amount, user['id'], user['id'], customer, debt_reduction))
                    correction_id = cursor.fetchone()[0]
                    for item in sorted(selected, key=lambda item: original[item.sale_id][1]):
                        sale_id, product_id, _, price, name, unit = original[item.sale_id]
                        cursor.execute('''INSERT INTO sale_correction_items
                            (correction_id, sale_id, product_id, product_name, base_unit, quantity, unit_price, restock)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;''',
                            (correction_id, sale_id, product_id, name, unit, item. quantity, price, item.restock))
                        correction_item_id = cursor.fetchone()[0]
                        if item.restock:
                            cursor.execute('''INSERT INTO inventory (branch_id, product_id, quantity) VALUES (%s, %s, %s)
                                ON CONFLICT (branch_id, product_id)
                                DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity;''',
                                (branch_id, product_id, item.quantity))
                            # Damaged/non-resellable returns have no available-stock movement.
                            cursor.execute('''INSERT INTO stock_movements
                                (branch_id, product_id, quantity_change, movement_type, notes, correction_item_id)
                                VALUES (%s, %s, %s, %s, %s, %s);''', (branch_id, product_id, item.quantity,
                                'sale_void' if request.kind == 'void' else 'sale_return', request.reason, correction_item_id))
                    result = correction_details(cursor, correction_id)
                    finish_stock_request(cursor, idempotency_key, result)
        except NumericValueOutOfRange:
            raise HTTPException(status_code=409, detail='Restocking would exceed the inventory integer range') from None
    return result


@router.get('/sale-corrections')
def list_sale_corrections(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                          limit: int = Query(default=100, ge=1, le=500),
                          offset: int = Query(default=0, ge=0, le=2147483647),
                          user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {CORRECTION_SELECT} FROM sale_corrections
            WHERE (%s::integer IS NULL OR branch_id = %s) ORDER BY id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, limit, offset)).fetchall()
    return [correction_response(row) for row in rows]


@router.get('/sale-corrections/{correction_id}')
def get_sale_correction(correction_id: int = Path(gt=0, le=2147483647), user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT branch_id FROM sale_corrections WHERE id = %s;', (correction_id,))
            branch = cursor.fetchone()
            if branch is None:
                raise HTTPException(status_code=404, detail='Correction not found')
            scoped_branch(user, branch[0])
            return correction_details(cursor, correction_id)
