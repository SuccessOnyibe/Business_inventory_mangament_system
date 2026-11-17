"""Credit: extracted workflows; URLs and transactions are unchanged."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user, require_stock_manager, scoped_branch
from credit_helpers import credit_totals
from database import db_connection
from receipt_helpers import ORDER_COLUMNS, order_response
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Credit'])


class CreditRepaymentCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    order_id: int = Field(strict=True, gt=0, le=2147483647)
    amount: Decimal = Field(gt=0, max_digits=24, decimal_places=2)
    payment_method: Literal['cash', 'pos']
    notes: str | None = Field(default=None, max_length=1000)


class RepaymentVoid(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('A reversal reason is required')
        return value.strip()


REPAYMENT_COLUMNS = 'id, order_id, branch_id, amount, payment_method, notes, reversal_of, created_by, recorded_by_name, created_at'


def repayment_response(row):
    result = dict(zip(REPAYMENT_COLUMNS.split(', '), row))
    result['amount'] = format(result['amount'], '.2f')
    result['created_at'] = result['created_at'].isoformat()
    result['receipt_number'] = f"FAS-P-{result['id']:08d}"
    if len(row) > 10:
        result.update(customer_name=row[10], branch_name=row[11])
    return result


@router.get('/credit-sales')
def credit_sales(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                 limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
                 user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        # One snapshot keeps each reported balance consistent with its collections.
        rows = connection.execute(f'''SELECT {ORDER_COLUMNS},
            COALESCE((SELECT SUM(amount) FROM credit_repayments p WHERE p.order_id = o.id), 0),
            COALESCE((SELECT SUM(debt_reduction) FROM sale_corrections c WHERE c.order_id = o.id), 0)
            FROM sale_orders o WHERE payment_method = 'credit' AND (%s::integer IS NULL OR branch_id = %s)
            ORDER BY id DESC LIMIT %s OFFSET %s;''', (branch_id, branch_id, limit, offset)).fetchall()
    return [{**order_response(row[:12]), 'repaid':format(row[12], '.2f'), 'debt_reduced':format(row[13],'.2f'),
             'outstanding':format(row[6]-row[12]-row[13], '.2f')} for row in rows]


@router.get('/credit-repayments')
def repayments(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
               order_id: int | None = Query(default=None, gt=0, le=2147483647),
               limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
               user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        columns = ', '.join('p.'+key for key in REPAYMENT_COLUMNS.split(', '))
        rows = connection.execute(f'''SELECT {columns}, o.customer_name, o.branch_name
            FROM credit_repayments p JOIN sale_orders o ON o.id=p.order_id
            WHERE (%s::integer IS NULL OR p.branch_id = %s) AND (%s::integer IS NULL OR p.order_id = %s)
            ORDER BY p.id DESC LIMIT %s OFFSET %s;''', (branch_id, branch_id, order_id, order_id, limit, offset)).fetchall()
    return [repayment_response(row) for row in rows]


@router.get('/customers/{customer_id}/balance')
def customer_balance(customer_id: int = Path(gt=0, le=2147483647), user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        row = connection.execute('''SELECT c.branch_id, c.name,
            COALESCE((SELECT SUM(total_amount
                - COALESCE((SELECT SUM(amount) FROM credit_repayments p WHERE p.order_id=o.id),0)
                - COALESCE((SELECT SUM(debt_reduction) FROM sale_corrections s WHERE s.order_id=o.id),0))
                FROM sale_orders o WHERE customer_id=c.id AND payment_method='credit'),0)
            FROM customers c WHERE c.id=%s;''', (customer_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail='Customer not found')
    scoped_branch(user, row[0])
    return dict(customer_id=customer_id, branch_id=row[0], name=row[1], outstanding=format(row[2],'.2f'),
                generated_at=datetime.now(ZoneInfo('Africa/Lagos')).isoformat())


@router.post('/credit-repayments', status_code=201)
def repay_credit(request: CreditRepaymentCreate, idempotency_key: UUID = Header(),
                 user: dict = Depends(get_current_user)):
    payload = request.model_dump(mode='json'); payload['amount'] = format(request.amount, '.2f')
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute("SELECT branch_id FROM sale_orders WHERE id = %s AND payment_method = 'credit';", (request.order_id,))
                row = cursor.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail='Credit sale not found')
                branch_id = row[0]
                # Re-check scope even for a retry after an account's branch changes.
                scoped_branch(user, branch_id)
                previous = begin_stock_request(cursor, idempotency_key, 'credit_repayment', payload, user['id'])
                if previous is not None:
                    return previous
                # Same lock order as sale corrections/counts: branch, then receipt.
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (branch_id,))
                cursor.execute('SELECT id FROM sale_orders WHERE id = %s FOR UPDATE;', (request.order_id,))
                if request.amount > Decimal(credit_totals(cursor, request.order_id)['outstanding']):
                    raise HTTPException(status_code=409, detail='Repayment exceeds the outstanding debt')
                cursor.execute(f'''INSERT INTO credit_repayments (order_id, branch_id, amount, payment_method,
                    notes, created_by, recorded_by_name) VALUES (%s,%s,%s,%s,%s,%s,
                    (SELECT username FROM users WHERE id = %s)) RETURNING {REPAYMENT_COLUMNS};''',
                    (request.order_id, branch_id, request.amount, request.payment_method, request.notes, user['id'], user['id']))
                result = repayment_response(cursor.fetchone())
                result.update(credit_totals(cursor, request.order_id))
                finish_stock_request(cursor, idempotency_key, result)
    return result


@router.post('/credit-repayments/{repayment_id}/void', status_code=201)
def void_repayment(request: RepaymentVoid, repayment_id: int = Path(gt=0, le=2147483647),
                   idempotency_key: UUID = Header(), user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'repayment_void',
                    {'repayment_id':repayment_id, **request.model_dump()}, user['id'])
                if previous is not None:
                    return previous
                cursor.execute(f'SELECT {REPAYMENT_COLUMNS} FROM credit_repayments WHERE id = %s;', (repayment_id,))
                row = cursor.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail='Repayment not found')
                original = repayment_response(row)
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (original['branch_id'],))
                cursor.execute('SELECT id FROM sale_orders WHERE id = %s FOR UPDATE;', (original['order_id'],))
                cursor.execute('SELECT id FROM credit_repayments WHERE reversal_of = %s;', (repayment_id,))
                if row[3] <= 0 or cursor.fetchone() is not None:
                    raise HTTPException(status_code=409, detail='Repayment is already reversed or is itself a reversal')
                totals = credit_totals(cursor, original['order_id'])
                if Decimal(totals['outstanding']) + row[3] > Decimal(totals['credit_net_total']):
                    raise HTTPException(status_code=409, detail='Cannot reverse collections already used for a customer refund')
                # Append a signed reversal dated today; original receipt stays intact.
                cursor.execute(f'''INSERT INTO credit_repayments (order_id, branch_id, amount, payment_method,
                    notes, reversal_of, created_by, recorded_by_name) VALUES (%s,%s,%s,%s,%s,%s,%s,
                    (SELECT username FROM users WHERE id = %s)) RETURNING {REPAYMENT_COLUMNS};''',
                    (row[1],row[2],-row[3],row[4],request.reason,repayment_id,user['id'],user['id']))
                result = repayment_response(cursor.fetchone())
                result.update(credit_totals(cursor, original['order_id']))
                finish_stock_request(cursor, idempotency_key, result)
    return result
