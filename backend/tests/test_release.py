"""Public readiness must fail closed without exposing database connection errors."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import main
import scheduled_backup


class ReleaseTests(unittest.TestCase):
    def test_liveness_requires_no_database_and_assets_have_security_headers(self):
        with patch.object(main,'db_connection') as connect:
            client=TestClient(main.app)
            self.assertEqual(client.get('/health').json(),{'status':'ok'})
            response=client.get('/app/')
            self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertIn("frame-ancestors 'none'",response.headers['content-security-policy'])
            connect.assert_not_called()

    def test_unready_response_hides_connection_details(self):
        with patch.object(main,'db_connection',side_effect=RuntimeError('private database password')):
            response=TestClient(main.app).get('/health/ready')
            self.assertEqual(response.status_code,503)
            self.assertNotIn('private',response.text)

    def test_failed_scheduled_backup_records_failure_without_secret(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(scheduled_backup.backup,'database_settings',side_effect=ValueError('private secret')):
            result=scheduled_backup.run(directory)
            self.assertFalse(result['success'])
            status=(Path(directory)/'last-backup-status.json').read_text()
            self.assertNotIn('private',status)
            self.assertIn('finished_at',status)
