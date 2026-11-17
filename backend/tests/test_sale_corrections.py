"""Append-only voids/returns, refund-day accounting, and all-or-nothing restocking."""
import os
import unittest
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import main
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'PostgreSQL tests are opt-in')
class SaleCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_stock.PostgresStockTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.client, self.connection = self.fixture.client, self.fixture.connection
        self.today = datetime.now(ZoneInfo('Africa/Lagos')).date()
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET is_active = TRUE, selling_price = 100, max_discount_percent = 10')
            self.connection.execute('INSERT INTO inventory (branch_id, product_id, quantity) VALUES (1, 2, 10)')
        response = self.client.post('/checkouts', headers={'Idempotency-Key': str(uuid.uuid4())}, json=dict(
            branch_id=1, payment_method='pos', items=[dict(product_id=1, quantity=2, unit_price='90.00'),
                                                    dict(product_id=2, quantity=3)]))
        self.assertEqual(response.status_code, 201)
        self.order = response.json()
        self.first, self.second = [item['id'] for item in self.order['items']]

    def correction(self, key=None, **changes):
        return self.client.post('/sale-corrections', headers={'Idempotency-Key': key or str(uuid.uuid4())},
            json={'receipt_type': 'checkout', 'receipt_id': self.order['id'], 'kind': 'return',
                  'reason': 'Customer returned an unopened item',
                  'items': [dict(sale_id=self.first, quantity=1, restock=True)], **changes})

    def details(self):
        return self.client.get(f"/checkouts/{self.order['id']}").json()

    def summary(self, day=None):
        return self.client.get('/reconciliations/summary', params=dict(branch_id=1,
            business_date=(day or self.today).isoformat())).json()

    def test_void_restores_all_stock_preserves_sale_and_replays_once(self):
        original = self.fixture.rows('SELECT id, quantity, unit_price FROM sales ORDER BY id')
        key = str(uuid.uuid4())
        response = self.correction(key=key, kind='void', items=None)
        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.json()['refund_total'], response.json()['refund_method']), ('480.00', 'pos'))
        self.assertEqual(self.fixture.rows('SELECT product_id, quantity FROM inventory ORDER BY product_id'), [(1, 50), (2, 10)])
        self.assertEqual(self.fixture.rows('SELECT id, quantity, unit_price FROM sales ORDER BY id'), original)
        self.assertEqual(self.correction(key=key, kind='void', items=None).json(), response.json())
        self.assertEqual(self.correction(kind='void', items=None).status_code, 409)
        self.assertEqual(self.correction().status_code, 409)
        self.assertEqual((self.details()['status'], self.details()['net_total']), ('voided', '0.00'))

    def test_partial_resellable_and_damaged_returns_cannot_exceed_sold(self):
        first = self.correction()
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['refund_total'], '90.00')
        damaged = self.correction(items=[dict(sale_id=self.second, quantity=2, restock=False)])
        self.assertEqual(damaged.status_code, 201)
        self.assertEqual(self.fixture.rows('SELECT product_id, quantity FROM inventory ORDER BY product_id'), [(1, 49), (2, 7)])
        self.assertEqual(self.correction(items=[dict(sale_id=self.first, quantity=2, restock=True)]).status_code, 409)
        self.assertEqual(self.correction(kind='void', items=None).status_code, 409)
        receipt = self.details()
        self.assertEqual((receipt['status'], receipt['refunded_total'], receipt['net_total']), ('partially_returned', '290.00', '190.00'))
        final = self.correction(items=[dict(sale_id=self.first, quantity=1, restock=True), dict(sale_id=self.second, quantity=1, restock=False)])
        self.assertEqual(final.status_code, 201)
        self.assertEqual(self.details()['status'], 'returned')
        self.assertEqual(self.fixture.rows("SELECT COUNT(*) FROM stock_movements WHERE movement_type = 'sale_return'"), [(2,)])

    def test_refund_uses_original_discounted_price_after_catalogue_edit(self):
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET selling_price = 1000, max_discount_percent = 0')
        result = self.correction(refund_method='cash')
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()['refund_total'], '90.00')
        totals = self.summary()
        self.assertEqual((totals['gross_pos'], totals['refund_cash'], totals['expected_cash'], totals['expected_pos']),
                         ('480.00', '90.00', '-90.00', '480.00'))

    def test_later_day_refund_keeps_original_day_and_allows_negative_net_count(self):
        yesterday = self.today - timedelta(days=1)
        stamp = datetime.combine(yesterday, datetime.min.time(), tzinfo=ZoneInfo('Africa/Lagos')) + timedelta(hours=12)
        with self.connection.transaction():
            self.connection.execute('UPDATE sale_orders SET created_at = %s', (stamp,))
            self.connection.execute('UPDATE sales SET created_at = %s', (stamp,))
        self.assertEqual(self.correction(kind='void', items=None).status_code, 201)
        self.assertEqual((self.summary(yesterday)['expected_pos'], self.summary()['expected_pos']), ('480.00', '-480.00'))
        response = self.client.post('/reconciliations', headers={'Idempotency-Key': str(uuid.uuid4())},
            json=dict(branch_id=1, business_date=self.today.isoformat(), actual_cash='0', actual_pos='-480.00'))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['pos_difference'], '0.00')

    def test_new_refund_marks_daily_count_stale(self):
        record = self.client.post('/reconciliations', headers={'Idempotency-Key': str(uuid.uuid4())},
            json=dict(branch_id=1, business_date=self.today.isoformat(), actual_cash='0', actual_pos='480')).json()
        self.correction()
        self.assertTrue(self.summary()['is_stale'])
        self.assertEqual(self.client.post(f"/reconciliations/{record['id']}/review", json={}).status_code, 409)

    def test_failed_later_restock_movement_rolls_back_everything(self):
        with self.connection.transaction():
            self.connection.execute("ALTER TABLE stock_movements ADD CHECK (movement_type = 'sale' OR product_id <> 2)")
        before = self.fixture.snapshot()
        self.assertEqual(self.correction(kind='void', items=None).status_code, 500)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM sale_corrections'), [(0,)])
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM sale_correction_items'), [(0,)])
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM stock_requests'), [(1,)])

    def test_restock_overflow_rolls_back_refund(self):
        with self.connection.transaction():
            self.connection.execute('UPDATE inventory SET quantity = 2147483647 WHERE product_id = 1')
        self.assertEqual(self.correction().status_code, 409)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM sale_corrections'), [(0,)])

    def test_salesperson_cannot_approve_corrections_and_scope_applies_to_reads(self):
        record = self.correction().json()
        main.app.dependency_overrides[main.get_current_user] = lambda: {'id': 1, 'role': 'salesperson', 'branch_id': 2}
        self.assertEqual(self.correction().status_code, 403)
        self.assertEqual(self.client.get('/sale-corrections').json(), [])
        self.assertEqual(self.client.get(f"/sale-corrections/{record['id']}").status_code, 403)

    def test_reason_item_ownership_and_input_validation(self):
        for changes in ({'reason': '   '}, {'items': []}, {'items': [dict(sale_id=self.first, quantity=0, restock=True)]},
                        {'items': [dict(sale_id=999, quantity=1, restock=True)]},
                        {'refund_method': 'bank_transfer'}, {'refund_total': '999999'}):
            self.assertEqual(self.correction(**changes).status_code, 422)
        self.assertEqual(self.correction(receipt_id=999).status_code, 404)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM sale_corrections'), [(0,)])

    def test_legacy_unknown_payment_requires_explicit_refund_method(self):
        legacy = self.client.post('/sales', headers={'Idempotency-Key': str(uuid.uuid4())},
            json=dict(branch_id=1, product_id=1, quantity=1, payment_method='cash')).json()
        with self.connection.transaction():
            self.connection.execute('UPDATE sales SET payment_method = NULL WHERE id = %s', (legacy['id'],))
        request = dict(receipt_type='legacy', receipt_id=legacy['id'], kind='void', items=None)
        self.assertEqual(self.correction(**request).status_code, 422)
        self.assertEqual(self.correction(**request, refund_method='cash').status_code, 201)
        receipt = self.client.get(f"/sales/{legacy['id']}/receipt").json()
        self.assertEqual(receipt['status'], 'voided')
        self.assertIsNone(receipt['payment_method'])

    def test_history_receipt_and_timestamps(self):
        response = self.correction()
        record = response.json()
        self.assertIsNotNone(datetime.fromisoformat(record['created_at']).utcoffset())
        self.assertEqual(self.client.get(f"/sale-corrections/{record['id']}").json(), record)
        self.assertEqual(self.client.get('/sale-corrections').json()[0]['id'], record['id'])
        self.assertEqual(self.client.get('/sale-corrections?offset=1').json(), [])
        self.assertEqual(self.details()['corrections'][0]['receipt_number'], record['receipt_number'])


if __name__ == '__main__':
    unittest.main()
