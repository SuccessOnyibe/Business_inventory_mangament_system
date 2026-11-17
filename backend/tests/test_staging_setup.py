"""Staging must be explicit, empty, atomic and separate from business data."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql
import yaml

from create_user import NewUser
from database import get_connection
import setup_staging


class StagingTargetTests(unittest.TestCase):
    def test_only_explicit_encrypted_direct_neon_staging_target_is_accepted(self):
        good = 'postgresql://tester:private@ep-example.eu.neon.tech/festy_staging?sslmode=require'
        self.assertEqual(setup_staging.staging_target(good)['dbname'], 'festy_staging')
        for bad in (good.replace('festy_staging', 'production'),
                    good.replace('ep-example.eu.neon.tech', 'localhost'),
                    good.replace('sslmode=require', 'sslmode=disable'),
                    good.replace('ep-example.', 'ep-example-pooler.'),
                    good + '&hostaddr=127.0.0.1'):
            with self.subTest(target_type=bad.split('?')[0].split('@')[-1]):
                with self.assertRaises(ValueError):
                    setup_staging.staging_target(bad)

    def test_invalid_target_never_opens_a_connection_or_echoes_the_secret(self):
        with patch.object(setup_staging.getpass, 'getpass', return_value='private-invalid-url'), \
             patch.object(setup_staging.psycopg, 'connect') as connect, \
             patch('builtins.print') as output:
            self.assertEqual(setup_staging.main(), 1)
            connect.assert_not_called()
            self.assertNotIn('private-invalid-url', str(output.call_args_list))

    def test_render_configuration_is_free_and_does_not_initialize_database_at_startup(self):
        config = yaml.safe_load((setup_staging.ROOT / 'render.yaml').read_text())
        self.assertNotIn('databases', config)
        service = config['services'][0]
        self.assertEqual(service['plan'], 'free')
        self.assertEqual(service['autoDeployTrigger'], 'off')
        self.assertNotIn('rootDir', service)
        self.assertEqual(service['healthCheckPath'], '/health')
        self.assertNotIn('setup_staging', service['startCommand'])
        self.assertIn('--workers 1', service['startCommand'])
        self.assertTrue((setup_staging.ROOT / '.python-version').is_file())


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'PostgreSQL tests are opt-in')
class StagingDatabaseTests(unittest.TestCase):
    def setUp(self):
        if os.getenv('DB_HOST') != '127.0.0.1' or os.getenv('DB_PORT') != '55439':
            self.skipTest('Staging setup tests require the disposable PostgreSQL server')
        self.name = 'inventory_staging_test_' + uuid.uuid4().hex
        admin = get_connection()
        admin.autocommit = True
        self.addCleanup(admin.close)
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.name)))
        # Cleanup only the uniquely named database this test just created.
        self.addCleanup(lambda: admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(self.name))))
        self.connection = psycopg.connect(admin.info.dsn, dbname=self.name)
        self.addCleanup(self.connection.close)
        self.account = NewUser(username='staging_admin', password='a private test password')

    def test_full_schema_and_sample_history_then_refuse_second_run(self):
        setup_staging.initialize_staging(self.connection, self.account)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM branches').fetchone()[0], 3)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM stock_movements').fetchone()[0], 3)
        self.assertEqual(self.connection.execute('SELECT SUM(quantity) FROM inventory').fetchone()[0], 30)
        self.assertIsNotNone(self.connection.execute("SELECT to_regclass('public.credit_repayments')").fetchone()[0])
        with self.assertRaises(ValueError):
            setup_staging.initialize_staging(self.connection, self.account)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)

    def test_failure_rolls_back_entire_schema_and_samples(self):
        with patch.object(setup_staging, 'hash_password', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                setup_staging.initialize_staging(self.connection, self.account)
        self.assertIsNone(self.connection.execute("SELECT to_regclass('public.users')").fetchone()[0])
        self.assertIsNone(self.connection.execute("SELECT to_regclass('public.branches')").fetchone()[0])

    def test_existing_table_is_preserved_and_setup_refused(self):
        self.connection.execute('CREATE TABLE sentinel (id INTEGER)')
        self.connection.execute('INSERT INTO sentinel VALUES (7)')
        self.connection.commit()
        with self.assertRaises(ValueError):
            setup_staging.initialize_staging(self.connection, self.account)
        self.assertEqual(self.connection.execute('SELECT id FROM sentinel').fetchall(), [(7,)])
        self.assertIsNone(self.connection.execute("SELECT to_regclass('public.products')").fetchone()[0])
