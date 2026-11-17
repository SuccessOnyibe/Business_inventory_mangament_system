"""Resolution audit, exact financial reports/CSV, and controlled stock adjustments."""
import csv
import io
import os
import unittest
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import main
import auth
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'PostgreSQL tests are opt-in')
class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_stock.PostgresStockTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.client, self.connection = self.fixture.client, self.fixture.connection
        self.today = datetime.now(ZoneInfo('Africa/Lagos')).date()
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET selling_price = 100 WHERE id = 1')

    def post(self, path, body, key=None):
        return self.client.post(path, json=body, headers={'Idempotency-Key': key or str(uuid.uuid4())})

    def sale(self, method='cash'):
        response = self.post('/sales', dict(branch_id=1, product_id=1, quantity=1, payment_method=method))
        self.assertEqual(response.status_code, 201)
        return response.json()

    def discrepancy(self, review=True):
        self.sale()
        record = self.post('/reconciliations', dict(branch_id=1, business_date=self.today.isoformat(),
            actual_cash='90', actual_pos='0')).json()
        if review:
            self.assertEqual(self.client.post(f"/reconciliations/{record['id']}/review", json={}).status_code, 200)
        return record

    def event(self, record, key=None, **changes):
        return self.post(f"/reconciliations/{record['id']}/discrepancy-events", {
            'action': 'investigate', 'explanation': 'Compare receipts with the cash count',
            'responsible_user_id': 1, **changes}, key)

    def report(self, **changes):
        return self.client.get('/reports/financial', params={
            'start_date': self.today.isoformat(), 'end_date': self.today.isoformat(), 'branch_id': 1, **changes})

    def adjustment(self, key=None, **changes):
        return self.post('/stock-adjustments', {'branch_id': 1, 'product_id': 1,
            'mode': 'physical_count', 'expected_quantity': 50, 'counted_quantity': 48,
            'reason': 'Physical shelf count confirmed', **changes}, key)

    def test_resolution_lifecycle_preserves_counts_and_snapshots(self):
        record = self.discrepancy()
        original = self.fixture.rows('SELECT actual_cash, expected_cash, cash_difference, reviewed_at FROM daily_reconciliations')
        key = str(uuid.uuid4())
        first = self.event(record, key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.event(record, key).json(), first.json())
        resolved = self.event(record, action='resolve', resolution_action='Accepted documented shortage; staff follow-up completed')
        self.assertEqual(resolved.status_code, 201)
        self.assertEqual(self.event(record).status_code, 409)
        self.assertEqual(self.event(record, action='reopen', explanation='New evidence to check').status_code, 201)
        self.assertEqual(self.fixture.rows('SELECT actual_cash, expected_cash, cash_difference, reviewed_at FROM daily_reconciliations'), original)
        self.assertEqual(self.client.get('/reconciliations').json()[0]['resolution_state'], 'open')
        self.assertEqual(len(self.client.get('/discrepancy-events').json()), 3)

    def test_resolution_requires_review_current_snapshot_and_explanation(self):
        record = self.discrepancy(review=False)
        self.assertEqual(self.event(record, action='resolve', resolution_action='Checked').status_code, 409)
        self.assertEqual(self.event(record, explanation=' ').status_code, 422)
        self.assertEqual(self.event(record, action='resolve').status_code, 422)
        self.sale()
        self.assertEqual(self.event(record).status_code, 409)

    def test_assignment_validation_and_assignee_list(self):
        record = self.discrepancy()
        with self.connection.transaction():
            wrong = self.connection.execute("INSERT INTO users (username,password_hash,role,branch_id) VALUES ('otherbranch','unused','salesperson',2) RETURNING id").fetchone()[0]
        self.assertEqual(self.event(record, responsible_user_id=wrong).status_code, 422)
        self.assertEqual(self.event(record, responsible_user_id=99).status_code, 404)
        self.assertEqual([row['username'] for row in self.client.get(f"/reconciliations/{record['id']}/assignees").json()], ['tester'])

    def test_report_tracks_unresolved_and_resolved_without_hiding_variance(self):
        record = self.discrepancy()
        report = self.report()
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()['totals']['gross_sales'], '100.00')
        self.assertEqual(report.json()['totals']['unresolved_days'], 1)
        self.assertEqual(self.event(record, action='resolve', resolution_action='Documented shortage accepted').status_code, 201)
        updated = self.report().json()
        self.assertEqual(updated['totals']['unresolved_days'], 0)
        self.assertEqual(updated['rows'][0]['cash_difference'], '-10.00')
        self.sale()
        stale = self.report().json()
        self.assertEqual(stale['rows'][0]['resolution_state'], 'out_of_date')
        self.assertEqual(stale['totals']['unreconciled_days'], 1)

    def test_report_refunds_unknown_methods_empty_days_and_csv(self):
        sale = self.sale('pos')
        self.assertEqual(self.post('/sale-corrections', dict(receipt_type='legacy', receipt_id=sale['id'],
            kind='void', reason='Wrong entry', refund_method='cash')).status_code, 201)
        report = self.report().json()
        self.assertEqual((report['totals']['gross_pos'], report['totals']['refund_cash'], report['totals']['net_sales']), ('100.00', '100.00', '0.00'))
        self.assertEqual(report['totals']['expected_cash'], '-100.00')
        with self.connection.transaction():
            self.connection.execute("UPDATE branches SET name = '=SUM(1,2)' WHERE id = 1")
        response = self.client.get('/reports/financial.csv', params=dict(start_date=self.today.isoformat(), end_date=self.today.isoformat(), branch_id=1))
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.text.lstrip('\ufeff'))))
        self.assertTrue(rows[0]['branch_name'].startswith("'="))
        self.assertEqual(rows[0]['expected_cash'], '-100.00')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(self.report(start_date=(self.today-timedelta(days=1)).isoformat()).json()['rows'][0]['reconciliation_status'], 'no_activity')

    def test_report_includes_unclassified_gross_without_guessing_cash(self):
        self.sale()
        with self.connection.transaction():
            self.connection.execute('UPDATE sales SET payment_method = NULL')
        totals = self.report().json()['totals']
        self.assertEqual((totals['gross_sales'], totals['unclassified_amount'], totals['gross_cash']), ('100.00', '100.00', '0.00'))

    def test_report_uses_lagos_day_boundaries(self):
        first, second = self.sale(), self.sale('pos')
        with self.connection.transaction():
            self.connection.execute("UPDATE sales SET created_at = '2026-01-01T23:00:00Z' WHERE id = %s", (first['id'],))
            self.connection.execute("UPDATE sales SET created_at = '2026-01-02T23:00:00Z' WHERE id = %s", (second['id'],))
        day = self.report(start_date='2026-01-02', end_date='2026-01-02').json()
        self.assertEqual((day['totals']['gross_cash'], day['totals']['gross_pos']), ('100.00', '0.00'))
        both = self.report(start_date='2026-01-02', end_date='2026-01-03').json()
        self.assertEqual(both['totals']['gross_sales'], '200.00')

    def test_report_range_and_role_validation(self):
        self.assertEqual(self.report(end_date=(self.today+timedelta(days=1)).isoformat()).status_code, 422)
        self.assertEqual(self.report(start_date=(self.today-timedelta(days=366)).isoformat()).status_code, 422)
        self.assertEqual(self.report(branch_id=99).status_code, 404)
        main.app.dependency_overrides[auth.get_current_user] = lambda: {'id': 1, 'role': 'salesperson', 'branch_id': 1}
        self.assertEqual(self.report().status_code, 403)
        self.assertEqual(self.adjustment().status_code, 403)

    def test_adjustment_audit_replay_and_matching_count(self):
        key = str(uuid.uuid4())
        first = self.adjustment(key)
        self.assertEqual(first.status_code, 201)
        self.assertEqual((first.json()['quantity_before'], first.json()['quantity_after'], first.json()['quantity_change']), (50, 48, -2))
        self.assertEqual(self.adjustment(key).json(), first.json())
        self.assertEqual(self.adjustment().status_code, 409)
        matching = self.adjustment(expected_quantity=48, counted_quantity=48)
        self.assertEqual(matching.status_code, 201)
        self.assertEqual(matching.json()['quantity_change'], 0)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM stock_movements'), [(1,)])
        self.assertEqual(len(self.client.get('/stock-adjustments').json()), 2)

    def test_damage_expiry_and_signed_corrections(self):
        for mode, before, delta, after in (('damage',50,-2,48), ('expiry',48,-3,45), ('correction',45,4,49)):
            result = self.adjustment(mode=mode, expected_quantity=before, counted_quantity=None, quantity_change=delta)
            self.assertEqual(result.status_code, 201)
            self.assertEqual(result.json()['quantity_after'], after)
        self.assertEqual(self.adjustment(mode='damage', expected_quantity=49, counted_quantity=None, quantity_change=1).status_code, 422)
        self.assertEqual(self.adjustment(mode='expiry', expected_quantity=49, counted_quantity=None, quantity_change=-50).status_code, 409)
        self.assertEqual(self.adjustment(mode='correction', expected_quantity=49, counted_quantity=None, quantity_change=2147483647).status_code, 409)

    def test_stale_balance_missing_stock_and_failed_movement_rollback(self):
        self.sale()
        self.assertEqual(self.adjustment().status_code, 409)
        result = self.adjustment(branch_id=2, expected_quantity=0, counted_quantity=5)
        self.assertEqual(result.status_code, 201)
        with self.connection.transaction():
            self.connection.execute("ALTER TABLE stock_movements ADD CHECK (movement_type <> 'damage')")
        before = self.fixture.snapshot()
        self.assertEqual(self.adjustment(mode='damage', expected_quantity=49, counted_quantity=None, quantity_change=-1).status_code, 500)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM stock_adjustments'), [(1,)])

    def test_stock_history_is_scoped_and_reasons_are_required(self):
        self.assertEqual(self.adjustment(reason=' ').status_code, 422)
        self.assertEqual(self.adjustment().status_code, 201)
        main.app.dependency_overrides[auth.get_current_user] = lambda: {'id':1, 'role':'salesperson', 'branch_id':2}
        self.assertEqual(self.client.get('/stock-adjustments').json(), [])
        self.assertEqual(self.client.get('/discrepancy-events?branch_id=1').status_code, 403)


if __name__ == '__main__':
    unittest.main()
