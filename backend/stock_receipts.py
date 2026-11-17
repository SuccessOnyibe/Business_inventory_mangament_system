"""Stock receipts: extracted workflows; URLs and transactions are unchanged."""

from datetime import date as BusinessDate, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from psycopg.errors import NumericValueOutOfRange
from pydantic import BaseModel, Field, field_validator

from auth import get_current_user, require_stock_manager, scoped_branch
from database import db_connection
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Stock Receipts'])


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


@router.post("/stock-receipts", status_code=201)
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


@router.get('/stock-receipts')
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
