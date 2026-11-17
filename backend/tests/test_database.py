"""Connection selection must preserve secrets, TLS options and isolated test targets."""
import os
import unittest
from unittest.mock import Mock, patch

import database


class DatabaseConnectionTests(unittest.TestCase):
    def test_process_url_wins_and_is_passed_without_rewriting(self):
        url = 'postgresql://test.invalid/example?sslmode=require&channel_binding=require'
        with patch.dict(os.environ, {'DATABASE_URL': url, 'DB_HOST': 'local'}, clear=True), \
             patch.object(database, 'dotenv_values') as dotenv, \
             patch.object(database.psycopg, 'connect') as connect:
            database.get_connection()
            connect.assert_called_once_with(url, connect_timeout=15)
            dotenv.assert_not_called()

    def test_explicit_test_fields_do_not_load_neon_url(self):
        fields = {'DB_HOST': '127.0.0.1', 'DB_PORT': '55439', 'DB_NAME': 'isolated',
                  'DB_USER': 'tester', 'DB_PASSWORD': ''}
        with patch.dict(os.environ, fields, clear=True), \
             patch.object(database, 'dotenv_values', return_value={}) as dotenv, \
             patch.object(database.psycopg, 'connect') as connect:
            database.get_connection()
            dotenv.assert_called_once_with(database.ROOT / 'backend' / '.env')
            connect.assert_called_once_with(host='127.0.0.1', port='55439', dbname='isolated',
                                            user='tester', password='', connect_timeout=5)

    def test_private_local_url_is_used_without_exporting_it(self):
        url = 'postgresql://test.invalid/example?sslmode=require'
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(database, 'dotenv_values', return_value={'DATABASE_URL': url}), \
             patch.object(database.psycopg, 'connect') as connect:
            database.get_connection()
            connect.assert_called_once_with(url, connect_timeout=15)
            self.assertNotIn('DATABASE_URL', os.environ)

    def test_original_backend_env_is_used_when_no_url_exists(self):
        local = {'DB_HOST': 'original', 'DB_NAME': 'inventory', 'DB_USER': 'owner'}
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(database, 'dotenv_values', side_effect=[{}, local]), \
             patch.object(database.psycopg, 'connect') as connect:
            database.get_connection()
            self.assertEqual(connect.call_args.kwargs['host'], 'original')
            self.assertEqual(connect.call_args.kwargs['dbname'], 'inventory')

    def test_failed_neon_connection_never_falls_back_to_another_database(self):
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test.invalid/example'}, clear=True), \
             patch.object(database, 'dotenv_values') as dotenv, \
             patch.object(database.psycopg, 'connect', side_effect=RuntimeError('failed')) as connect:
            with self.assertRaises(RuntimeError):
                database.get_connection()
            self.assertEqual(connect.call_count, 1)
            dotenv.assert_not_called()

    def test_connection_is_closed_when_a_workflow_raises(self):
        connection = Mock()
        with patch.object(database, 'get_connection', return_value=connection):
            with self.assertRaises(ValueError):
                with database.db_connection():
                    raise ValueError('failed workflow')
        connection.close.assert_called_once()
        connection.commit.assert_not_called()
