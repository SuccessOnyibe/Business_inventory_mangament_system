"""Retired cash-ledger routes cannot write; previously posted history stays accounted for."""
import os
import unittest
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
import main
import auth
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS')=='1','Requires isolated PostgreSQL')
class RetiredCashLedgerTests(unittest.TestCase):
    def setUp(self):
        self.f=test_stock.PostgresStockTests();self.addCleanup(self.f.doCleanups);self.f.setUp();self.client=self.f.client

    def test_removed_routes_are_unavailable_to_admin_and_salesperson(self):
        paths=('/cash-movements','/cash-movement-requests','/cash-movement-requests/1/decision','/cash-recovery-options?branch_id=1')
        for role in ('admin','salesperson'):
            main.app.dependency_overrides[auth.get_current_user]=lambda role=role:{'id':1,'role':role,'branch_id':1}
            for path in paths:
                self.assertEqual(self.client.get(path).status_code,404)
                self.assertEqual(self.client.post(path,json={'branch_id':1,'kind':'expense','amount':'20','reason':'Retired'},headers={'Idempotency-Key':str(uuid.uuid4())}).status_code,404)
        self.assertEqual(self.f.rows('SELECT count(*) FROM cash_movements'),[(0,)])
        self.assertEqual(self.f.rows('SELECT count(*) FROM stock_requests'),[(0,)])

    def test_removed_feature_is_absent_from_api_documentation(self):
        self.assertFalse(any(path.startswith('/cash-') for path in self.client.get('/openapi.json').json()['paths']))

    def test_archived_entries_remain_in_historical_counts_and_reports(self):
        # Fixture SQL only: preserve the effect of history recorded before retirement.
        with self.f.connection.transaction():
            stamp=self.f.connection.execute('SELECT clock_timestamp()').fetchone()[0]
            day=stamp.astimezone(ZoneInfo('Africa/Lagos')).date()
            record=self.f.connection.execute("""INSERT INTO cash_movement_requests
                (branch_id,branch_name,kind,amount,reason,requested_by,requested_by_name,status,decided_by,decided_by_name,decided_at)
                VALUES (1,'Historic branch','cash_added',25,'Historical entry',1,'tester','approved',1,'tester',%s) RETURNING id""",(stamp,)).fetchone()[0]
            self.f.connection.execute("""INSERT INTO cash_movements
                (request_id,branch_id,kind,amount,expected_cash_effect,business_date,posted_at,created_by,created_by_name)
                VALUES (%s,1,'cash_added',25,25,%s,%s,1,'tester')""",(record,day,stamp))
        summary=self.client.get('/reconciliations/summary',params={'branch_id':1,'business_date':day.isoformat()}).json()
        self.assertEqual(summary['expected_cash'],'25.00')
        report=self.client.get('/reports/financial',params={'start_date':day.isoformat(),'end_date':day.isoformat()}).json()
        self.assertEqual(report['totals']['net_sales'],'0.00')
        self.assertEqual(report['totals']['expected_cash'],'25.00')
