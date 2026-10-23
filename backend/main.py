from database import db_connection
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Family Business Inventory API")

class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    category: str = Field(min_length=1, max_length=50)
    base_unit: str = Field(min_length=1, max_length=30)

class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    base_unit: str | None = Field(default=None, min_length=1, max_length=30)
    is_active: bool | None = None


@app.get("/")
def home():
    return {"message": "Family Inventory Management API is running"}
@app.get("/branches")
def get_branches():
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, type FROM branches ORDER BY id;"
            )
            rows = cursor.fetchall()

    branches = [
        {"id": row[0], "name": row[1], "type": row[2]}
        for row in rows
    ]

    return branches


@app.get("/products")
def get_products(active_only: bool = False):
    with db_connection() as connection:
        with connection.cursor() as cursor:
            if active_only:
                cursor.execute(
                    """
                    SELECT id, name, category, base_unit, is_active
                    FROM products
                    WHERE is_active = TRUE
                    ORDER BY id;
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT id, name, category, base_unit, is_active
                    FROM products
                    ORDER BY id;
                    """
                )

            rows = cursor.fetchall()

    products = [
        {
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "base_unit": row[3],
            "is_active": row[4]
        }
        for row in rows
    ]

    return products

@app.post("/products", status_code=201)
def create_product(product: ProductCreate):
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO products (name, category, base_unit)
                VALUES (%s, %s, %s)
                RETURNING id, name, category, base_unit, is_active;
                """,
                (product.name, product.category, product.base_unit)
            )

            row = cursor.fetchone()
        connection.commit()

    return {
        "id": row[0],
        "name": row[1],
        "category": row[2],
        "base_unit": row[3],
        "is_active": row[4]
    }

@app.patch("/products/{product_id}")
def update_product(product_id: int, product: ProductUpdate):

    updates = product.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="No fields provided for update"
        )

    if any(value is None for value in updates.values()):
        raise HTTPException(
            status_code=422,
            detail="Product fields cannot be null"
        )

    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE products
                SET
                    name = COALESCE(%s, name),
                    category = COALESCE(%s, category),
                    base_unit = COALESCE(%s, base_unit),
                    is_active = COALESCE(%s, is_active)
                WHERE id = %s
                RETURNING id, name, category, base_unit, is_active;
                """,
                (
                    updates.get("name"),
                    updates.get("category"),
                    updates.get("base_unit"),
                    updates.get("is_active"),
                    product_id
                )
            )

            row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Product not found"
            )

        connection.commit()

    return {
        "id": row[0],
        "name": row[1],
        "category": row[2],
        "base_unit": row[3],
        "is_active": row[4]
    }

@app.get("/inventory")
def get_inventory(branch_id: int | None = None):
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
    WHERE (%s IS NULL OR inventory.branch_id = %s)
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