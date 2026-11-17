"""Printed product codes stay exact and unique; catalogue edits never alter stock."""
import os
import unittest
import main
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS')=='1','Requires isolated PostgreSQL')
class BarcodeTests(unittest.TestCase):
    def setUp(self):
        self.f=test_stock.PostgresStockTests();self.addCleanup(self.f.doCleanups);self.f.setUp();self.client=self.f.client

    def test_optional_code_preserves_zeroes_and_rejects_duplicate_atomically(self):
        before=self.f.snapshot()
        first=self.client.patch('/products/1',json={'barcode':' 0012345678905 '})
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['barcode'],'0012345678905')
        conflict=self.client.patch('/products/2',json={'barcode':'0012345678905','name':'Should roll back'})
        self.assertEqual(conflict.status_code,409)
        self.assertNotEqual(self.client.get('/products').json()[1]['name'],'Should roll back')
        self.assertEqual(self.f.snapshot(),before)

    def test_omitted_preserves_null_clears_and_invalid_codes_rejected(self):
        self.client.patch('/products/1',json={'barcode':'LOT-0001'})
        self.assertEqual(self.client.patch('/products/1',json={'name':'Renamed'}).json()['barcode'],'LOT-0001')
        for code in ('x'*65,'bad code','bad\ncode'):
            self.assertEqual(self.client.patch('/products/1',json={'barcode':code}).status_code,422)
        self.assertIsNone(self.client.patch('/products/1',json={'barcode':None}).json()['barcode'])

    def test_creation_unique_codes_and_staff_permissions(self):
        body=dict(name='Equipment',category='Equipment',base_unit='piece',selling_price='10',barcode='0099')
        self.assertEqual(self.client.post('/products',json=body).status_code,201)
        self.assertEqual(self.client.post('/products',json=body).status_code,409)
        main.app.dependency_overrides[main.get_current_user]=lambda:{'id':1,'role':'salesperson','branch_id':1}
        self.assertEqual(self.client.patch('/products/1',json={'barcode':'001'}).status_code,403)
