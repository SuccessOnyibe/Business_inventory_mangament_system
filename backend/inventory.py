"""Inventory: extracted workflows; URLs and transactions are unchanged."""

from fastapi import APIRouter, Depends, Query

from auth import get_current_user, scoped_branch
from database import db_connection

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Inventory'])


@router.get("/branches")
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


@router.get("/stock-movements")
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


@router.get("/inventory")
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
