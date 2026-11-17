"""Delivery labels are atomic, retry-safe, and never presented as batch balances."""
from datetime import datetime, timedelta
import os
import unittest
from unittest.mock import patch
import uuid
from zoneinfo import ZoneInfo

import main
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'Requires isolated PostgreSQL')
class ReceiptBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_stock.PostgresStockTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.client = self.fixture.client
        self.today = datetime.now(ZoneInfo('Africa/Lagos')).date()

    def test_labels_actor_and_timestamp_are_saved_with_delivery(self):
        response = self.fixture.receipt(batch_number=' LOT-17 ', expires_on=self.today.isoformat())
        self.assertEqual(response.status_code, 201)
        record = self.client.get('/stock-receipts').json()[0]
        self.assertEqual(record['batch_number'], 'LOT-17')
        self.assertEqual(record['expires_on'], self.today.isoformat())
        self.assertEqual(record['received_by_name'], 'tester')
        self.assertEqual(record['received_at'], response.json()['received_at'])
        self.assertEqual(record['quantity_received'], 100)
        self.assertNotIn('quantity_remaining', record)

    def test_unknown_labels_are_optional_and_old_keys_keep_their_shape(self):
        key = str(uuid.uuid4())
        self.assertEqual(self.fixture.receipt(request_key=key).status_code, 201)
        payload = self.fixture.rows('SELECT request_payload FROM stock_requests')[0][0]
        self.assertNotIn('batch_number', payload)
        self.assertNotIn('expires_on', payload)
        self.assertEqual(self.fixture.receipt(request_key=key, batch_number=None, expires_on=None).status_code, 201)
        self.assertIsNone(self.client.get('/stock-receipts').json()[0]['batch_number'])

    def test_expired_or_invalid_labels_do_not_change_stock(self):
        before = self.fixture.snapshot()
        for data in ({'batch_number':' '}, {'batch_number':'X'*101}, {'expires_on':'invalid'},
                     {'expires_on':(self.today-timedelta(days=1)).isoformat()}):
            self.assertEqual(self.fixture.receipt(**data).status_code, 422)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM stock_requests'), [(0,)])

    def test_replay_after_expiry_works_but_changed_label_conflicts(self):
        key = str(uuid.uuid4())
        body = dict(batch_number='LOT-17', expires_on=self.today.isoformat())
        first = self.fixture.receipt(request_key=key, **body)
        self.assertEqual(first.status_code, 201)
        tomorrow = datetime.now(ZoneInfo('Africa/Lagos')) + timedelta(days=1)
        with patch.object(main, 'datetime') as clock:
            clock.now.return_value = tomorrow
            self.assertEqual(self.fixture.receipt(request_key=key, **body).json(), first.json())
        self.assertEqual(self.fixture.receipt(request_key=key, **{**body,'batch_number':'changed'}).status_code, 409)
        self.assertEqual(len(self.client.get('/stock-receipts').json()), 1)

    def test_receipt_failure_rolls_back_labels_stock_and_retry_key(self):
        before = self.fixture.snapshot()
        self.fixture.fail_movements('stock_received')
        self.assertEqual(self.fixture.receipt(batch_number='LOT-17').status_code, 500)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM stock_requests'), [(0,)])

    def test_history_scope_pagination_and_product_filter(self):
        self.fixture.receipt(batch_number='FIRST')
        self.fixture.receipt(branch_id=2, batch_number='SECOND')
        records = self.client.get('/stock-receipts?limit=1&offset=1').json()
        self.assertEqual(records[0]['batch_number'], 'FIRST')
        self.assertEqual(self.client.get('/stock-receipts?product_id=2').json(), [])
        main.app.dependency_overrides[main.get_current_user] = lambda: {'id':1,'role':'salesperson','branch_id':2}
        self.assertEqual(len(self.client.get('/stock-receipts').json()), 1)
        self.assertEqual(self.client.get('/stock-receipts?branch_id=1').status_code, 403)
        self.assertEqual(self.fixture.receipt().status_code, 403)
