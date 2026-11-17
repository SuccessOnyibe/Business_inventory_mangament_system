"""Create a consistent PostgreSQL archive; verify only on our disposable test server.

This is an operator command, never a public API endpoint. Passwords stay out of
command arguments and the manifest. See docs/BACKUP_AND_RECOVERY.md.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from dotenv import load_dotenv
import psycopg
from psycopg import sql


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = {'branches', 'products', 'inventory', 'stock_movements', 'users', 'sales',
                   'daily_reconciliations', 'cash_movement_requests', 'cash_movements'}


def database_settings():
    # Find .env relative to this file, even when launched from another directory.
    load_dotenv(ROOT / 'backend' / '.env')
    values = {name: os.getenv('DB_' + name.upper()) for name in ('host', 'port', 'user', 'password')}
    values['dbname'] = os.getenv('DB_NAME')
    if any(not values[key] for key in ('host', 'port', 'user', 'dbname')):
        raise ValueError('DB_HOST, DB_PORT, DB_USER and DB_NAME must be configured')
    return values


def postgres_tool(name, pg_bin=None):
    candidate = Path(pg_bin) / (name + '.exe' if os.name == 'nt' else name) if pg_bin else None
    found = str(candidate) if candidate and candidate.is_file() else shutil.which(name)
    if not found and not pg_bin and os.name == 'nt':
        candidate = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'PostgreSQL/17/bin' / (name + '.exe')
        found = str(candidate) if candidate.is_file() else None
    if not found:
        raise ValueError(f'{name} not found. Supply --pg-bin with your PostgreSQL bin directory')
    return found


def run_postgres(tool, arguments, settings):
    # libpq reads credentials from this child's environment, not the process list.
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith('PG')}
    environment.update({
        'PGHOST': settings['host'], 'PGPORT': str(settings['port']), 'PGUSER': settings['user'],
        'PGPASSWORD': settings.get('password') or '', 'PGDATABASE': settings['dbname'],
        'PGCONNECT_TIMEOUT': '10',
    })
    result = subprocess.run([tool, '--no-password', *arguments], env=environment,
                            capture_output=True, text=True, timeout=600, check=False)
    if result.returncode:
        # Do not echo connection details, archive contents, or secrets into logs.
        raise RuntimeError(f'{Path(tool).stem} failed (exit {result.returncode}); check tool version, permissions and database availability')


def table_counts(connection):
    tables = connection.execute("""SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY c.relname""").fetchall()
    names = {row[0] for row in tables}
    if not REQUIRED_TABLES.issubset(names):
        raise ValueError('Expected inventory application tables are missing')
    # Identifiers cannot be bound as values; Identifier safely quotes table names.
    return {name: connection.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(name))).fetchone()[0]
            for (name,) in tables}


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def create_backup(output, settings, pg_bin=None):
    tool = postgres_tool('pg_dump', pg_bin)
    folder = Path(output).resolve() / ('FAS-backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex)
    folder.mkdir(parents=True, mode=0o700)
    partial = folder / 'database.dump.partial'
    archive = folder / 'database.dump'
    with psycopg.connect(**settings, connect_timeout=10) as connection:
        # Count rows and pg_dump see exactly the same committed database state,
        # even if another staff member makes a sale while the backup runs.
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = connection.execute('SELECT pg_export_snapshot()').fetchone()[0]
        counts = table_counts(connection)
        run_postgres(tool, ['--format=custom', '--no-owner', '--no-privileges',
                           '--snapshot=' + snapshot, '--file=' + str(partial)], settings)
        version = connection.execute('SHOW server_version').fetchone()[0]
    partial.rename(archive)
    manifest = {'format_version': 1, 'business': 'FESTY AGRIC SERVICES',
                'created_at': datetime.now(timezone.utc).isoformat(), 'postgres_version': version,
                'archive_sha256': sha256_file(archive), 'table_counts': counts}
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return folder


def verify_backup(folder, pg_bin=None):
    folder = Path(folder).resolve()
    archive = folder / 'database.dump'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format_version') != 1 or sha256_file(archive) != manifest.get('archive_sha256'):
        raise ValueError('Backup checksum or manifest is invalid; no restore attempted')
    tool = postgres_tool('pg_restore', pg_bin)
    # Deliberately no configurable restore target: this command cannot restore
    # over the working database. The test cluster must be started separately.
    settings = dict(host='127.0.0.1', port=55439, dbname='postgres', user='inventory_test', password='')
    database_name = 'inventory_restore_test_' + uuid.uuid4().hex
    with psycopg.connect(**settings, autocommit=True, connect_timeout=10) as admin:
        if admin.execute('SHOW port').fetchone()[0] != '55439':
            raise ValueError('Restore verification requires the dedicated test server')
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database_name)))
        try:
            target = {**settings, 'dbname': database_name}
            run_postgres(tool, ['--exit-on-error', '--single-transaction', '--no-owner', '--no-privileges',
                               '--dbname=' + database_name, str(archive)], target)
            with psycopg.connect(**target, connect_timeout=10) as restored:
                if table_counts(restored) != manifest['table_counts']:
                    raise ValueError('Restored row counts do not match the backup snapshot')
                # Every restored CHECK/FK should be validated, not silently skipped.
                if restored.execute("SELECT count(*) FROM pg_constraint WHERE NOT convalidated AND connamespace = 'public'::regnamespace").fetchone()[0]:
                    raise ValueError('Restored database contains unvalidated constraints')
        finally:
            # Drop only the random database created by this invocation. No CASCADE,
            # --clean, or deletion of an operator-supplied database is available.
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database_name)))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', help='PostgreSQL bin directory (pg_dump and pg_restore)')
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create', help='Read the configured database and write a new backup folder')
    create.add_argument('--output', type=Path, default=ROOT / 'backups')
    verify = commands.add_parser('verify', help='Restore a trusted backup on the disposable server only')
    verify.add_argument('folder', type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == 'create':
            print('Backup created: ' + str(create_backup(arguments.output, database_settings(), arguments.pg_bin)))
            print('Keep database.dump and manifest.json together. Run verify before relying on this backup.')
        else:
            verify_backup(arguments.folder, arguments.pg_bin)
            print('Restore verified: checksum, application table counts and validated constraints match. Test database removed.')
    except (ValueError, RuntimeError, OSError, psycopg.Error, subprocess.TimeoutExpired) as error:
        # A database exception may include connection information; keep it private.
        parser.exit(1, f'Backup operation failed ({type(error).__name__}). Check configuration, trusted archive, tools and server availability.\n')


if __name__ == '__main__':
    main()
