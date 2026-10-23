from fastapi import FastAPI
from database import get_connection

app = FastAPI(title="Family Business Inventory API")


@app.get("/")
def home():
    return {"message": "Family Inventory Management API is running"}
@app.get("/branches")
def get_branches():
    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name, type FROM branches ORDER BY id;")
            rows = cursor.fetchall()

        branches = [
            {"id": row[0], "name": row[1], "type": row[2]}
            for row in rows
        ]

        return branches

    finally:
        connection.close()