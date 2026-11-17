"""Atomic multi-item purchases, receipt snapshots, and purchase-based reconciliation."""
import os
import unittest
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import main
import auth
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'PostgreSQL tests are opt-in')
class CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_stock.PostgresStockTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.client, self.connection = self.fixture.client, self.fixture.connection
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET is_active = TRUE, selling_price = 100, max_discount_percent = 10')
            self.connection.execute('INSERT INTO inventory (branch_id, product_id, quantity) VALUES (1, 2, 10)')

    def checkout(self, key=None, **changes):
        return self.client.post('/checkouts', headers={'Idempotency-Key': key or str(uuid.uuid4())},
            json={'branch_id': 1, 'payment_method': 'pos', 'items': [
                {'product_id': 1, 'quantity': 2, 'unit_price': '90.00'},
                {'product_id': 2, 'quantity': 3}], **changes})

    def counts(self):
        return [self.fixture.rows(f'SELECT COUNT(*) FROM {table}')[0][0]
                for table in ('sale_orders', 'sales', 'stock_movements', 'stock_requests')]

    def test_multi_item_checkout_receipt_and_reconciliation_once(self):
        response = self.checkout()
        self.assertEqual(response.status_code, 201)
        record = response.json()
        self.assertEqual((record['item_count'], record['total_amount'], record['payment_method']), (2, '480.00', 'pos'))
        self.assertEqual(record['business_name'], 'FESTY AGRIC SERVICES')
        self.assertTrue(record['receipt_number'].startswith('FAS-'))
        self.assertEqual(len(record['items']), 2)
        self.assertEqual(self.counts(), [1, 2, 2, 1])
        self.assertEqual(self.fixture.rows('SELECT product_id, quantity FROM inventory ORDER BY product_id'), [(1, 48), (2, 7)])
        summary = self.client.get('/reconciliations/summary', params={'branch_id': 1,
            'business_date': datetime.now(ZoneInfo('Africa/Lagos')).date().isoformat()}).json()
        self.assertEqual((summary['sales_count'], summary['expected_pos']), (1, '480.00'))

    def test_later_item_insufficient_stock_rolls_back_everything(self):
        before = self.fixture.snapshot()
        self.assertEqual(self.checkout(items=[{'product_id': 1, 'quantity': 2}, {'product_id': 2, 'quantity': 11}]).status_code, 409)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_failure_on_second_movement_rolls_back_earlier_item(self):
        with self.connection.transaction():
            self.connection.execute('ALTER TABLE stock_movements ADD CHECK (product_id <> 2)')
        before = self.fixture.snapshot()
        self.assertEqual(self.checkout().status_code, 500)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_item_policy_validation_and_missing_product(self):
        for items, status in (([], 422), ([{'product_id': 1, 'quantity': 0}], 422),
            ([{'product_id': 1, 'quantity': 1.5}], 422),
            ([{'product_id': 1, 'quantity': 1}, {'product_id': 1, 'quantity': 1}], 422),
            ([{'product_id': 1, 'quantity': 1, 'unit_price': '89.99'}], 422),
            ([{'product_id': 99, 'quantity': 1}], 404)):
            self.assertEqual(self.checkout(items=items).status_code, status)
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET is_active = FALSE WHERE id = 2')
        self.assertEqual(self.checkout().status_code, 409)
        self.assertEqual(self.counts(), [0, 0, 0, 0])

    def test_retry_is_single_purchase_even_after_prices_change(self):
        key = str(uuid.uuid4())
        first = self.checkout(key)
        with self.connection.transaction():
            self.connection.execute("UPDATE products SET selling_price = 500, name = 'Renamed'")
            self.connection.execute("UPDATE branches SET name = 'Renamed branch' WHERE id = 1")
        retry = self.checkout(key, items=[{'product_id': 2, 'quantity': 3}, {'product_id': 1, 'quantity': 2, 'unit_price': '90.0'}])
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(self.checkout(key, payment_method='cash').status_code, 409)
        details = self.client.get('/checkouts/' + str(first.json()['id'])).json()
        self.assertEqual(details['items'][0]['product_name'], 'Feed')
        self.assertEqual(details['branch_name'], first.json()['branch_name'])
        self.assertEqual(details['created_at'], first.json()['created_at'])
        self.assertEqual(self.counts(), [1, 2, 2, 1])

    def test_receipts_and_history_follow_branch_scope(self):
        record = self.checkout().json()
        main.app.dependency_overrides[auth.get_current_user] = lambda: {'id': 1, 'role': 'salesperson', 'branch_id': 2}
        self.assertEqual(self.client.get(f"/checkouts/{record['id']}").status_code, 403)
        self.assertEqual(self.client.get('/checkouts').json(), [])
        self.assertEqual(self.checkout().status_code, 403)

    def test_legacy_sales_remain_in_history_without_double_counting(self):
        self.checkout()
        legacy = self.client.post('/sales', headers={'Idempotency-Key': str(uuid.uuid4())},
            json=dict(branch_id=1, product_id=1, quantity=1, payment_method='cash')).json()
        history = self.client.get('/checkouts').json()
        self.assertEqual(len(history), 2)
        self.assertEqual({row['receipt_type'] for row in history}, {'legacy', 'checkout'})
        receipt = self.client.get(f"/sales/{legacy['id']}/receipt").json()
        self.assertEqual(receipt['receipt_number'], f"FAS-S-{legacy['id']:08d}")
        self.assertEqual(len(receipt['items']), 1)
        self.assertEqual(self.client.get('/checkouts?limit=1&offset=1').status_code, 200)

    def test_new_checkout_marks_previous_reconciliation_stale(self):
        today = datetime.now(ZoneInfo('Africa/Lagos')).date().isoformat()
        record = self.client.post('/reconciliations', headers={'Idempotency-Key': str(uuid.uuid4())},
            json=dict(branch_id=1, business_date=today, actual_cash='0', actual_pos='0')).json()
        self.checkout()
        summary = self.client.get('/reconciliations/summary', params=dict(branch_id=1, business_date=today)).json()
        self.assertTrue(summary['is_stale'])
        self.assertEqual(self.client.post(f"/reconciliations/{record['id']}/review", json={}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
