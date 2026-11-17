from database import db_connection
from uuid import UUID
from decimal import Decimal, ROUND_CEILING
from pathlib import Path as FilePath
from typing import Literal
from datetime import date as BusinessDate, datetime, time, timedelta
from zoneinfo import ZoneInfo
import csv
import io
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from psycopg.errors import NumericValueOutOfRange, UniqueViolation
from psycopg.types.json import Jsonb
from auth import get_current_user, require_stock_manager, scoped_branch, router as auth_router
from accounts import router as accounts_router

app = FastAPI(title="FESTY AGRIC SERVICES Inventory API")
app.include_router(auth_router)
app.include_router(accounts_router)
if os.getenv('APP_ALLOWED_HOSTS'):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host.strip() for host in os.environ['APP_ALLOWED_HOSTS'].split(',') if host.strip()])


@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    if request.url.path.startswith('/app'):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    if request.url.scheme == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


@app.get('/health')
def health():
    return {'status':'ok'}


@app.get('/health/ready')
def readiness():
    try:
        with db_connection() as connection:
            ready = connection.execute("""SELECT to_regclass('public.credit_repayments') IS NOT NULL
                AND to_regclass('public.customer_changes') IS NOT NULL AND EXISTS (
                SELECT 1 FROM information_schema.columns WHERE table_schema='public'
                AND table_name='products' AND column_name='barcode')""").fetchone()[0]
        if ready:
            return {'status':'ready'}
    except Exception:
        pass  # Never expose credentials or database errors through public probes.
    raise HTTPException(status_code=503, detail='Database or required schema unavailable')

class ProductBarcode(BaseModel):
    barcode: str | None = Field(default=None, max_length=64, pattern=r'^[!-~]{1,64}$')

    @field_validator('barcode', mode='before')
    @classmethod
    def clean_barcode(cls, value):
        return (value.strip() or None) if isinstance(value,str) else value


class ProductCreate(ProductBarcode):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=50)
    base_unit: str = Field(min_length=1, max_length=30)
    selling_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    max_discount_percent: Decimal = Field(default=Decimal('0'), ge=0, le=100, decimal_places=2)

class StockReceiptCreate(BaseModel):
    branch_id: int = Field(strict=True, gt=0, le=2147483647)
    product_id: int = Field(strict=True, gt=0, le=2147483647)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    notes: str | None = None
    # These describe this delivery, not the quantity remaining in that batch.
    batch_number: str | None = Field(default=None, max_length=100)
    expires_on: BusinessDate | None = None

    @field_validator('batch_number')
    @classmethod
    def clean_batch_number(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError('Enter a batch number or omit it when unknown')
        return value


class ProductUpdate(ProductBarcode):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    base_unit: str | None = Field(default=None, min_length=1, max_length=30)
    is_active: bool | None = None
    selling_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    max_discount_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)


class CustomerDetails(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator('name', 'phone', 'notes')
    @classmethod
    def trim_contact(cls, value, info):
        value = value.strip() if value else None
        if info.field_name == 'name' and not value:
            raise ValueError('Customer name is required')
        return value


class CustomerCreate(CustomerDetails):
    branch_id: int = Field(strict=True, gt=0, le=2147483647)


class CustomerUpdate(CustomerDetails):
    is_active: bool = Field(strict=True)
    expected_version: int = Field(strict=True, gt=0, le=2147483647)


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


class ReconciliationCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    branch_id: int = Field(strict=True, gt=0, le=2147483647)
    business_date: BusinessDate
    actual_cash: Decimal = Field(max_digits=24, decimal_places=2)
    actual_pos: Decimal = Field(max_digits=24, decimal_places=2)
    notes: str | None = Field(default=None, max_length=2000)


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


class ReconciliationReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notes: str | None = Field(default=None, max_length=2000)


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


class DiscrepancyEventCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['investigate', 'resolve', 'reopen']
    explanation: str = Field(min_length=1, max_length=2000)
    resolution_action: str | None = Field(default=None, max_length=2000)
    responsible_user_id: int = Field(strict=True, gt=0, le=2147483647)

    @model_validator(mode='after')
    def require_explanation(self):
        self.explanation = self.explanation.strip()
        if not self.explanation:
            raise ValueError('Explain the investigation or decision')
        if self.action == 'resolve':
            if not self.resolution_action or not self.resolution_action.strip():
                raise ValueError('Describe the resolution action taken')
            self.resolution_action = self.resolution_action.strip()
        elif self.resolution_action is not None:
            raise ValueError('Resolution action applies only to resolving a discrepancy')
        return self


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


def product_response(row):
    return {
        'id': row[0], 'name': row[1], 'category': row[2], 'base_unit': row[3],
        'is_active': row[4],
        # Money is returned as decimal text, avoiding floating-point rounding.
        'selling_price': format(row[5], '.2f') if row[5] is not None else None,
        'max_discount_percent': format(row[6], '.2f'), 'barcode':row[7]
    }


class StockTransferCreate(BaseModel):
    source_branch_id: int = Field(strict=True, gt=0, le=2147483647)
    destination_branch_id: int = Field(strict=True, gt=0, le=2147483647)
    product_id: int = Field(strict=True, gt=0, le=2147483647)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    notes: str | None = None


@app.get("/")
def home():
    return {"message": "FESTY AGRIC SERVICES Inventory API is running"}
@app.get("/branches")
def get_branches(user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user)
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, type FROM branches WHERE (%s::integer IS NULL OR id = %s) ORDER BY id;",
                (branch_id, branch_id)
            )
            rows = cursor.fetchall()

    branches = [
        {"id": row[0], "name": row[1], "type": row[2]}
        for row in rows
    ]

    return branches


@app.get("/products")
def get_products(active_only: bool = False, user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        with connection.cursor() as cursor:
            if active_only:
                cursor.execute(
                    """
                    SELECT id, name, category, base_unit, is_active, selling_price, max_discount_percent, barcode
                    FROM products
                    WHERE is_active = TRUE
                    ORDER BY id;
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT id, name, category, base_unit, is_active, selling_price, max_discount_percent, barcode
                    FROM products
                    ORDER BY id;
                    """
                )

            rows = cursor.fetchall()

    products = [product_response(row) for row in rows]

    return products

PRODUCT_COLUMNS = 'id, name, category, base_unit, is_active, selling_price, max_discount_percent, barcode'


@app.post('/products', status_code=201)
def create_product(product: ProductCreate, user: dict = Depends(require_stock_manager)):
    if 'max_discount_percent' in product.model_fields_set and user['role'] != 'admin':
        raise HTTPException(status_code=403, detail='Only Admin can set discount limits')
    try:
        with db_connection() as connection:
            with connection.transaction():
                row=connection.execute(f'''INSERT INTO products (name,category,base_unit,selling_price,max_discount_percent,barcode)
                    VALUES (%s,%s,%s,%s,%s,%s) RETURNING {PRODUCT_COLUMNS};''',
                    (product.name,product.category,product.base_unit,product.selling_price,product.max_discount_percent,product.barcode)).fetchone()
    except UniqueViolation:
        raise HTTPException(status_code=409,detail='This barcode is already assigned to another product') from None
    return product_response(row)


@app.patch('/products/{product_id}')
def update_product(product_id: int, product: ProductUpdate, user: dict = Depends(require_stock_manager)):
    updates=product.model_dump(exclude_unset=True)
    if 'max_discount_percent' in updates and user['role'] != 'admin':
        raise HTTPException(status_code=403,detail='Only Admin can set discount limits')
    if not updates:
        raise HTTPException(status_code=400,detail='No fields provided for update')
    if any(value is None for key,value in updates.items() if key != 'barcode'):
        raise HTTPException(status_code=422,detail='Product fields cannot be null')
    try:
        with db_connection() as connection:
            with connection.transaction():
                # An omitted code stays unchanged; explicit null clears it.
                row=connection.execute(f'''UPDATE products SET name=COALESCE(%s,name),category=COALESCE(%s,category),
                    base_unit=COALESCE(%s,base_unit),is_active=COALESCE(%s,is_active),
                    selling_price=COALESCE(%s,selling_price),max_discount_percent=COALESCE(%s,max_discount_percent),
                    barcode=CASE WHEN %s THEN %s ELSE barcode END WHERE id=%s RETURNING {PRODUCT_COLUMNS};''',
                    (updates.get('name'),updates.get('category'),updates.get('base_unit'),updates.get('is_active'),
                     updates.get('selling_price'),updates.get('max_discount_percent'),'barcode' in updates,updates.get('barcode'),product_id)).fetchone()
                if row is None:
                    raise HTTPException(status_code=404,detail='Product not found')
    except UniqueViolation:
        raise HTTPException(status_code=409,detail='This barcode is already assigned to another product') from None
    return product_response(row)


def begin_stock_request(cursor, request_id, operation, payload, user_id):
    """Reserve a request key, or return the result of an earlier successful request."""
    # The unique key makes a simultaneous retry wait for the first transaction.
    # If that transaction fails, its reservation rolls back and the retry can run.
    cursor.execute(
        """
        INSERT INTO stock_requests (request_id, operation, request_payload, user_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (request_id) DO NOTHING
        RETURNING request_id;
        """,
        (request_id, operation, Jsonb(payload), user_id)
    )
    if cursor.fetchone() is not None:
        return None

    cursor.execute(
        "SELECT operation, request_payload, response, user_id FROM stock_requests WHERE request_id = %s;",
        (request_id,)
    )
    previous = cursor.fetchone()
    # A key belongs to one operation and body; changing either is a new request.
    # Another user (or a legacy key with no owner) cannot retrieve this response.
    if previous[3] != user_id or previous[0] != operation or previous[1] != payload:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for another request")
    if previous[2] is None:
        raise HTTPException(status_code=409, detail="Stock request has no saved response")
    return previous[2]


def finish_stock_request(cursor, request_id, response):
    # Save the original result in the SAME transaction as stock and movements.
    # Replays return this result, even if the inventory changes again later.
    cursor.execute(
        "UPDATE stock_requests SET response = %s WHERE request_id = %s;",
        (Jsonb(response), request_id)
    )


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


REPAYMENT_COLUMNS = 'id, order_id, branch_id, amount, payment_method, notes, reversal_of, created_by, recorded_by_name, created_at'


def repayment_response(row):
    result = dict(zip(REPAYMENT_COLUMNS.split(', '), row))
    result['amount'] = format(result['amount'], '.2f')
    result['created_at'] = result['created_at'].isoformat()
    result['receipt_number'] = f"FAS-P-{result['id']:08d}"
    if len(row) > 10:
        result.update(customer_name=row[10], branch_name=row[11])
    return result


@app.get('/credit-sales')
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


@app.get('/credit-repayments')
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


@app.get('/customers/{customer_id}/balance')
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


@app.post('/credit-repayments', status_code=201)
def repay_credit(request: CreditRepaymentCreate, idempotency_key: UUID = Header(),
                 user: dict = Depends(require_stock_manager)):
    payload = request.model_dump(mode='json'); payload['amount'] = format(request.amount, '.2f')
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'credit_repayment', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute("SELECT branch_id FROM sale_orders WHERE id = %s AND payment_method = 'credit';", (request.order_id,))
                row = cursor.fetchone()
                if row is None:
                    raise HTTPException(status_code=404, detail='Credit sale not found')
                branch_id = row[0]
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


@app.post('/credit-repayments/{repayment_id}/void', status_code=201)
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


CUSTOMER_COLUMNS = 'id, branch_id, name, phone, notes, is_active, version, created_by, updated_by, created_at, updated_at'


def customer_response(row):
    record = dict(zip(CUSTOMER_COLUMNS.split(', '), row))
    for key in ('created_at', 'updated_at'):
        record[key] = record[key].isoformat()
    return record


@app.get('/customers')
def list_customers(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                   limit: int = Query(default=100, ge=1, le=500),
                   offset: int = Query(default=0, ge=0, le=2147483647),
                   user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {CUSTOMER_COLUMNS} FROM customers
            WHERE (%s::integer IS NULL OR branch_id = %s) ORDER BY id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, limit, offset)).fetchall()
    return [customer_response(row) for row in rows]


def save_customer_change(cursor, record, user_id):
    # Retain each saved version; deactivation never deletes a customer's identity.
    cursor.execute('INSERT INTO customer_changes (customer_id, snapshot, changed_by) VALUES (%s, %s, %s);',
                   (record['id'], Jsonb(record), user_id))


@app.post('/customers', status_code=201)
def create_customer(request: CustomerCreate, idempotency_key: UUID = Header(),
                    user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'customer_create', request.model_dump(), user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR KEY SHARE;', (request.branch_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                cursor.execute(f'''INSERT INTO customers (branch_id, name, phone, notes, created_by, updated_by)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING {CUSTOMER_COLUMNS};''',
                    (request.branch_id, request.name, request.phone, request.notes, user['id'], user['id']))
                record = customer_response(cursor.fetchone())
                save_customer_change(cursor, record, user['id'])
                finish_stock_request(cursor, idempotency_key, record)
    return record


@app.post('/customers/{customer_id}/update')
def update_customer(request: CustomerUpdate, customer_id: int = Path(gt=0, le=2147483647),
                    idempotency_key: UUID = Header(), user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                payload = {'customer_id':customer_id, **request.model_dump()}
                previous = begin_stock_request(cursor, idempotency_key, 'customer_update', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT version FROM customers WHERE id = %s FOR UPDATE;', (customer_id,))
                found = cursor.fetchone()
                if found is None:
                    raise HTTPException(status_code=404, detail='Customer not found')
                # Reject a stale form instead of overwriting another Manager's edit.
                if found[0] != request.expected_version:
                    raise HTTPException(status_code=409, detail='Customer changed; refresh and reopen the edit form')
                cursor.execute(f'''UPDATE customers SET name = %s, phone = %s, notes = %s,
                    is_active = %s, updated_by = %s, updated_at = clock_timestamp(), version = version + 1
                    WHERE id = %s RETURNING {CUSTOMER_COLUMNS};''',
                    (request.name, request.phone, request.notes, request.is_active, user['id'], customer_id))
                record = customer_response(cursor.fetchone())
                save_customer_change(cursor, record, user['id'])
                finish_stock_request(cursor, idempotency_key, record)
    return record


@app.post("/stock-receipts", status_code=201)
def receive_stock(
    receipt: StockReceiptCreate,
    idempotency_key: UUID = Header(description="New UUID per delivery; reuse it for retries"),
    user: dict = Depends(require_stock_manager)
):
    # Omit absent new fields so receipt keys saved before this upgrade still match.
    payload = receipt.model_dump(mode='json', exclude={'batch_number', 'expires_on'})
    for key in ('batch_number', 'expires_on'):
        if getattr(receipt, key) is not None:
            payload[key] = receipt.model_dump(mode='json')[key]
    with db_connection() as connection:
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # Check for a replay before checking mutable product/branch state.
                    previous = begin_stock_request(cursor, idempotency_key, "stock_received", payload, user["id"])
                    if previous is not None:
                        return previous

                    # Check after replay: retrying yesterday's successful delivery
                    # must still work if its expiry date has since passed.
                    if receipt.expires_on and receipt.expires_on < datetime.now(ZoneInfo('Africa/Lagos')).date():
                        raise HTTPException(status_code=422, detail='Cannot receive stock whose labelled expiry date has passed')

                    cursor.execute(
                        "SELECT id FROM branches WHERE id = %s FOR KEY SHARE;",
                        (receipt.branch_id,)
                    )
                    if cursor.fetchone() is None:
                        raise HTTPException(status_code=404, detail="Branch not found")

                    cursor.execute(
                        "SELECT is_active FROM products WHERE id = %s FOR SHARE;",
                        (receipt.product_id,)
                    )
                    product = cursor.fetchone()
                    if product is None:
                        raise HTTPException(status_code=404, detail="Product not found")
                    if not product[0]:
                        raise HTTPException(status_code=409, detail="Product is inactive")

                    cursor.execute(
                        """
                        INSERT INTO inventory (branch_id, product_id, quantity)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (branch_id, product_id)
                        DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity
                        RETURNING quantity;
                        """,
                        (receipt.branch_id, receipt.product_id, receipt.quantity)
                    )
                    updated_quantity = cursor.fetchone()[0]

                    cursor.execute(
                        """
                        INSERT INTO stock_movements
                            (branch_id, product_id, quantity_change, movement_type, notes,
                             batch_number, expires_on, received_by, received_by_name)
                        VALUES (%s, %s, %s, 'stock_received', %s, %s, %s, %s,
                            (SELECT username FROM users WHERE id = %s)) RETURNING id, created_at;
                        """,
                        (receipt.branch_id, receipt.product_id, receipt.quantity, receipt.notes,
                         receipt.batch_number, receipt.expires_on, user['id'], user['id'])
                    )
                    movement_id, received_at = cursor.fetchone()
                    response = {
                        "branch_id": receipt.branch_id,
                        "product_id": receipt.product_id,
                        "quantity_received": receipt.quantity,
                        "updated_quantity": updated_quantity,
                        "movement_id": movement_id,
                        "received_at": received_at.isoformat(),
                        "batch_number": receipt.batch_number,
                        "expires_on": receipt.expires_on.isoformat() if receipt.expires_on else None
                    }
                    finish_stock_request(cursor, idempotency_key, response)
        except NumericValueOutOfRange:
            raise HTTPException(
                status_code=409,
                detail="Receiving this quantity would exceed PostgreSQL's integer range"
            ) from None

    return response


@app.get('/stock-receipts')
def receipt_history(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                    product_id: int | None = Query(default=None, gt=0, le=2147483647),
                    limit: int = Query(default=100, ge=1, le=500),
                    offset: int = Query(default=0, ge=0, le=2147483647),
                    user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute('''SELECT id, branch_id, product_id, quantity_change,
            batch_number, expires_on, received_by, received_by_name, notes, created_at
            FROM stock_movements WHERE movement_type = 'stock_received'
            AND (%s::integer IS NULL OR branch_id = %s)
            AND (%s::integer IS NULL OR product_id = %s)
            ORDER BY id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, product_id, product_id, limit, offset)).fetchall()
    keys = ('id', 'branch_id', 'product_id', 'quantity_received', 'batch_number', 'expires_on',
            'received_by', 'received_by_name', 'notes', 'received_at')
    records = []
    for row in rows:
        record = dict(zip(keys, row))
        record['expires_on'] = row[5].isoformat() if row[5] else None
        record['received_at'] = row[9].isoformat()
        records.append(record)
    return records


@app.post("/stock-transfers", status_code=201)
def transfer_stock(
    transfer: StockTransferCreate,
    idempotency_key: UUID = Header(description="New UUID per transfer; reuse it for retries"),
    user: dict = Depends(require_stock_manager)
):
    if transfer.source_branch_id == transfer.destination_branch_id:
        raise HTTPException(status_code=422, detail="Source and destination must be different")

    with db_connection() as connection:
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    previous = begin_stock_request(cursor, idempotency_key, "stock_transfer", transfer.model_dump(), user["id"])
                    if previous is not None:
                        return previous
                    # Lock branches in a consistent order, including when inventory is missing.
                    for branch_id in sorted((transfer.source_branch_id, transfer.destination_branch_id)):
                        cursor.execute(
                            "SELECT id FROM branches WHERE id = %s FOR UPDATE;",
                            (branch_id,)
                        )
                        if cursor.fetchone() is None:
                            raise HTTPException(status_code=404, detail="Branch not found")

                    cursor.execute(
                        "SELECT is_active FROM products WHERE id = %s FOR SHARE;",
                        (transfer.product_id,)
                    )
                    product = cursor.fetchone()
                    if product is None:
                        raise HTTPException(status_code=404, detail="Product not found")
                    if not product[0]:
                        raise HTTPException(status_code=409, detail="Product is inactive")

                    cursor.execute(
                        """
                        UPDATE inventory SET quantity = quantity - %s
                        WHERE branch_id = %s AND product_id = %s AND quantity >= %s
                        RETURNING quantity;
                        """,
                        (transfer.quantity, transfer.source_branch_id,
                         transfer.product_id, transfer.quantity)
                    )
                    source = cursor.fetchone()
                    if source is None:
                        raise HTTPException(status_code=409, detail="Insufficient source stock")

                    # Dispatch removes stock from availability, but does not credit
                    # the receiving branch until someone there confirms delivery.
                    cursor.execute(
                        """
                        INSERT INTO stock_transfers
                            (source_branch_id, destination_branch_id, product_id, quantity, notes, created_by)
                        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at;
                        """,
                        (transfer.source_branch_id, transfer.destination_branch_id, transfer.product_id,
                         transfer.quantity, transfer.notes, user["id"])
                    )
                    transfer_id, created_at = cursor.fetchone()

                    cursor.execute(
                        """
                        INSERT INTO stock_movements
                            (branch_id, product_id, quantity_change, movement_type, notes, transfer_id)
                        VALUES (%s, %s, %s, 'transfer_out', %s, %s);
                        """,
                        (transfer.source_branch_id, transfer.product_id, -transfer.quantity,
                         transfer.notes, transfer_id)
                    )
                    response = {
                        "transfer_id": transfer_id,
                        "status": "in_transit",
                        "created_at": created_at.isoformat(),
                        "source_branch_id": transfer.source_branch_id,
                        "destination_branch_id": transfer.destination_branch_id,
                        "product_id": transfer.product_id,
                        "quantity_transferred": transfer.quantity,
                        "source_quantity": source[0]
                    }
                    finish_stock_request(cursor, idempotency_key, response)
        except NumericValueOutOfRange:
            raise HTTPException(
                status_code=409,
                detail="Transfer would exceed PostgreSQL's integer range"
            ) from None

    return response


@app.get("/stock-transfers")
def list_stock_transfers(
    branch_id: int | None = Query(default=None, gt=0, le=2147483647),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2147483647),
    user: dict = Depends(get_current_user)
):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, source_branch_id, destination_branch_id, product_id,
                   quantity, status, notes, created_at, received_at
            FROM stock_transfers
            WHERE (%s::integer IS NULL OR source_branch_id = %s OR destination_branch_id = %s)
            ORDER BY id DESC LIMIT %s OFFSET %s;
            """, (branch_id, branch_id, branch_id, limit, offset)
        ).fetchall()
    keys = ("id", "source_branch_id", "destination_branch_id", "product_id",
            "quantity", "status", "notes", "created_at", "received_at")
    return [dict(zip(keys, row)) for row in rows]


@app.post("/stock-transfers/{transfer_id}/confirm")
def confirm_stock_transfer(transfer_id: int = Path(gt=0, le=2147483647), user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    # Lock the transfer itself: concurrent confirmations can credit it once only.
                    cursor.execute(
                        """
                        SELECT source_branch_id, destination_branch_id, product_id,
                               quantity, status, notes, destination_quantity, created_at, received_at
                        FROM stock_transfers WHERE id = %s FOR UPDATE;
                        """, (transfer_id,)
                    )
                    transfer = cursor.fetchone()
                    if transfer is None:
                        raise HTTPException(status_code=404, detail="Transfer not found")
                    source_id, destination_id, product_id, quantity, status, notes, saved_quantity, created_at, received_at = transfer
                    scoped_branch(user, destination_id)
                    if status == "received":
                        return {"transfer_id": transfer_id, "status": "received",
                                "destination_quantity": saved_quantity,
                                "created_at": created_at.isoformat(), "received_at": received_at.isoformat()}
                    for branch_id in sorted((source_id, destination_id)):
                        cursor.execute("SELECT id FROM branches WHERE id = %s FOR UPDATE;", (branch_id,))
                    cursor.execute(
                        """
                        INSERT INTO inventory (branch_id, product_id, quantity) VALUES (%s, %s, %s)
                        ON CONFLICT (branch_id, product_id)
                        DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity
                        RETURNING quantity;
                        """, (destination_id, product_id, quantity)
                    )
                    destination_quantity = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO stock_movements
                            (branch_id, product_id, quantity_change, movement_type, notes, transfer_id)
                        VALUES (%s, %s, %s, 'transfer_in', %s, %s);
                        """, (destination_id, product_id, quantity, notes, transfer_id)
                    )
                    cursor.execute(
                        """
                        UPDATE stock_transfers SET status = 'received', confirmed_by = %s,
                            received_at = clock_timestamp(), destination_quantity = %s WHERE id = %s
                        RETURNING received_at;
                        """, (user["id"], destination_quantity, transfer_id)
                    )
                    received_at = cursor.fetchone()[0]
        except NumericValueOutOfRange:
            raise HTTPException(status_code=409, detail="Receiving transfer would exceed PostgreSQL's integer range") from None
    return {"transfer_id": transfer_id, "status": "received", "destination_quantity": destination_quantity,
            "created_at": created_at.isoformat(), "received_at": received_at.isoformat()}


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


@app.post('/sales', status_code=201)
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


@app.get('/sales')
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


@app.post('/checkouts', status_code=201)
def create_checkout(checkout: CheckoutCreate, idempotency_key: UUID = Header(),
                    user: dict = Depends(get_current_user)):
    scoped_branch(user, checkout.branch_id)
    if checkout.payment_method == 'credit' and user['role'] not in ('admin','manager'):
        raise HTTPException(status_code=403, detail='Manager/Admin permission required for credit sales')
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


@app.get('/checkouts')
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


@app.get('/checkouts/{order_id}')
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


@app.get('/sales/{sale_id}/receipt')
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


@app.post('/sale-corrections', status_code=201)
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


@app.get('/sale-corrections')
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


@app.get('/sale-corrections/{correction_id}')
def get_sale_correction(correction_id: int = Path(gt=0, le=2147483647), user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT branch_id FROM sale_corrections WHERE id = %s;', (correction_id,))
            branch = cursor.fetchone()
            if branch is None:
                raise HTTPException(status_code=404, detail='Correction not found')
            scoped_branch(user, branch[0])
            return correction_details(cursor, correction_id)


@app.get("/stock-movements")
def get_stock_movements(
    branch_id: int | None = Query(default=None, gt=0, le=2147483647),
    product_id: int | None = Query(default=None, gt=0, le=2147483647),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=2147483647),
    user: dict = Depends(get_current_user)
):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, branch_id, product_id, quantity_change,
                       movement_type, notes, created_at, transfer_id, sale_id, correction_item_id, stock_adjustment_id
                FROM stock_movements
                WHERE (%s::integer IS NULL OR branch_id = %s)
                  AND (%s::integer IS NULL OR product_id = %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s OFFSET %s;
                """,
                (branch_id, branch_id, product_id, product_id, limit, offset)
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "branch_id": row[1],
            "product_id": row[2],
            "quantity_change": row[3],
            "movement_type": row[4],
            "notes": row[5],
            "created_at": row[6],
            "transfer_id": row[7],
            "sale_id": row[8],
            "correction_item_id": row[9],
            "stock_adjustment_id": row[10]
        }
        for row in rows
    ]


@app.get("/inventory")
def get_inventory(branch_id: int | None = None, user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
    """
    SELECT
        inventory.id,
        branches.id AS branch_id,
        branches.name AS branch,
        products.id AS product_id,
        products.name AS product,
        inventory.quantity,
        products.base_unit AS unit
    FROM inventory
    JOIN branches ON inventory.branch_id = branches.id
    JOIN products ON inventory.product_id = products.id
    WHERE (%s::integer IS NULL OR inventory.branch_id = %s)
    ORDER BY branches.id, products.id;
    """,
    (branch_id, branch_id)
)
            rows = cursor.fetchall()

    inventory_records = [
    {
        "id": row[0],
        "branch_id": row[1],
        "branch": row[2],
        "product_id": row[3],
        "product": row[4],
        "quantity": row[5],
        "unit": row[6]
    }
    for row in rows
]

    return inventory_records


RECONCILIATION_COLUMNS = ('id', 'branch_id', 'business_date', 'revision', 'expected_cash',
    'expected_pos', 'actual_cash', 'actual_pos', 'cash_difference', 'pos_difference',
    'sales_count', 'last_sale_id', 'notes', 'submitted_by', 'submitted_at',
    'reviewed_by', 'reviewed_at', 'review_notes', 'gross_cash', 'gross_pos',
    'refund_cash', 'refund_pos', 'refund_count', 'last_correction_id',
    'cash_in', 'cash_out', 'cash_movement_effect', 'movement_count', 'last_movement_id', 'repayment_count', 'last_repayment_id')
RECONCILIATION_SELECT = ', '.join(RECONCILIATION_COLUMNS)


def reconciliation_response(row):
    result = dict(zip(RECONCILIATION_COLUMNS, row))
    for key in ('expected_cash', 'expected_pos', 'actual_cash', 'actual_pos', 'cash_difference', 'pos_difference',
                'gross_cash', 'gross_pos', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out', 'cash_movement_effect'):
        result[key] = format(result[key], '.2f')
    for key in ('business_date', 'submitted_at', 'reviewed_at'):
        if result[key] is not None:
            result[key] = result[key].isoformat()
    result['status'] = 'reviewed' if result['reviewed_at'] else 'submitted'
    result['currency'] = 'NGN'
    return result


def daily_sales_totals(cursor, branch_id, business_date):
    lagos = ZoneInfo('Africa/Lagos')
    if business_date > datetime.now(lagos).date():
        raise HTTPException(status_code=422, detail='Cannot reconcile a future date')
    # A business day is midnight-to-midnight in Lagos, not the database server's zone.
    start = datetime.combine(business_date, time.min, tzinfo=lagos)
    end = start + timedelta(days=1)
    cursor.execute(
        '''WITH purchases AS (
               SELECT id, branch_id, total_amount, payment_method, created_at FROM sales WHERE order_id IS NULL
               UNION ALL
               SELECT (SELECT MAX(id) FROM sales WHERE order_id = o.id), branch_id,
                      total_amount, payment_method, created_at FROM sale_orders o
           ) SELECT COUNT(*), COALESCE(SUM(total_amount) FILTER (WHERE payment_method = 'cash'), 0),
                  COALESCE(SUM(total_amount) FILTER (WHERE payment_method = 'pos'), 0),
                  COUNT(*) FILTER (WHERE payment_method IS NULL),
                  COALESCE(SUM(total_amount) FILTER (WHERE payment_method IS NULL), 0), MAX(id)
           FROM purchases WHERE branch_id = %s AND created_at >= %s AND created_at < %s;''',
        (branch_id, start, end)
    )
    row = cursor.fetchone()
    cursor.execute('''SELECT COALESCE(SUM(refund_total) FILTER (WHERE refund_method = 'cash'), 0),
        COALESCE(SUM(refund_total) FILTER (WHERE refund_method = 'pos'), 0), COUNT(*), MAX(id)
        FROM sale_corrections WHERE branch_id = %s AND created_at >= %s AND created_at < %s;''', (branch_id, start, end))
    refunds = cursor.fetchone()
    cursor.execute('''SELECT COALESCE(SUM(cash_in), 0), COALESCE(SUM(cash_out), 0),
        COALESCE(SUM(expected_cash_effect), 0), COUNT(*), MAX(id) FROM cash_movements
        WHERE branch_id = %s AND business_date = %s;''', (branch_id, business_date))
    cash = cursor.fetchone()
    cursor.execute('''SELECT COALESCE(SUM(amount) FILTER (WHERE payment_method = 'cash'),0),
        COALESCE(SUM(amount) FILTER (WHERE payment_method = 'pos'),0), COUNT(*), MAX(id)
        FROM credit_repayments WHERE branch_id = %s AND created_at >= %s AND created_at < %s;''', (branch_id,start,end))
    repayments = cursor.fetchone()
    return dict(repaid_cash=format(repayments[0], '.2f'), repaid_pos=format(repayments[1], '.2f'),
                repayment_count=repayments[2], last_repayment_id=repayments[3], sales_count=row[0], expected_cash=format(row[1] - refunds[0] + cash[2] + repayments[0], '.2f'), expected_pos=format(row[2] - refunds[1] + repayments[1], '.2f'),
                gross_cash=format(row[1], '.2f'), gross_pos=format(row[2], '.2f'),
                refund_cash=format(refunds[0], '.2f'), refund_pos=format(refunds[1], '.2f'),
                refund_count=refunds[2], last_correction_id=refunds[3],
                cash_in=format(cash[0], '.2f'), cash_out=format(cash[1], '.2f'), cash_movement_effect=format(cash[2], '.2f'),
                movement_count=cash[3], last_movement_id=cash[4],
                unclassified_count=row[3], unclassified_amount=format(row[4], '.2f'), last_sale_id=row[5])


def reconciliation_stale(record, totals):
    return totals['unclassified_count'] > 0 or any(record[key] != totals[key] for key in
        ('sales_count', 'last_sale_id', 'expected_cash', 'expected_pos', 'gross_cash', 'gross_pos',
         'refund_cash', 'refund_pos', 'refund_count', 'last_correction_id',
         'cash_in', 'cash_out', 'cash_movement_effect', 'movement_count', 'last_movement_id', 'repayment_count', 'last_repayment_id'))


@app.get('/reconciliations/summary')
def reconciliation_summary(branch_id: int = Query(gt=0, le=2147483647),
                           business_date: BusinessDate = Query(),
                           user: dict = Depends(get_current_user)):
    scoped_branch(user, branch_id)
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                # Sales and submissions lock this same branch row, keeping the summary coherent.
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR SHARE;', (branch_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                totals = daily_sales_totals(cursor, branch_id, business_date)
                cursor.execute(f'''SELECT {RECONCILIATION_SELECT} FROM daily_reconciliations
                    WHERE branch_id = %s AND business_date = %s ORDER BY revision DESC LIMIT 1;''',
                    (branch_id, business_date))
                row = cursor.fetchone()
                latest = reconciliation_response(row) if row else None
                if latest:
                    latest.update(discrepancy_state(cursor, latest))
    return {'branch_id': branch_id, 'business_date': business_date.isoformat(), **totals,
            'latest_submission': latest, 'is_stale': reconciliation_stale(latest, totals) if latest else False}


@app.post('/reconciliations', status_code=201)
def submit_reconciliation(submission: ReconciliationCreate, idempotency_key: UUID = Header(),
                          user: dict = Depends(get_current_user)):
    scoped_branch(user, submission.branch_id)
    payload = submission.model_dump(mode='json')
    for key in ('actual_cash', 'actual_pos'):
        payload[key] = format(getattr(submission, key), '.2f')
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'reconciliation', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (submission.branch_id,))
                if cursor.fetchone() is None:
                    raise HTTPException(status_code=404, detail='Branch not found')
                totals = daily_sales_totals(cursor, submission.branch_id, submission.business_date)
                if totals['unclassified_count']:
                    raise HTTPException(status_code=409, detail='Sales with unknown payment methods prevent reconciliation')
                cursor.execute('''SELECT COALESCE(MAX(revision), 0) + 1 FROM daily_reconciliations
                                  WHERE branch_id = %s AND business_date = %s;''',
                               (submission.branch_id, submission.business_date))
                revision = cursor.fetchone()[0]
                # Corrections append revisions. They never overwrite earlier counts or reviews.
                cursor.execute(f'''INSERT INTO daily_reconciliations
                    (branch_id, business_date, revision, expected_cash, expected_pos, actual_cash,
                     actual_pos, sales_count, last_sale_id, notes, submitted_by, gross_cash, gross_pos,
                     refund_cash, refund_pos, refund_count, last_correction_id,
                     cash_in, cash_out, cash_movement_effect, movement_count, last_movement_id, repayment_count, last_repayment_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {RECONCILIATION_SELECT};''',
                    (submission.branch_id, submission.business_date, revision, totals['expected_cash'],
                     totals['expected_pos'], submission.actual_cash, submission.actual_pos,
                     totals['sales_count'], totals['last_sale_id'], submission.notes, user['id'], totals['gross_cash'],
                     totals['gross_pos'], totals['refund_cash'], totals['refund_pos'], totals['refund_count'], totals['last_correction_id'],
                     totals['cash_in'], totals['cash_out'], totals['cash_movement_effect'], totals['movement_count'], totals['last_movement_id'], totals['repayment_count'], totals['last_repayment_id']))
                result = reconciliation_response(cursor.fetchone())
                finish_stock_request(cursor, idempotency_key, result)
    return result


@app.get('/reconciliations')
def list_reconciliations(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                        limit: int = Query(default=100, ge=1, le=500),
                        offset: int = Query(default=0, ge=0, le=2147483647),
                        user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {RECONCILIATION_SELECT},
            NOT EXISTS (SELECT 1 FROM daily_reconciliations newer WHERE newer.branch_id = r.branch_id
                AND newer.business_date = r.business_date AND newer.revision > r.revision)
            FROM daily_reconciliations r WHERE (%s::integer IS NULL OR branch_id = %s)
            ORDER BY id DESC LIMIT %s OFFSET %s;''', (branch_id, branch_id, limit, offset)).fetchall()
        result = [{**reconciliation_response(row), 'is_latest': row[-1]} for row in rows]
        with connection.cursor() as cursor:
            cursor.execute('''SELECT DISTINCT ON (reconciliation_id) reconciliation_id, action,
                responsible_user_id, responsible_name FROM discrepancy_events
                WHERE reconciliation_id = ANY(%s) ORDER BY reconciliation_id, id DESC;''', ([row['id'] for row in result],))
            events = {row[0]: row[1:] for row in cursor.fetchall()}
        for row in result:
            event = events.get(row['id'])
            row.update(resolution_state=discrepancy_action_state(event[0]) if event else
                'balanced' if Decimal(row['cash_difference']) == 0 and Decimal(row['pos_difference']) == 0 else 'open',
                responsible_user_id=event[1] if event else None, responsible_name=event[2] if event else None)
    return result


@app.post('/reconciliations/{reconciliation_id}/review')
def review_reconciliation(review: ReconciliationReview,
                          reconciliation_id: int = Path(gt=0, le=2147483647),
                          user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute('SELECT branch_id FROM daily_reconciliations WHERE id = %s;', (reconciliation_id,))
                branch = cursor.fetchone()
                if branch is None:
                    raise HTTPException(status_code=404, detail='Reconciliation not found')
                # Lock order matches submissions/sales: branch first, then the record.
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (branch[0],))
                cursor.execute(f'SELECT {RECONCILIATION_SELECT} FROM daily_reconciliations WHERE id = %s FOR UPDATE;',
                               (reconciliation_id,))
                record = reconciliation_response(cursor.fetchone())
                if record['status'] == 'reviewed':
                    return record  # A repeated review cannot replace the first reviewer or timestamp.
                cursor.execute('SELECT MAX(revision) FROM daily_reconciliations WHERE branch_id = %s AND business_date = %s;',
                               (record['branch_id'], record['business_date']))
                latest_revision = cursor.fetchone()[0]
                totals = daily_sales_totals(cursor, record['branch_id'], BusinessDate.fromisoformat(record['business_date']))
                if record['revision'] != latest_revision or reconciliation_stale(record, totals):
                    raise HTTPException(status_code=409, detail='Submission is out of date; submit updated counts before review')
                cursor.execute(f'''UPDATE daily_reconciliations SET reviewed_by = %s,
                    reviewed_at = clock_timestamp(), review_notes = %s WHERE id = %s
                    RETURNING {RECONCILIATION_SELECT};''', (user['id'], review.notes, reconciliation_id))
                result = reconciliation_response(cursor.fetchone())
    return result


def discrepancy_action_state(action):
    return {'investigate': 'investigating', 'resolve': 'resolved', 'reopen': 'open'}[action]


def discrepancy_state(cursor, record):
    cursor.execute('''SELECT action, responsible_user_id, responsible_name FROM discrepancy_events
        WHERE reconciliation_id = %s ORDER BY id DESC LIMIT 1;''', (record['id'],))
    event = cursor.fetchone()
    balanced = Decimal(record['cash_difference']) == 0 and Decimal(record['pos_difference']) == 0
    return dict(resolution_state=discrepancy_action_state(event[0]) if event else 'balanced' if balanced else 'open',
                responsible_user_id=event[1] if event else None, responsible_name=event[2] if event else None)


EVENT_SELECT = '''e.id, e.reconciliation_id, e.action, e.explanation, e.resolution_action,
    e.responsible_user_id, e.responsible_name, e.created_by, e.created_by_name, e.created_at,
    r.branch_id, r.business_date'''


def event_response(row):
    result = dict(zip(('id', 'reconciliation_id', 'action', 'explanation', 'resolution_action',
        'responsible_user_id', 'responsible_name', 'created_by', 'created_by_name', 'created_at', 'branch_id', 'business_date'), row))
    result['created_at'] = result['created_at'].isoformat()
    result['business_date'] = result['business_date'].isoformat()
    result['resolution_state'] = discrepancy_action_state(result['action'])
    return result


@app.get('/reconciliations/{reconciliation_id}/assignees')
def discrepancy_assignees(reconciliation_id: int = Path(gt=0, le=2147483647), user: dict = Depends(require_stock_manager)):
    with db_connection() as connection:
        branch = connection.execute('SELECT branch_id FROM daily_reconciliations WHERE id = %s;', (reconciliation_id,)).fetchone()
        if branch is None:
            raise HTTPException(status_code=404, detail='Reconciliation not found')
        rows = connection.execute('''SELECT id, username, role FROM users WHERE is_active = TRUE
            AND (role <> 'salesperson' OR branch_id = %s) ORDER BY username;''', (branch[0],)).fetchall()
    return [dict(id=row[0], username=row[1], role=row[2]) for row in rows]


@app.post('/reconciliations/{reconciliation_id}/discrepancy-events', status_code=201)
def create_discrepancy_event(request: DiscrepancyEventCreate, reconciliation_id: int = Path(gt=0, le=2147483647),
                             idempotency_key: UUID = Header(), user: dict = Depends(require_stock_manager)):
    payload = {'reconciliation_id': reconciliation_id, **request.model_dump(mode='json')}
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                previous = begin_stock_request(cursor, idempotency_key, 'discrepancy_event', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT branch_id FROM daily_reconciliations WHERE id = %s;', (reconciliation_id,))
                branch = cursor.fetchone()
                if branch is None:
                    raise HTTPException(status_code=404, detail='Reconciliation not found')
                cursor.execute('SELECT id FROM branches WHERE id = %s FOR UPDATE;', (branch[0],))
                cursor.execute(f'SELECT {RECONCILIATION_SELECT} FROM daily_reconciliations WHERE id = %s FOR UPDATE;', (reconciliation_id,))
                record = reconciliation_response(cursor.fetchone())
                cursor.execute('SELECT MAX(revision) FROM daily_reconciliations WHERE branch_id = %s AND business_date = %s;',
                               (record['branch_id'], record['business_date']))
                if cursor.fetchone()[0] != record['revision'] or reconciliation_stale(record,
                        daily_sales_totals(cursor, branch[0], BusinessDate.fromisoformat(record['business_date']))):
                    raise HTTPException(status_code=409, detail='Count is superseded or out of date; submit current counts first')
                current = discrepancy_state(cursor, record)['resolution_state']
                if current == 'balanced':
                    raise HTTPException(status_code=409, detail='This count has no discrepancy')
                if (request.action == 'reopen') != (current == 'resolved'):
                    raise HTTPException(status_code=409, detail='Reopen a resolved discrepancy before adding another decision')
                if request.action == 'resolve' and record['reviewed_at'] is None:
                    raise HTTPException(status_code=409, detail='Review the count before resolving its discrepancy')
                cursor.execute('SELECT username, role, branch_id, is_active FROM users WHERE id = %s;', (request.responsible_user_id,))
                responsible = cursor.fetchone()
                if responsible is None:
                    raise HTTPException(status_code=404, detail='Responsible user not found')
                if not responsible[3] or (responsible[1] == 'salesperson' and responsible[2] != branch[0]):
                    raise HTTPException(status_code=422, detail='Assign an active member of this branch or a Manager/Admin')
                # This records a decision; no submitted amount, sale, or payment is altered.
                cursor.execute('''INSERT INTO discrepancy_events (reconciliation_id, action, explanation,
                    resolution_action, responsible_user_id, responsible_name, created_by, created_by_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, (SELECT username FROM users WHERE id = %s)) RETURNING id;''',
                    (reconciliation_id, request.action, request.explanation, request.resolution_action,
                     request.responsible_user_id, responsible[0], user['id'], user['id']))
                event_id = cursor.fetchone()[0]
                cursor.execute(f'''SELECT {EVENT_SELECT} FROM discrepancy_events e
                    JOIN daily_reconciliations r ON r.id = e.reconciliation_id WHERE e.id = %s;''', (event_id,))
                result = event_response(cursor.fetchone())
                finish_stock_request(cursor, idempotency_key, result)
    return result


@app.get('/discrepancy-events')
def list_discrepancy_events(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                            limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0, le=2147483647),
                            user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {EVENT_SELECT} FROM discrepancy_events e
            JOIN daily_reconciliations r ON r.id = e.reconciliation_id
            WHERE (%s::integer IS NULL OR r.branch_id = %s) ORDER BY e.id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, limit, offset)).fetchall()
    return [event_response(row) for row in rows]


ADJUSTMENT_COLUMNS = 'id, branch_id, branch_name, product_id, product_name, base_unit, mode, quantity_before, quantity_after, quantity_change, reason, created_by, created_by_name, created_at'


def adjustment_response(row):
    result = dict(zip(('id', 'branch_id', 'branch_name', 'product_id', 'product_name', 'base_unit', 'mode',
        'quantity_before', 'quantity_after', 'quantity_change', 'reason', 'created_by', 'created_by_name', 'created_at'), row))
    result['created_at'] = result['created_at'].isoformat()
    return result


@app.post('/stock-adjustments', status_code=201)
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


@app.get('/stock-adjustments')
def list_stock_adjustments(branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                           limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0, le=2147483647),
                           user: dict = Depends(get_current_user)):
    branch_id = scoped_branch(user, branch_id)
    with db_connection() as connection:
        rows = connection.execute(f'''SELECT {ADJUSTMENT_COLUMNS} FROM stock_adjustments
            WHERE (%s::integer IS NULL OR branch_id = %s) ORDER BY id DESC LIMIT %s OFFSET %s;''',
            (branch_id, branch_id, limit, offset)).fetchall()
    return [adjustment_response(row) for row in rows]


def financial_report_data(start_date, end_date, branch_id):
    lagos = ZoneInfo('Africa/Lagos')
    if end_date < start_date or (end_date - start_date).days >= 366 or end_date > datetime.now(lagos).date():
        raise HTTPException(status_code=422, detail='Choose a non-future date range of at most 366 days')
    start = datetime.combine(start_date, time.min, tzinfo=lagos)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=lagos)
    keys = ('id', 'reviewed_at', 'cash_difference', 'pos_difference', 'sales_count', 'last_sale_id',
        'expected_cash', 'expected_pos', 'gross_cash', 'gross_pos', 'refund_cash', 'refund_pos', 'refund_count', 'last_correction_id',
        'cash_in', 'cash_out', 'cash_movement_effect', 'movement_count', 'last_movement_id', 'repayment_count', 'last_repayment_id')
    snapshot_select = ', '.join(f'latest.{key} AS snapshot_{key}' for key in keys)
    # One statement gives sales, refunds, counts and decisions one coherent database view.
    sql = f'''WITH bounds AS (SELECT %s::date first_day, %s::date last_day,
        %s::timestamptz start_at, %s::timestamptz end_at, %s::integer branch_filter),
    purchases AS (
        SELECT id, branch_id, total_amount, payment_method, created_at FROM sales WHERE order_id IS NULL
        UNION ALL SELECT (SELECT MAX(id) FROM sales WHERE order_id = o.id), branch_id,
            total_amount, payment_method, created_at FROM sale_orders o),
    gross AS (SELECT p.branch_id, (p.created_at AT TIME ZONE 'Africa/Lagos')::date business_date,
        COUNT(*) sales_count, MAX(id) last_sale_id,
        SUM(total_amount) FILTER (WHERE payment_method = 'cash') gross_cash,
        SUM(total_amount) FILTER (WHERE payment_method = 'pos') gross_pos,
        SUM(total_amount) FILTER (WHERE payment_method = 'credit') gross_credit,
        COUNT(*) FILTER (WHERE payment_method IS NULL) unclassified_count,
        SUM(total_amount) FILTER (WHERE payment_method IS NULL) unclassified_amount
        FROM purchases p CROSS JOIN bounds WHERE created_at >= start_at AND created_at < end_at GROUP BY 1, 2),
    refunds AS (SELECT c.branch_id, (c.created_at AT TIME ZONE 'Africa/Lagos')::date business_date,
        COUNT(*) refund_count, MAX(id) last_correction_id,
        SUM(refund_total) FILTER (WHERE refund_method = 'cash') refund_cash,
        SUM(refund_total) FILTER (WHERE refund_method = 'pos') refund_pos, SUM(debt_reduction) debt_reduced
        FROM sale_corrections c CROSS JOIN bounds WHERE created_at >= start_at AND created_at < end_at GROUP BY 1, 2),
    collections AS (SELECT branch_id, (created_at AT TIME ZONE 'Africa/Lagos')::date business_date,
        SUM(amount) FILTER (WHERE payment_method = 'cash') repaid_cash,
        SUM(amount) FILTER (WHERE payment_method = 'pos') repaid_pos, COUNT(*) repayment_count, MAX(id) last_repayment_id
        FROM credit_repayments CROSS JOIN bounds WHERE created_at >= start_at AND created_at < end_at GROUP BY 1,2),
    drawer AS (SELECT m.branch_id, m.business_date, SUM(cash_in) cash_in, SUM(cash_out) cash_out,
        SUM(expected_cash_effect) cash_movement_effect, COUNT(*) movement_count, MAX(id) last_movement_id
        FROM cash_movements m CROSS JOIN bounds WHERE business_date BETWEEN first_day AND last_day GROUP BY 1,2),
    latest AS (SELECT DISTINCT ON (r.branch_id, r.business_date) r.* FROM daily_reconciliations r CROSS JOIN bounds
        WHERE business_date BETWEEN first_day AND last_day ORDER BY r.branch_id, r.business_date, revision DESC),
    decisions AS (SELECT DISTINCT ON (reconciliation_id) reconciliation_id, action, responsible_name
        FROM discrepancy_events ORDER BY reconciliation_id, id DESC),
    calendar AS (SELECT b.id branch_id, b.name branch_name, d::date business_date FROM branches b CROSS JOIN bounds
        CROSS JOIN LATERAL generate_series(first_day::timestamp, last_day::timestamp, INTERVAL '1 day') d
        WHERE branch_filter IS NULL OR b.id = branch_filter)
    SELECT calendar.*, COALESCE(gross.gross_credit,0) gross_credit, COALESCE(refunds.debt_reduced,0) debt_reduced,
        COALESCE(collections.repaid_cash,0) repaid_cash, COALESCE(collections.repaid_pos,0) repaid_pos,
        COALESCE(collections.repayment_count,0) repayment_count, collections.last_repayment_id,
        COALESCE(gross.sales_count, 0) sales_count, gross.last_sale_id,
        COALESCE(gross.gross_cash, 0) gross_cash, COALESCE(gross.gross_pos, 0) gross_pos,
        COALESCE(gross.unclassified_count, 0) unclassified_count, COALESCE(gross.unclassified_amount, 0) unclassified_amount,
        COALESCE(refunds.refund_cash, 0) refund_cash, COALESCE(refunds.refund_pos, 0) refund_pos,
        COALESCE(refunds.refund_count, 0) refund_count, refunds.last_correction_id,
        COALESCE(drawer.cash_in, 0) cash_in, COALESCE(drawer.cash_out, 0) cash_out,
        COALESCE(drawer.cash_movement_effect, 0) cash_movement_effect,
        COALESCE(drawer.movement_count, 0) movement_count, drawer.last_movement_id,
        {snapshot_select}, decisions.action last_action, decisions.responsible_name
    FROM calendar LEFT JOIN collections USING (branch_id, business_date) LEFT JOIN gross USING (branch_id, business_date)
    LEFT JOIN refunds USING (branch_id, business_date) LEFT JOIN drawer USING (branch_id, business_date)
    LEFT JOIN latest USING (branch_id, business_date)
    LEFT JOIN decisions ON decisions.reconciliation_id = latest.id
    ORDER BY calendar.business_date, calendar.branch_id LIMIT 5001;'''
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (start_date, end_date, start, end, branch_id))
            names = [column.name for column in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    if branch_id is not None and not rows:
        raise HTTPException(status_code=404, detail='Branch not found')
    if len(rows) > 5000:
        raise HTTPException(status_code=422, detail='Report is too large; choose fewer dates or one branch')
    return format_financial_report(rows, keys, start_date, end_date, branch_id, lagos)


def format_financial_report(rows, snapshot_keys, start_date, end_date, branch_id, lagos):
    result = []
    money_keys = ('gross_credit', 'debt_reduced', 'repaid_cash', 'repaid_pos', 'gross_cash', 'gross_pos', 'unclassified_amount', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out', 'cash_movement_effect')
    compare_money = ('expected_cash', 'expected_pos', 'gross_cash', 'gross_pos', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out', 'cash_movement_effect')
    for row in rows:
        current = {key: format(row[key], '.2f') for key in money_keys}
        current.update(sales_count=row['sales_count'], refund_count=row['refund_count'],
                       unclassified_count=row['unclassified_count'], last_sale_id=row['last_sale_id'],
                       last_correction_id=row['last_correction_id'],
                       movement_count=row['movement_count'], last_movement_id=row['last_movement_id'],
                       repayment_count=row['repayment_count'], last_repayment_id=row['last_repayment_id'],
                       expected_cash=format(row['gross_cash'] - row['refund_cash'] + row['cash_movement_effect'] + row['repaid_cash'], '.2f'),
                       expected_pos=format(row['gross_pos'] - row['refund_pos'] + row['repaid_pos'], '.2f'))
        snapshot = {key: row[f'snapshot_{key}'] for key in snapshot_keys}
        exists = snapshot['id'] is not None
        if exists:
            for key in compare_money:
                snapshot[key] = format(snapshot[key], '.2f')
        stale = exists and reconciliation_stale(snapshot, current)
        balanced = exists and snapshot['cash_difference'] == 0 and snapshot['pos_difference'] == 0
        resolution = ('out_of_date' if stale else discrepancy_action_state(row['last_action']) if row['last_action']
                      else 'balanced' if balanced else 'open' if exists else 'not_counted')
        active = bool(row['sales_count'] or row['refund_count'] or row['movement_count'] or row['repayment_count'] or exists)
        status = ('out_of_date' if stale else 'reviewed' if exists and snapshot['reviewed_at'] else 'submitted' if exists
                  else 'no_submission' if active else 'no_activity')
        result.append(dict(branch_id=row['branch_id'], branch_name=row['branch_name'], business_date=row['business_date'].isoformat(),
            **current, net_sales=format(row['gross_cash'] + row['gross_pos'] + row['unclassified_amount']
                + row['gross_credit'] - row['debt_reduced'] - row['refund_cash'] - row['refund_pos'], '.2f'), reconciliation_id=snapshot['id'],
            reconciliation_status=status, resolution_state=resolution, responsible_name=row['responsible_name'],
            cash_difference=format(snapshot['cash_difference'], '.2f') if exists else None,
            pos_difference=format(snapshot['pos_difference'], '.2f') if exists else None,
            unresolved=bool(exists and not balanced and resolution != 'resolved')))
    totals = {key: format(sum((Decimal(row[key]) for row in result), Decimal('0')), '.2f')
              for key in (*money_keys, 'expected_cash', 'expected_pos', 'net_sales')}
    totals.update(gross_sales=format(Decimal(totals['gross_cash']) + Decimal(totals['gross_pos'])
                                    + Decimal(totals['unclassified_amount']) + Decimal(totals['gross_credit']), '.2f'),
                  sales_count=sum(row['sales_count'] for row in result), refund_count=sum(row['refund_count'] for row in result),
                  unresolved_days=sum(row['unresolved'] for row in result),
                  unreconciled_days=sum(row['reconciliation_status'] in ('no_submission', 'out_of_date') for row in result),
                  awaiting_review_days=sum(row['reconciliation_status'] == 'submitted' for row in result))
    return dict(start_date=start_date.isoformat(), end_date=end_date.isoformat(), branch_id=branch_id,
                generated_at=datetime.now(lagos).isoformat(), timezone='Africa/Lagos', currency='NGN', totals=totals, rows=result)


@app.get('/reports/financial')
def financial_report(start_date: BusinessDate = Query(), end_date: BusinessDate = Query(),
                      branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                      user: dict = Depends(require_stock_manager)):
    return financial_report_data(start_date, end_date, branch_id)


@app.get('/reports/financial.csv')
def export_financial_report(start_date: BusinessDate = Query(), end_date: BusinessDate = Query(),
                             branch_id: int | None = Query(default=None, gt=0, le=2147483647),
                             user: dict = Depends(require_stock_manager)):
    report = financial_report_data(start_date, end_date, branch_id)
    columns = ('gross_credit', 'debt_reduced', 'repaid_cash', 'repaid_pos', 'business_date', 'branch_id', 'branch_name', 'sales_count', 'gross_cash', 'gross_pos',
        'unclassified_count', 'unclassified_amount', 'refund_cash', 'refund_pos', 'cash_in', 'cash_out',
        'cash_movement_effect', 'expected_cash', 'expected_pos', 'net_sales',
        'reconciliation_status', 'cash_difference', 'pos_difference', 'resolution_state', 'responsible_name')
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow((*columns, 'generated_at_lagos'))
    for row in report['rows']:
        values = []
        for key in columns:
            value = row[key] if row[key] is not None else ''
            # Escape formulas in text, preserving signed Decimal financial amounts.
            if key in ('branch_name', 'responsible_name') and str(value).lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + str(value)
            values.append(value)
        writer.writerow((*values, report['generated_at']))
    return Response('\ufeff' + buffer.getvalue(), media_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': f'attachment; filename="FAS-financial-{start_date}-{end_date}.csv"', 'Cache-Control': 'no-store'})


# Serve only the public frontend folder, never backend configuration or credentials.
app.mount('/app', StaticFiles(directory=FilePath(__file__).resolve().parents[1] / 'frontend', html=True), name='frontend')
