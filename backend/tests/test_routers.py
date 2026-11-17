"""Routing boundaries and API discovery must remain intact after extraction."""
import importlib
import unittest

from fastapi import APIRouter
from fastapi.testclient import TestClient
import main


WORKFLOWS = {
    'products': '/products', 'inventory': '/inventory',
    'stock_receipts': '/stock-receipts', 'stock_transfers': '/stock-transfers',
    'customers': '/customers', 'sales': '/checkouts',
    'sale_corrections': '/sale-corrections', 'credit': '/credit-repayments',
    'reconciliations': '/reconciliations', 'stock_adjustments': '/stock-adjustments',
    'reports': '/reports/financial',
}


class RouterTests(unittest.TestCase):
    def test_workflow_routers_registered_once_with_local_handlers(self):
        # Inspect routers directly: FastAPI may represent included routers lazily.
        registered = set()
        paths = main.app.openapi()['paths']
        for module_name, primary_path in WORKFLOWS.items():
            with self.subTest(workflow=module_name):
                module = importlib.import_module(module_name)
                self.assertIsInstance(module.router, APIRouter)
                self.assertIn(primary_path, paths)
                for route in module.router.routes:
                    self.assertEqual(route.endpoint.__module__, module_name)
                    for method in route.methods:
                        key = (method.lower(), route.path)
                        self.assertNotIn(key, registered)
                        registered.add(key)
                        self.assertEqual(paths[route.path][method.lower()]['tags'], route.tags)
        # Authentication and account administration stay in their existing routers.
        self.assertIn('/auth/login', paths)
        self.assertIn('/users', paths)
        self.assertFalse(hasattr(main, 'create_checkout'))
        self.assertFalse(hasattr(main, 'receive_stock'))

    def test_openapi_discovery_does_not_connect_to_database(self):
        from test_stock import patch_workflow_connections
        with patch_workflow_connections() as connection:
            response = TestClient(main.app).get('/openapi.json')
            self.assertEqual(response.status_code, 200)
            connection.assert_not_called()
