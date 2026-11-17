"""Admin-only account management; never expose password hashes or session tokens."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from psycopg.errors import UniqueViolation

from auth import hash_password, require_admin
from database import db_connection

router = APIRouter(prefix="/users", tags=["Account administration"])
Role = Literal["admin", "manager", "salesperson"]


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    password: SecretStr = Field(min_length=12, max_length=128)
    role: Role
    branch_id: int | None = Field(default=None, strict=True, gt=0, le=2147483647)


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role | None = None
    is_active: bool | None = Field(default=None, strict=True)
    branch_id: int | None = Field(default=None, strict=True, gt=0, le=2147483647)


def account_response(row):
    return dict(zip(("id", "username", "role", "is_active", "branch_id"), row))


def check_branch(cursor, role, branch_id, active=True):
    if active and role == "salesperson" and branch_id is None:
        raise HTTPException(status_code=422, detail="Salesperson requires an assigned branch")
    if branch_id is not None:
        cursor.execute("SELECT id FROM branches WHERE id = %s FOR KEY SHARE;", (branch_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="Branch not found")


def lock_accounts(cursor, actor_id):
    # Serialize account changes before counting Admins. Two simultaneous requests
    # must not both decide that it is safe to remove the other last Admin.
    cursor.execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE;")
    cursor.execute("SELECT role, is_active FROM users WHERE id = %s;", (actor_id,))
    actor = cursor.fetchone()
    # Recheck after the lock: another Admin may have just removed this permission.
    if actor is None or actor[0] != "admin" or not actor[1]:
        raise HTTPException(status_code=403, detail="Active Admin permission required")


@router.get("")
def list_accounts(limit: int = Query(default=100, ge=1, le=500),
                  offset: int = Query(default=0, ge=0, le=2147483647),
                  user: dict = Depends(require_admin)):
    with db_connection() as connection:
        rows = connection.execute("SELECT id, username, role, is_active, branch_id FROM users ORDER BY id LIMIT %s OFFSET %s;",
                                  (limit, offset)).fetchall()
    return [account_response(row) for row in rows]


@router.post("", status_code=201)
def create_account(account: AccountCreate, user: dict = Depends(require_admin)):
    password_hash = hash_password(account.password.get_secret_value())
    try:
        with db_connection() as connection:
            with connection.transaction():
                with connection.cursor() as cursor:
                    lock_accounts(cursor, user["id"])
                    check_branch(cursor, account.role, account.branch_id)
                    cursor.execute(
                        """
                        INSERT INTO users (username, password_hash, role, branch_id) VALUES (%s, %s, %s, %s)
                        RETURNING id, username, role, is_active, branch_id;
                        """, (account.username, password_hash, account.role, account.branch_id)
                    )
                    result = account_response(cursor.fetchone())
    except UniqueViolation:
        raise HTTPException(status_code=409, detail="Username already exists") from None
    return result


@router.patch("/{user_id}")
def update_account(account: AccountUpdate, user_id: int = Path(gt=0, le=2147483647),
                   user: dict = Depends(require_admin)):
    changes = account.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields provided for update")
    if any(value is None for key, value in changes.items() if key != "branch_id"):
        raise HTTPException(status_code=422, detail="Account fields cannot be null")
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                lock_accounts(cursor, user["id"])
                cursor.execute("SELECT id, username, role, is_active, branch_id FROM users WHERE id = %s;", (user_id,))
                target = cursor.fetchone()
                if target is None:
                    raise HTTPException(status_code=404, detail="User not found")
                role = changes.get("role", target[2])
                active = changes.get("is_active", target[3])
                branch_id = changes.get("branch_id", target[4])
                check_branch(cursor, role, branch_id, active)
                if target[2] == "admin" and target[3] and (role != "admin" or not active):
                    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE;")
                    if cursor.fetchone()[0] <= 1:
                        raise HTTPException(status_code=409, detail="Cannot remove the last active Admin")
                cursor.execute(
                    "UPDATE users SET role = %s, is_active = %s, branch_id = %s WHERE id = %s RETURNING id, username, role, is_active, branch_id;",
                    (role, active, branch_id, user_id)
                )
                result = account_response(cursor.fetchone())
                if not active:
                    # Reactivating an account must not revive tokens held before deactivation.
                    cursor.execute("UPDATE user_sessions SET revoked_at = NOW() WHERE user_id = %s AND revoked_at IS NULL;",
                                   (user_id,))
    return result
