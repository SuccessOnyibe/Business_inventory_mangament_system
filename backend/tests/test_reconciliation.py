"""Daily-count snapshots, Lagos day boundaries, review, and branch permissions."""
import os
import unittest
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import main
import auth
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'PostgreSQL tests are opt-in')
class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_stock.PostgresStockTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.client = self.fixture.client
        self.connection = self.fixture.connection
        self.today = datetime.now(ZoneInfo('Africa/Lagos')).date()
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET selling_price = 100 WHERE id = 1')

    def sale(self, method='cash', quantity=1):
        response = self.client.post('/sales', headers={'Idempotency-Key': str(uuid.uuid4())},
            json=dict(branch_id=1, product_id=1, quantity=quantity, payment_method=method))
        self.assertEqual(response.status_code, 201)
        return response.json()

    def submit(self, key=None, **changes):
        return self.client.post('/reconciliations', headers={'Idempotency-Key': key or str(uuid.uuid4())},
            json={'branch_id': 1, 'business_date': self.today.isoformat(), 'actual_cash': '0', 'actual_pos': '0', **changes})

    def summary(self, **changes):
        return self.client.get('/reconciliations/summary', params={
            'branch_id': 1, 'business_date': self.today.isoformat(), **changes})

    def review(self, record_id, notes='Checked terminal report and cash count'):
        return self.client.post(f'/reconciliations/{record_id}/review', json={'notes': notes})

    def test_expected_totals_differences_and_timestamps(self):
        self.sale(quantity=2)
        self.sale('pos')
        summary = self.summary().json()
        self.assertEqual((summary['expected_cash'], summary['expected_pos'], summary['sales_count']), ('200.00', '100.00', 2))
        before = self.fixture.snapshot()
        response = self.submit(actual_cash='190.00', actual_pos='105.00')
        self.assertEqual(response.status_code, 201)
        record = response.json()
        self.assertEqual((record['cash_difference'], record['pos_difference']), ('-10.00', '5.00'))
        self.assertIsNotNone(datetime.fromisoformat(record['submitted_at']).utcoffset())
        self.assertEqual(self.fixture.snapshot(), before, 'Reconciliation never changes inventory or sales')
        reviewed = self.review(record['id'])
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.json()['status'], 'reviewed')
        self.assertIsNotNone(datetime.fromisoformat(reviewed.json()['reviewed_at']).utcoffset())

    def test_lagos_midnight_boundaries(self):
        first, second = self.sale(), self.sale('pos')
        with self.connection.transaction():
            self.connection.execute("UPDATE sales SET created_at = '2026-01-01T23:00:00Z' WHERE id = %s", (first['id'],))
            self.connection.execute("UPDATE sales SET created_at = '2026-01-02T23:00:00Z' WHERE id = %s", (second['id'],))
        result = self.summary(business_date='2026-01-02').json()
        self.assertEqual((result['sales_count'], result['expected_cash'], result['expected_pos']), (1, '100.00', '0.00'))

    def test_zero_sales_day_can_be_reconciled(self):
        summary = self.summary().json()
        self.assertEqual(summary['expected_cash'], '0.00')
        record = self.submit().json()
        self.assertEqual(record['sales_count'], 0)
        self.assertEqual(self.review(record['id']).status_code, 200)

    def test_replay_does_not_create_revision_or_change_snapshot(self):
        key = str(uuid.uuid4())
        first = self.submit(key=key)
        self.sale()
        retry = self.submit(key=key, actual_cash='0.00')
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM daily_reconciliations'), [(1,)])
        self.assertEqual(self.submit(key=key, actual_cash='1').status_code, 409)
        self.assertTrue(self.summary().json()['is_stale'])
        self.assertEqual(self.review(first.json()['id']).status_code, 409)

    def test_revisions_preserve_old_submission_and_review_is_repeat_safe(self):
        first = self.submit(actual_cash='1').json()
        second = self.submit(actual_cash='2').json()
        self.assertEqual((first['revision'], second['revision']), (1, 2))
        self.assertEqual(self.review(first['id']).status_code, 409)
        reviewed = self.review(second['id'])
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(self.review(second['id'], notes='Different retry note').json(), reviewed.json())
        history = self.client.get('/reconciliations').json()
        self.assertEqual([item['is_latest'] for item in history], [True, False])
        self.assertEqual(self.client.get('/reconciliations?limit=1&offset=1').json()[0]['id'], first['id'])

    def test_more_sales_after_review_mark_summary_stale_without_overwriting_review(self):
        record = self.submit().json()
        reviewed = self.review(record['id']).json()
        self.sale()
        summary = self.summary().json()
        self.assertTrue(summary['is_stale'])
        self.assertEqual(summary['latest_submission']['reviewed_at'], reviewed['reviewed_at'])
        new = self.submit(actual_cash='100').json()
        self.assertEqual(new['revision'], 2)
        self.assertFalse(self.summary().json()['is_stale'])

    def test_salesperson_scope_and_manager_review_permissions(self):
        record = self.submit().json()
        main.app.dependency_overrides[auth.get_current_user] = lambda: {'id': 1, 'role': 'salesperson', 'branch_id': 2}
        self.assertEqual(self.summary().status_code, 403)
        self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(self.client.get('/reconciliations').json(), [])
        self.assertEqual(self.review(record['id']).status_code, 403)
        self.assertEqual(self.submit(branch_id=2).status_code, 201)

    def test_unknown_legacy_payment_blocks_submission(self):
        self.sale()
        with self.connection.transaction():
            self.connection.execute('UPDATE sales SET payment_method = NULL')
        summary = self.summary().json()
        self.assertEqual((summary['unclassified_count'], summary['unclassified_amount']), (1, '100.00'))
        self.assertEqual(self.submit().status_code, 409)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM daily_reconciliations'), [(0,)])

    def test_invalid_inputs_future_date_and_missing_records(self):
        for changes in ({'actual_cash': 'NaN'}, {'actual_pos': '0.001'},
                        {'business_date': (self.today + timedelta(days=1)).isoformat()},
                        {'business_date': 'not-a-date'}):
            self.assertEqual(self.submit(**changes).status_code, 422)
        self.assertEqual(self.submit(branch_id=99).status_code, 404)
        self.assertEqual(self.summary(branch_id=99).status_code, 404)
        self.assertEqual(self.review(99).status_code, 404)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM stock_requests'), [(0,)])

    def test_failed_insert_rolls_back_request_key(self):
        with self.connection.transaction():
            self.connection.execute('ALTER TABLE daily_reconciliations ADD CHECK (actual_cash = 0)')
        self.assertEqual(self.submit(actual_cash='1').status_code, 500)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM stock_requests'), [(0,)])
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM daily_reconciliations'), [(0,)])


if __name__ == '__main__':
    unittest.main()
