"""Real PostgreSQL sale/discount tests, always using isolated temporary tables."""
import os
import unittest
import uuid
from datetime import datetime

import main
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'PostgreSQL tests are opt-in')
class SaleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_stock.PostgresStockTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.connection = self.fixture.connection
        self.client = self.fixture.client
        with self.connection.transaction():
            self.connection.execute("UPDATE products SET selling_price = 100.00, max_discount_percent = 10 WHERE id = 1")

    def role(self, role, branch_id=1):
        main.app.dependency_overrides[main.get_current_user] = lambda: {
            'id': 1, 'username': 'tester', 'role': role, 'branch_id': branch_id}

    def sale(self, key=None, **changes):
        return self.client.post('/sales', headers={'Idempotency-Key': key or str(uuid.uuid4())},
                                json={'branch_id': 1, 'product_id': 1, 'quantity': 2, 'payment_method': 'cash', **changes})

    def test_default_price_whole_units_and_timestamp(self):
        self.role('salesperson')
        response = self.sale()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual((body['unit_price'], body['total_amount'], body['currency']), ('100.00', '200.00', 'NGN'))
        self.assertEqual(body['updated_quantity'], 48)
        self.assertEqual(body['payment_method'], 'cash')
        self.assertIsNotNone(datetime.fromisoformat(body['created_at']).utcoffset())
        self.assertEqual(self.fixture.rows("SELECT quantity_change, movement_type, sale_id FROM stock_movements"),
                         [(-2, 'sale', body['id'])])

    def test_pos_payment_is_recorded_and_replayed(self):
        key = str(uuid.uuid4())
        first = self.sale(key=key, payment_method='pos')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()['payment_method'], 'pos')
        self.assertEqual(self.sale(key=key, payment_method='pos').json(), first.json())
        self.assertEqual(self.sale(key=key, payment_method='cash').status_code, 409)
        self.assertEqual(self.client.get('/sales').json()[0]['payment_method'], 'pos')

    def test_payment_method_is_explicit_and_invalid_method_has_no_stock_effect(self):
        for value in ('transfer', 'Cash', '', None):
            self.assertEqual(self.sale(payment_method=value).status_code, 422)
        response = self.client.post('/sales', json=dict(branch_id=1, product_id=1, quantity=1),
                                    headers={'Idempotency-Key': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.fixture.snapshot(), ([(1, 1, 50)], []))

    def test_historical_unknown_payment_is_not_assumed_cash(self):
        response = self.sale()
        with self.connection.transaction():
            self.connection.execute('UPDATE sales SET payment_method = NULL WHERE id = %s', (response.json()['id'],))
        self.assertIsNone(self.client.get('/sales').json()[0]['payment_method'])

    def test_exact_discount_limit_and_rejection_below_limit(self):
        self.role('salesperson')
        accepted = self.sale(unit_price='90.00', customer_name='Regular customer')
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(accepted.json()['total_amount'], '180.00')
        before = self.fixture.snapshot()
        for value in ('89.99', '100.01', '-1', '90.001'):
            self.assertEqual(self.sale(unit_price=value).status_code, 422)
        self.assertEqual(self.fixture.snapshot(), before)

    def test_minimum_rounds_up_to_kobo(self):
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET selling_price = 10.01, max_discount_percent = 5 WHERE id = 1')
        self.assertEqual(self.sale(unit_price='9.50').status_code, 422)
        self.assertEqual(self.sale(unit_price='9.51').status_code, 201)

    def test_zero_discount_default_and_admin_policy_only(self):
        self.role('admin')
        result = self.client.patch('/products/1', json={'max_discount_percent': '0'})
        self.assertEqual(result.status_code, 200)
        self.role('manager')
        self.assertEqual(self.client.patch('/products/1', json={'selling_price': '200.00'}).status_code, 200)
        self.assertEqual(self.client.patch('/products/1', json={'max_discount_percent': '20'}).status_code, 403)
        self.assertEqual(self.sale(unit_price='199.99').status_code, 422)
        self.role('salesperson')
        self.assertEqual(self.client.patch('/products/1', json={'selling_price': '1'}).status_code, 403)

    def test_product_creation_and_price_visibility(self):
        self.role('admin')
        body = dict(name='New feed', category='Feed', base_unit='bag', selling_price='25000.00', max_discount_percent='5')
        response = self.client.post('/products', json=body)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['selling_price'], '25000.00')
        self.role('manager')
        self.assertEqual(self.client.post('/products', json=body).status_code, 403)
        body.pop('max_discount_percent')
        self.assertEqual(self.client.post('/products', json=body).status_code, 201)
        self.role('salesperson')
        products = self.client.get('/products').json()
        self.assertEqual(products[0]['max_discount_percent'], '10.00')

    def test_missing_inactive_unpriced_and_insufficient_stock(self):
        for changes, code in ((dict(branch_id=99), 404), (dict(product_id=99), 404),
                              (dict(product_id=2), 409), (dict(quantity=51), 409)):
            self.assertEqual(self.sale(**changes).status_code, code)
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET selling_price = NULL WHERE id = 1')
        self.assertEqual(self.sale().status_code, 409)
        self.assertEqual(self.fixture.snapshot(), ([(1, 1, 50)], []))
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM sales'), [(0,)])
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM stock_requests'), [(0,)])

    def test_branch_scope_and_history_filtering(self):
        self.assertEqual(self.sale().status_code, 201)
        self.role('salesperson', 2)
        self.assertEqual(self.sale().status_code, 403)
        self.assertEqual(self.client.get('/sales').json(), [])
        self.assertEqual(self.client.get('/sales?branch_id=1').status_code, 403)
        self.role('admin')
        self.assertEqual(len(self.client.get('/sales').json()), 1)
        self.assertEqual(self.client.get('/sales?offset=1').json(), [])

    def test_retry_uses_original_price_units_and_timestamp(self):
        key = str(uuid.uuid4())
        first = self.sale(key=key, unit_price='90.00')
        with self.connection.transaction():
            self.connection.execute("UPDATE products SET selling_price = 500, max_discount_percent = 0, name = 'Renamed', base_unit = 'piece' WHERE id = 1")
        retry = self.sale(key=key, unit_price='90.0')
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM sales'), [(1,)])
        self.assertEqual(self.sale(key=key, unit_price='91.00').status_code, 409)
        stored = self.client.get('/sales').json()[0]
        self.assertEqual((stored['product_name'], stored['base_unit'], stored['list_price']), ('Feed', 'bag', '100.00'))

    def test_failed_movement_rolls_back_sale_inventory_and_key(self):
        self.fixture.fail_movements('sale')
        self.assertEqual(self.sale().status_code, 500)
        self.assertEqual(self.fixture.snapshot(), ([(1, 1, 50)], []))
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM sales'), [(0,)])
        self.assertEqual(self.fixture.rows('SELECT COUNT(*) FROM stock_requests'), [(0,)])

    def test_whole_quantity_and_idempotency_header_validation(self):
        for value in (0, -1, True, 1.5, '2', 2147483648):
            self.assertEqual(self.sale(quantity=value).status_code, 422)
        self.assertEqual(self.client.post('/sales', json=dict(branch_id=1, product_id=1, quantity=1)).status_code, 422)

    def test_transfer_dispatch_and_confirmation_have_saved_timestamps(self):
        dispatched = self.fixture.dispatch()
        self.assertEqual(dispatched.status_code, 201)
        body = dispatched.json()
        self.assertIsNotNone(datetime.fromisoformat(body['created_at']).utcoffset())
        route = '/stock-transfers/' + str(body['transfer_id']) + '/confirm'
        confirmed = self.client.post(route)
        self.assertEqual(confirmed.status_code, 200)
        self.assertGreaterEqual(datetime.fromisoformat(confirmed.json()['received_at']), datetime.fromisoformat(body['created_at']))
        self.assertEqual(self.client.post(route).json(), confirmed.json())


if __name__ == '__main__':
    unittest.main()
