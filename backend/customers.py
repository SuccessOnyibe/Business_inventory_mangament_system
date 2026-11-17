"""Customers: extracted workflows; URLs and transactions are unchanged."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Path, Query
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import get_current_user, scoped_branch
from database import db_connection
from stock_requests import begin_stock_request, finish_stock_request

# Group related endpoints without changing their existing paths.
router = APIRouter(tags=['Customers'])


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


CUSTOMER_COLUMNS = 'id, branch_id, name, phone, notes, is_active, version, created_by, updated_by, created_at, updated_at'


def customer_response(row):
    record = dict(zip(CUSTOMER_COLUMNS.split(', '), row))
    for key in ('created_at', 'updated_at'):
        record[key] = record[key].isoformat()
    return record


@router.get('/customers')
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


@router.post('/customers', status_code=201)
def create_customer(request: CustomerCreate, idempotency_key: UUID = Header(),
                    user: dict = Depends(get_current_user)):
    scoped_branch(user, request.branch_id)
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


@router.post('/customers/{customer_id}/update')
def update_customer(request: CustomerUpdate, customer_id: int = Path(gt=0, le=2147483647),
                    idempotency_key: UUID = Header(), user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                # Check branch access before replaying a saved response as well as editing.
                cursor.execute('SELECT branch_id, is_active FROM customers WHERE id = %s;', (customer_id,))
                owner = cursor.fetchone()
                if owner is None:
                    raise HTTPException(status_code=404, detail='Customer not found')
                scoped_branch(user, owner[0])
                if user['role'] == 'salesperson' and request.is_active != owner[1]:
                    raise HTTPException(status_code=403, detail='Only Admin/Manager can change customer status')
                payload = {'customer_id':customer_id, **request.model_dump()}
                previous = begin_stock_request(cursor, idempotency_key, 'customer_update', payload, user['id'])
                if previous is not None:
                    return previous
                cursor.execute('SELECT version FROM customers WHERE id = %s FOR UPDATE;', (customer_id,))
                found = cursor.fetchone()
                if found is None:
                    raise HTTPException(status_code=404, detail='Customer not found')
                # Reject a stale form instead of overwriting another staff member's edit.
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
