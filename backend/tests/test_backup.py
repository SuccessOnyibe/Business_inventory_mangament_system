"""Backups must be consistent, private, and incapable of restoring over live data."""
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import backup


class BackupTests(unittest.TestCase):
    def test_corrupt_archive_is_rejected_before_any_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'database.dump').write_bytes(b'changed')
            (folder / 'manifest.json').write_text(json.dumps({'format_version':1,'archive_sha256':'wrong'}))
            with patch.object(backup.psycopg, 'connect') as connect:
                with self.assertRaises(ValueError):
                    backup.verify_backup(folder)
                connect.assert_not_called()

    def test_child_credentials_are_not_in_command_arguments(self):
        settings = dict(host='localhost',port='5432',dbname='inventory',user='operator',password='test-secret')
        with patch.object(backup.subprocess, 'run') as run:
            run.return_value.returncode = 0
            backup.run_postgres('pg_dump', ['--format=custom'], settings)
        arguments, keywords = run.call_args
        self.assertNotIn('test-secret', str(arguments))
        self.assertEqual(keywords['env']['PGPASSWORD'], 'test-secret')
        self.assertNotIn('shell', keywords)

    def test_failure_does_not_echo_tool_output(self):
        with patch.object(backup.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = 'private connection details'
            with self.assertRaises(RuntimeError) as error:
                backup.run_postgres('pg_dump', [], dict(host='x',port='1',user='x',dbname='x'))
        self.assertNotIn('private', str(error.exception))

    def test_restore_failure_drops_only_the_database_it_created(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'database.dump').write_bytes(b'fixture')
            (folder / 'manifest.json').write_text(json.dumps({'format_version':1,
                'archive_sha256':backup.sha256_file(folder / 'database.dump')}))
            admin = MagicMock()
            admin.execute.return_value.fetchone.return_value = ('55439',)
            with patch.object(backup.psycopg, 'connect') as connect, \
                 patch.object(backup, 'postgres_tool', return_value='pg_restore'), \
                 patch.object(backup, 'run_postgres', side_effect=RuntimeError('failed')):
                connect.return_value.__enter__.return_value = admin
                with self.assertRaises(RuntimeError):
                    backup.verify_backup(folder)
            settings = connect.call_args.kwargs
            self.assertEqual((settings['host'],settings['port'],settings['user']), ('127.0.0.1',55439,'inventory_test'))
            created = admin.execute.call_args_list[1].args[0]
            dropped = admin.execute.call_args_list[2].args[0]
            name = re.search(r'"(inventory_restore_test_[a-f0-9]{32})"', created.as_string()).group(1)
            self.assertEqual(dropped.as_string(), f'DROP DATABASE "{name}"')


@unittest.skipUnless(os.getenv('RUN_BACKUP_TESTS') == '1', 'Requires isolated UI fixture and PostgreSQL tools')
class BackupIntegrationTests(unittest.TestCase):
    def test_snapshot_dump_and_restore_preserve_fixture(self):
        settings = backup.database_settings()
        self.assertEqual(settings['host'], '127.0.0.1')
        self.assertEqual(settings['port'], '55439')
        self.assertTrue(settings['dbname'].startswith('inventory_ui_test_'))
        with tempfile.TemporaryDirectory() as directory:
            original_counts = backup.table_counts
            inserted = []

            def concurrent_change(connection):
                if not inserted:
                    # Commit a row AFTER snapshot export but BEFORE counting.
                    # A READ COMMITTED implementation would now count the new
                    # branch even though pg_dump cannot see it in its snapshot.
                    with backup.psycopg.connect(**settings) as writer:
                        inserted.append(writer.execute("INSERT INTO branches (name, type) VALUES ('Concurrent backup test', 'General') RETURNING id").fetchone()[0])
                return original_counts(connection)

            try:
                with patch.object(backup, 'table_counts', side_effect=concurrent_change):
                    folder = backup.create_backup(directory, settings)
                    manifest = backup.verify_backup(folder)
                self.assertEqual(manifest['table_counts']['branches'], 2)
            finally:
                if inserted:
                    with backup.psycopg.connect(**settings) as writer:
                        writer.execute("DELETE FROM branches WHERE id = %s AND name = 'Concurrent backup test'", (inserted[0],))
            self.assertEqual(manifest['table_counts']['inventory'], 1)
            self.assertEqual(manifest['table_counts']['users'], 2)
            self.assertEqual(manifest['table_counts']['cash_movements'], 0)
            self.assertFalse((folder / 'database.dump.partial').exists())
            # A second run never overwrites the first successful backup.
            other = backup.create_backup(directory, settings)
            self.assertNotEqual(other, folder)
            with backup.psycopg.connect(**settings) as connection:
                remaining = connection.execute("SELECT datname FROM pg_database WHERE datname LIKE 'inventory_restore_test_%'").fetchall()
                self.assertEqual(remaining, [])
                self.assertEqual(connection.execute('SELECT quantity FROM inventory').fetchone()[0], 1000)


if __name__ == '__main__':
    unittest.main()
