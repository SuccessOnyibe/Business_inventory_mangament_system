"""Customer identity management must not create debts or financial transactions."""
import os
import unittest
import uuid
import main
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'Requires isolated PostgreSQL')
class CustomerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_stock.PostgresStockTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.client = self.fixture.client

    def create(self, key=None, **changes):
        return self.client.post('/customers', headers={'Idempotency-Key':key or str(uuid.uuid4())},
            json={'branch_id':1,'name':'Ada Farm','phone':'08012345678',**changes})

    def update(self, customer, key=None, **changes):
        return self.client.post(f"/customers/{customer['id']}/update", headers={'Idempotency-Key':key or str(uuid.uuid4())},
            json={'name':customer['name'],'phone':None,'notes':None,'is_active':True,'expected_version':customer['version'],**changes})

    def test_create_retry_and_audit_without_financial_effect(self):
        before = self.fixture.snapshot()
        key = str(uuid.uuid4())
        first = self.create(key, name=' Ada Farm ')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(self.create(key).json(), first.json())
        self.assertEqual(self.create(key, name='Different farm').status_code, 409)
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM customer_changes'), [(1,)])
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM sales'), [(0,)])
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM cash_movements'), [(0,)])
        self.assertEqual(self.fixture.snapshot(), before)

    def test_updates_preserve_identity_audit_and_stale_form_guard(self):
        original = self.create().json()
        key = str(uuid.uuid4())
        updated = self.update(original, key, name='Ada Poultry', is_active=False)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()['version'], 2)
        self.assertEqual(updated.json()['id'], original['id'])
        self.assertEqual(self.update(original, key, name='Ada Poultry', is_active=False).json(), updated.json())
        self.assertEqual(self.update(original).status_code, 409)
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM customer_changes'), [(2,)])
        self.assertFalse(self.client.get('/customers').json()[0]['is_active'])

    def test_staff_are_scoped_and_cannot_manage_customers(self):
        record = self.create().json()
        self.create(branch_id=2, name='Other branch customer')
        main.app.dependency_overrides[main.get_current_user] = lambda: {'id':1,'role':'salesperson','branch_id':2}
        self.assertEqual(len(self.client.get('/customers').json()), 1)
        self.assertEqual(self.client.get('/customers?branch_id=1').status_code, 403)
        self.assertEqual(self.create().status_code, 403)
        self.assertEqual(self.update(record).status_code, 403)

    def test_validation_pagination_and_missing_records(self):
        for data in ({'name':' '},{'name':'X'*151},{'branch_id':True},{'phone':'X'*41}):
            self.assertEqual(self.create(**data).status_code, 422)
        self.assertEqual(self.create(branch_id=99).status_code, 404)
        self.create(name='First'); self.create(name='Second')
        self.assertEqual(self.client.get('/customers?limit=1&offset=1').json()[0]['name'], 'First')
        self.assertEqual(self.update({'id':99,'name':'Missing','version':1}).status_code, 404)

    def test_audit_failure_rolls_back_customer_and_retry_key(self):
        with self.fixture.connection.transaction():
            self.fixture.connection.execute('ALTER TABLE customer_changes ADD CHECK (changed_by < 0)')
        self.assertEqual(self.create().status_code, 500)
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM customers'), [(0,)])
        self.assertEqual(self.fixture.rows('SELECT count(*) FROM stock_requests'), [(0,)])
