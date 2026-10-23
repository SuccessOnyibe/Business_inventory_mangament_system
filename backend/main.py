from fastapi import FastAPI
from database import db_connection

app = FastAPI(title="Family Business Inventory API")


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