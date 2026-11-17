"""Password verification, expiring bearer sessions, and role checks."""
import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, SecretStr

from database import db_connection

router = APIRouter(prefix="/auth", tags=["Authentication"])
bearer = HTTPBearer(auto_error=False)
SESSION_SECONDS = 8 * 60 * 60
LOGIN_LIMIT = 5
LOGIN_WINDOW_SECONDS = 15 * 60


def hash_password(password):
    # A random salt makes identical passwords produce different stored hashes.
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify_password(password, stored_hash):
    try:
        algorithm, salt, expected = stored_hash.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False


# Unknown accounts still perform the expensive password check, reducing timing clues.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    password: SecretStr = Field(min_length=1, max_length=128)


def unauthorized():
    return HTTPException(status_code=401, detail="Invalid credentials or expired session",
                         headers={"WWW-Authenticate": "Bearer"})


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    # Only a digest is stored: a database leak does not expose usable session tokens.
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT users.id, users.username, users.role, users.branch_id
                FROM user_sessions JOIN users ON users.id = user_sessions.user_id
                WHERE token_hash = %s AND revoked_at IS NULL
                  AND expires_at > NOW() AND users.is_active = TRUE;
                """, (token_hash,)
            )
            row = cursor.fetchone()
    if row is None:
        raise unauthorized()
    return {"id": row[0], "username": row[1], "role": row[2], "branch_id": row[3], "token_hash": token_hash}


def scoped_branch(user, requested_branch=None):
    """Force a Salesperson's reads to their assigned branch, never a client choice."""
    if user["role"] != "salesperson":
        return requested_branch
    assigned = user.get("branch_id")
    if assigned is None:
        raise HTTPException(status_code=403, detail="Ask an Admin to assign your branch")
    if requested_branch is not None and requested_branch != assigned:
        raise HTTPException(status_code=403, detail="Access is restricted to your assigned branch")
    return assigned


def require_stock_manager(user: dict = Depends(get_current_user)):
    # This central check is shared by product changes, receiving, and transfers.
    if user["role"] not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or Manager permission required")
    return user


def require_admin(user: dict = Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin permission required")
    return user


@router.post("/login")
def login(request: LoginRequest, response: Response):
    error = None
    with db_connection() as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                # Store counters in PostgreSQL, so all API workers share the limit.
                # Unknown usernames use the same flow to avoid revealing accounts.
                cursor.execute("INSERT INTO login_attempts (username) VALUES (%s) ON CONFLICT DO NOTHING;",
                               (request.username,))
                cursor.execute(
                    """
                    SELECT failures, locked_until > NOW(),
                           window_started_at <= NOW() - %s * INTERVAL '1 second',
                           CEIL(EXTRACT(EPOCH FROM (locked_until - NOW())))::integer
                    FROM login_attempts WHERE username = %s FOR UPDATE;
                    """, (LOGIN_WINDOW_SECONDS, request.username)
                )
                attempts = cursor.fetchone()
                if attempts[1]:
                    raise HTTPException(status_code=429, detail="Too many login attempts; try again later",
                                        headers={"Retry-After": str(max(1, attempts[3]))})
                if attempts[2]:
                    cursor.execute("UPDATE login_attempts SET failures = 0, window_started_at = NOW(), locked_until = NULL WHERE username = %s;",
                                   (request.username,))
                # Keep account status/password stable until the session is created.
                cursor.execute(
                    "SELECT id, password_hash, is_active FROM users WHERE username = %s FOR SHARE;",
                    (request.username,)
                )
                user = cursor.fetchone()
                valid = verify_password(request.password.get_secret_value(),
                                        user[1] if user else DUMMY_PASSWORD_HASH)
                if not valid or user is None or not user[2]:
                    cursor.execute(
                        """
                        UPDATE login_attempts SET failures = failures + 1,
                            locked_until = CASE WHEN failures + 1 >= %s
                                THEN NOW() + %s * INTERVAL '1 second' ELSE NULL END
                        WHERE username = %s;
                        """, (LOGIN_LIMIT, LOGIN_WINDOW_SECONDS, request.username)
                    )
                    error = unauthorized()
                else:
                    cursor.execute("UPDATE login_attempts SET failures = 0, window_started_at = NOW(), locked_until = NULL WHERE username = %s;",
                                   (request.username,))
                    token = secrets.token_urlsafe(32)
                    token_hash = hashlib.sha256(token.encode()).hexdigest()
                    cursor.execute(
                        """
                        INSERT INTO user_sessions (token_hash, user_id, expires_at)
                        VALUES (%s, %s, NOW() + %s * INTERVAL '1 second');
                        """, (token_hash, user[0], SESSION_SECONDS)
                    )
    # Raise AFTER committing: otherwise failed-login counters would roll back too.
    if error is not None:
        raise error
    response.headers["Cache-Control"] = "no-store"
    return {"access_token": token, "token_type": "bearer", "expires_in": SESSION_SECONDS}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    # Internal session digests are never included in API responses.
    return {key: user[key] for key in ("id", "username", "role", "branch_id")}


@router.post("/logout", status_code=204)
def logout(user: dict = Depends(get_current_user)):
    with db_connection() as connection:
        with connection.transaction():
            connection.execute("UPDATE user_sessions SET revoked_at = NOW() WHERE token_hash = %s;",
                               (user["token_hash"],))
