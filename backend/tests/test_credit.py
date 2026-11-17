"""Credit revenue, actual collections, corrections and retry-safe balance changes."""
from datetime import datetime, timedelta
import os
import unittest
import uuid
from zoneinfo import ZoneInfo
import main
import auth
import test_stock


@unittest.skipUnless(os.getenv('RUN_POSTGRES_TESTS') == '1', 'Requires disposable PostgreSQL')
class CreditTests(unittest.TestCase):
    def setUp(self):
        self.f = test_stock.PostgresStockTests(); self.addCleanup(self.f.doCleanups); self.f.setUp()
        self.client = self.f.client
        with self.f.connection.transaction():
            self.customer = self.f.connection.execute("INSERT INTO customers (branch_id,name,created_by,updated_by) VALUES (1,'Credit farm',1,1) RETURNING id").fetchone()[0]
            self.f.connection.execute('UPDATE products SET selling_price=100 WHERE id=1')
        self.day = datetime.now(ZoneInfo('Africa/Lagos')).date().isoformat()

    def post(self, path, body, key=None):
        return self.client.post(path, json=body, headers={'Idempotency-Key':key or str(uuid.uuid4())})

    def sale(self, quantity=2, **changes):
        return self.post('/checkouts',dict(branch_id=1,items=[dict(product_id=1,quantity=quantity)],payment_method='credit',customer_id=self.customer,**changes))

    def pay(self, order, amount='50', method='cash', key=None):
        return self.post('/credit-repayments',dict(order_id=order['id'],amount=amount,payment_method=method),key)

    def totals(self):
        return self.client.get('/reconciliations/summary', params=dict(branch_id=1,business_date=self.day)).json()

    def report(self):
        return self.client.get('/reports/financial',params=dict(start_date=self.day,end_date=self.day)).json()['totals']

    def correction(self, order, **changes):
        return self.post('/sale-corrections',dict(receipt_type='checkout',receipt_id=order['id'],kind='void',reason='Documented correction',**changes))

    def test_credit_is_revenue_not_cash_then_repayments_are_not_new_revenue(self):
        response = self.sale(); self.assertEqual(response.status_code,201,response.text)
        order = response.json(); self.assertEqual(order['outstanding'],'200.00')
        self.assertEqual(self.totals()['expected_cash'],'0.00')
        self.assertEqual(self.report()['net_sales'],'200.00')
        key=str(uuid.uuid4()); payment=self.pay(order,key=key)
        self.assertEqual(payment.status_code,201,payment.text)
        self.assertEqual(self.pay(order,key=key).json(),payment.json())
        self.assertEqual(self.pay(order,'100','pos').status_code,201)
        totals=self.totals(); self.assertEqual((totals['expected_cash'],totals['expected_pos']),('50.00','100.00'))
        self.assertEqual(self.report()['net_sales'],'200.00')
        self.assertEqual(self.client.get('/credit-sales').json()[0]['outstanding'],'50.00')
        self.assertEqual(self.client.get('/credit-repayments').json()[0]['customer_name'],'Credit farm')
        self.assertEqual(self.pay(order,'51').status_code,409)

    def test_unpaid_return_reduces_debt_without_refund_and_paid_return_refunds(self):
        order=self.sale().json(); self.pay(order,'50')
        response=self.correction(order,refund_method='cash')
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual((response.json()['debt_reduction'],response.json()['refund_total']),('150.00','50.00'))
        receipt=self.client.get(f"/checkouts/{order['id']}").json()
        self.assertEqual((receipt['outstanding'],receipt['net_total']),('0.00','0.00'))
        self.assertEqual(self.report()['net_sales'],'0.00')
        self.assertEqual(self.totals()['expected_cash'],'0.00')
        self.assertEqual(self.pay(order,'1').status_code,409)

    def test_unpaid_void_needs_no_cash_method(self):
        order=self.sale().json(); response=self.correction(order)
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['debt_reduction'],'200.00')
        self.assertEqual(response.json()['refund_total'],'0.00')

    def test_repayment_void_is_signed_dated_audited_and_cannot_be_repeated(self):
        order=self.sale().json(); payment=self.pay(order).json()
        response=self.post(f"/credit-repayments/{payment['id']}/void",{'reason':'Entered wrong payment'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['amount'],'-50.00')
        self.assertEqual(response.json()['outstanding'],'200.00')
        self.assertEqual(self.totals()['expected_cash'],'0.00')
        self.assertEqual(self.post(f"/credit-repayments/{payment['id']}/void",{'reason':'Again'}).status_code,409)

    def test_permissions_customer_validation_and_payment_validation(self):
        self.assertEqual(self.client.post('/checkouts',json=dict(branch_id=1,items=[dict(product_id=1,quantity=1)],payment_method='credit'),headers={'Idempotency-Key':str(uuid.uuid4())}).status_code,422)
        with self.f.connection.transaction(): self.f.connection.execute('UPDATE customers SET is_active=FALSE')
        self.assertEqual(self.sale().status_code,409)
        with self.f.connection.transaction(): self.f.connection.execute('UPDATE customers SET is_active=TRUE')
        order=self.sale().json()
        main.app.dependency_overrides[auth.get_current_user]=lambda: {'id':1,'role':'salesperson','branch_id':1}
        self.assertEqual(self.sale().status_code,403)
        self.assertEqual(self.pay(order).status_code,403)
        main.app.dependency_overrides[auth.get_current_user]=lambda: {'id':1,'role':'salesperson','branch_id':2}
        self.assertEqual(self.client.get('/credit-sales').json(),[])
        self.assertEqual(self.client.get('/credit-repayments').json(),[])

    def test_later_day_collections_and_snapshot_staleness(self):
        order=self.sale().json()
        yesterday=datetime.now(ZoneInfo('Africa/Lagos'))-timedelta(days=1)
        with self.f.connection.transaction():
            self.f.connection.execute('UPDATE sale_orders SET created_at=%s',(yesterday,))
        count=self.post('/reconciliations',dict(branch_id=1,business_date=self.day,actual_cash='0',actual_pos='0'))
        self.assertEqual(count.status_code,201,count.text)
        self.assertEqual(self.pay(order).status_code,201)
        self.assertTrue(self.totals()['is_stale'])
        self.assertEqual(self.report()['net_sales'],'0.00')
        self.assertEqual(self.report()['repaid_cash'],'50.00')

    def test_failed_payment_rolls_back_retry_key(self):
        order=self.sale().json()
        with self.f.connection.transaction(): self.f.connection.execute('ALTER TABLE credit_repayments ADD CHECK(amount < 0)')
        self.assertEqual(self.pay(order).status_code,500)
        self.assertEqual(self.client.get('/credit-sales').json()[0]['outstanding'],'200.00')
        self.assertEqual(self.f.rows('SELECT count(*) FROM stock_requests'),[(1,)])

    def test_paid_refund_needs_method_and_prevents_later_payment_reversal(self):
        order=self.sale().json(); payment=self.pay(order,'50').json()
        self.assertEqual(self.correction(order).status_code,422)
        self.assertEqual(self.client.get('/credit-sales').json()[0]['outstanding'],'150.00')
        self.assertEqual(self.correction(order,refund_method='cash').status_code,201)
        self.assertEqual(self.post(f"/credit-repayments/{payment['id']}/void",{'reason':'Wrong payment'}).status_code,409)
        balance=self.client.get(f'/customers/{self.customer}/balance').json()
        self.assertEqual(balance['outstanding'],'0.00')
