"""Stock adjustments: extracted workflows; URLs and transactions are unchanged."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from auth import get_current_user, require_stock_manager, scoped_branch
from database import db_connection
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Stock Adjustments'])


class StockAdjustmentCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: int = Field(strict=True, gt=0, le=2147483647)
    product_id: int = Field(strict=True, gt=0, le=2147483647)
    mode: Literal['physical_count', 'damage', 'expiry', 'correction']
    expected_quantity: int = Field(strict=True, ge=0, le=2147483647)
    counted_quantity: int | None = Field(default=None, strict=True, ge=0, le=2147483647)
    quantity_change: int | None = Field(default=None, strict=True, ge=-2147483647, le=2147483647)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode='after')
    def validate_adjustment(self):
        self.reason = self.reason.strip()
        if not self.reason:
            raise ValueError('An adjustment reason is required')
        if self.mode == 'physical_count':
            if self.counted_quantity is None or self.quantity_change is not None:
                raise ValueError('A physical count requires counted_quantity only')
        elif self.counted_quantity is not None or self.quantity_change in (None, 0):
            raise ValueError('Supply a nonzero quantity_change only')
        elif self.mode in ('damage', 'expiry') and self.quantity_change >= 0:
            raise ValueError('Damage and expiry must decrease stock')
        return self


ADJUSTMENT_COLUMNS = 'id, branch_id, branch_name, product_id, product_name, base_unit, mode, quantity_before, quantity_after, quantity_change, reason, created_by, created_by_name, created_at'


def adjustment_response(row):
    result = dict(zip(('id', 'branch_id', 'branch_name', 'product_id', 'product_name', 'base_unit', 'mode',
        'quantity_before', 'quantity_after', 'quantity_change', 'reason', 'created_by', 'created_by_name', 'created_at'), row))
    result['created_at'] = result['created_at'].isoformat()
    return result


@router.post('/stock-adjustments', status_code=201)
def create_stock_adjustment(request: StockAdjustmentCreate, idempotency_key: UUID = Header(),
                            user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'stock_adjustment', request.model_dump(mode='json'), user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT name FROM branches WHERE id = %s FOR UPDATE;', (request.branch_id,))
                branch = cursor.fetchone()
                if branch is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                # Inactive products can still be counted or removed as damaged/expired stock.
                cursor.execute('SELECT name, base_unit FROM products WHERE id = %s FOR SHARE;', (request.product_id,))
                product = cursor.fetchone()
                if product is None:
                    raise HTTPException(status_code=404, detail='Product not found')
                cursor.execute('SELECT quantity FROM inventory WHERE branch_id = %s AND product_id = %s FOR UPDATE;',
                               (request.branch_id, request.product_id))
                balance = cursor.fetchone()
                before = balance[0] if balance else 0
                if before != request.expected_quantity:
                    raise HTTPException(status_code=409, detail='Stock changed since loading; refresh the balance and recount before retrying')
                after = request.counted_quantity if request.mode == 'physical_count' else before + request.quantity_change
                if after < 0 or after > 2147483647:
                    raise HTTPException(status_code=409, detail='Adjustment would make stock negative or exceed the integer range')
                cursor.execute(f'''INSERT INTO stock_adjustments (branch_id, branch_name, product_id, product_name,
                    base_unit, mode, quantity_before, quantity_after, reason, created_by, created_by_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, (SELECT username FROM users WHERE id = %s))
                    RETURNING {ADJUSTMENT_COLUMNS};''', (request.branch_id, branch[0], request.product_id, product[0],
                    product[1], request.mode, before, after, request.reason, user['id'], user['id']))
                result = adjustment_response(cursor.fetchone())
                if after != before:
                    cursor.execute('''INSERT INTO inventory (branch_id, product_id, quantity) VALUES (%s, %s, %s)
                        ON CONFLICT (branch_id, product_id) DO UPDATE SET quantity = EXCLUDED.quantity;''',
                        (request.branch_id, request.product_id, after))
                    cursor.execute('''INSERT INTO stock_movements (branch_id, product_id, quantity_change,
                        movement_type, notes, stock_adjustment_id) VALUES (%s, %s, %s, %s, %s, %s);''',
                        (request.branch_id, request.product_id, after - before,
                         {'physical_count': 'stock_count', 'correction': 'adjustment'}.get(request.mode, request.mode),
                         request.reason, result['id']))
                # Matching physical counts still have an audit record, without a zero movement.
                finish_stock_request(cursor, idempotency_key, result)
    return result


@router.get('/stock-adjustments')
def list_stock_adjustments(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                           limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0, le=2147483647),
                           user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {ADJUSTMENT_COLUMNS} FROM stock_adjustments
            WHERE (%s::integer IS NULL OR branch_id = %s) ORDER BY id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, limit, offset)).fetchall()
    return [adjustment_response(row) for row in rows]
