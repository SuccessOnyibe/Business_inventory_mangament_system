"""Stock transfers: extracted workflows; URLs and transactions are unchanged."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Query
from psycopg.errors import NumericValueOutOfRange
from pydantic import BaseModel, Field

from auth import get_current_user, require_stock_manager, scoped_branch
from database import db_connection
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Stock Transfers'])


class StockTransferCreate(BaseModel):
    source_branch_id: int = Field(strict=True, gt=0, le=2147483647)
    destination_branch_id: int = Field(strict=True, gt=0, le=2147483647)
    product_id: int = Field(strict=True, gt=0, le=2147483647)
    quantity: int = Field(strict=True, gt=0, le=2147483647)
    notes: str | None = None


@router.post("/stock-transfers", status_code=201)
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


@router.get("/stock-transfers")
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


@router.post("/stock-transfers/{transfer_id}/confirm")
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
