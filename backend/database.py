"""Database connections for hosted PostgreSQL and the existing local setup."""
from contextlib import contextmanager
import os
from pathlib import Path

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DB_FIELDS = {'host': 'DB_HOST', 'port': 'DB_PORT', 'dbname': 'DB_NAME',
             'user': 'DB_USER', 'password': 'DB_PASSWORD'}


def get_connection():
    # A host-provided URL is authoritative. Keep its TLS and pooling options intact.
    database_url = os.getenv('DATABASE_URL')
    explicit_fields = any(name in os.environ for name in DB_FIELDS.values())
    if not database_url and not explicit_fields:
        # Read, rather than export, secrets: importing this module never changes env.
        database_url = dotenv_values(ROOT / '.env.local').get('DATABASE_URL')
    if database_url:
        return psycopg.connect(database_url, connect_timeout=15)

    # Explicit DB_* variables keep Render's split settings and isolated tests working.
    # The original local credentials are still available as the fallback.
    local = dotenv_values(ROOT / 'backend' / '.env')
    settings = {argument: os.environ.get(name, local.get(name))
                for argument, name in DB_FIELDS.items()}
    return psycopg.connect(**settings, connect_timeout=5)


@contextmanager
def db_connection():
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()
