"""Local account provisioning: python create_user.py USERNAME --role admin"""
import argparse
import getpass

from dotenv import load_dotenv
from pathlib import Path
from pydantic import BaseModel, Field, SecretStr, ValidationError
from psycopg.errors import UniqueViolation

from auth import hash_password
from database import db_connection


class NewUser(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    password: SecretStr = Field(min_length=12, max_length=128)
    branch_id: int | None = Field(default=None, strict=True, gt=0, le=2147483647)


def main():
    parser = argparse.ArgumentParser(description="Create an inventory account locally")
    parser.add_argument("username")
    parser.add_argument("--role", required=True, choices=("admin", "manager", "salesperson"))
    parser.add_argument("--branch-id", type=int, help="Required assigned branch for a Salesperson")
    args = parser.parse_args()
    if args.role == 'salesperson' and args.branch_id is None:
        parser.error("Salesperson requires --branch-id")
    # Passwords are entered privately, never passed as shell arguments or printed.
    password = getpass.getpass("Password (12-128 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.exit(1, "Passwords do not match.\n")
    try:
        user = NewUser(username=args.username, password=password, branch_id=args.branch_id)
    except ValidationError:
        parser.exit(1, "Use a lowercase username (3-50 letters/numbers/._-) and a 12-128 character password.\n")
    load_dotenv(Path(__file__).resolve().parent / ".env")
    try:
        with db_connection() as connection:
            with connection.transaction():
                if user.branch_id is not None:
                    branch = connection.execute('SELECT id FROM branches WHERE id = %s FOR KEY SHARE;',
                                                (user.branch_id,)).fetchone()
                    if branch is None:
                        parser.exit(1, 'Branch not found.\n')
                connection.execute(
                    "INSERT INTO users (username, password_hash, role, branch_id) VALUES (%s, %s, %s, %s);",
                    (user.username, hash_password(user.password.get_secret_value()), args.role, user.branch_id)
                )
    except UniqueViolation:
        parser.exit(1, "Username already exists.\n")
    print("Created account:", user.username, "with role", args.role)


if __name__ == "__main__":
    main()
