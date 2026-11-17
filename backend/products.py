"""Products: extracted workflows; URLs and transactions are unchanged."""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user, require_stock_manager
from database import db_connection

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Products'])


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


class ProductUpdate(ProductBarcode):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=150)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    base_unit: str | None = Field(default=None, min_length=1, max_length=30)
    is_active: bool | None = None
    selling_price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    max_discount_percent: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)


def product_response(row):
    return {
        'id': row[0], 'name': row[1], 'category': row[2], 'base_unit': row[3],
        'is_active': row[4],
        # Money is returned as decimal text, avoiding floating-point rounding.
        'selling_price': format(row[5], '.2f') if row[5] is not None else None,
        'max_discount_percent': format(row[6], '.2f'), 'barcode':row[7]
    }


@router.get("/products")
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


@router.post('/products', status_code=201)
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


@router.patch('/products/{product_id}')
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
