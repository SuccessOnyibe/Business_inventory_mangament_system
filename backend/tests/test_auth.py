"""Authentication tests use temporary tables, including real password/session checks."""
import hashlib
import os
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

import auth
import accounts
import main
from create_user import NewUser
from pydantic import ValidationError
import test_stock


class PasswordTests(unittest.TestCase):
    def test_password_hash_is_salted_and_verified(self):
        first = auth.hash_password("a long test password")
        self.assertNotEqual(first, auth.hash_password("a long test password"))
        self.assertTrue(auth.verify_password("a long test password", first))
        self.assertFalse(auth.verify_password("wrong password", first))
        self.assertFalse(auth.verify_password("password", "invalid hash"))

    def test_account_validation_and_password_redaction(self):
        with self.assertRaises(ValidationError):
            NewUser(username="admin", password="short")
        with self.assertRaises(ValidationError):
            NewUser(username="INVALID USER", password="a long test password")
        self.assertNotIn("a long test password", repr(NewUser(username="admin", password="a long test password")))


@unittest.skipUnless(os.getenv("RUN_POSTGRES_TESTS") == "1", "PostgreSQL tests are opt-in")
class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the isolated schema setup, then remove its business-test auth override.
        fixture = test_stock.PostgresStockTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        self.connection = fixture.connection
        self.fixture = fixture
        override = patch.dict(main.app.dependency_overrides, {}, clear=True)
        override.start()
        self.addCleanup(override.stop)

        @contextmanager
        def test_connection():
            yield self.connection

        patcher = patch.object(auth, "db_connection", test_connection)
        patcher.start()
        self.addCleanup(patcher.stop)
        account_patcher = patch.object(accounts, "db_connection", test_connection)
        account_patcher.start()
        self.addCleanup(account_patcher.stop)
        self.password = "a long test password"
        with self.connection.transaction():
            self.connection.execute("UPDATE users SET password_hash = %s WHERE id = 1",
                                    (auth.hash_password(self.password),))
            for username, role in (("admin", "admin"), ("seller", "salesperson")):
                self.connection.execute("INSERT INTO users (username, password_hash, role, branch_id) VALUES (%s, %s, %s, %s)",
                                        (username, auth.hash_password(self.password), role, 1 if role == 'salesperson' else None))
        self.client = TestClient(main.app, raise_server_exceptions=False)

    def login(self, username="tester", password=None):
        return self.client.post("/auth/login", json={
            "username": username, "password": self.password if password is None else password})

    def headers(self, username="tester"):
        response = self.login(username)
        self.assertEqual(response.status_code, 200)
        return {"Authorization": "Bearer " + response.json()["access_token"],
                "Idempotency-Key": str(uuid.uuid4())}

    def test_business_routes_require_authentication(self):
        for route in ('/credit-sales','/credit-repayments','/customers/1/balance'):
            self.assertEqual(self.client.get(route).status_code,401)
        self.assertEqual(self.client.post('/credit-repayments',json={'order_id':1,'amount':'1','payment_method':'cash'}).status_code,401)
        self.assertEqual(self.client.get('/customers').status_code, 401)
        self.assertEqual(self.client.post('/customers', json={'branch_id':1,'name':'Farm'}).status_code, 401)
        self.assertEqual(self.client.post('/customers/1/update', json={'name':'Farm','is_active':True,'expected_version':1}).status_code, 401)
        self.assertEqual(self.client.get('/stock-receipts').status_code, 401)
        for route in ("/branches", "/products", "/inventory", "/stock-movements", "/auth/me", '/sales', '/reconciliations', '/checkouts', '/sale-corrections', '/stock-adjustments', '/discrepancy-events'):
            self.assertEqual(self.client.get(route).status_code, 401)
        for route, body in (
            ("/products", dict(name="Test", category="Feed", base_unit="bag")),
            ("/stock-receipts", dict(branch_id=1, product_id=1, quantity=1)),
            ("/stock-transfers", dict(source_branch_id=1, destination_branch_id=2, product_id=1, quantity=1)),
            ('/sales', dict(branch_id=1, product_id=1, quantity=1)),
        ):
            response = self.client.post(route, json=body, headers={"Idempotency-Key": str(uuid.uuid4())})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(self.client.patch("/products/1", json={"name": "Changed"}).status_code, 401)

    def test_login_me_and_hashed_session(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        token = response.json()["access_token"]
        result = self.client.get("/auth/me", headers={"Authorization": "Bearer " + token})
        self.assertEqual(result.json(), {"id": 1, "username": "tester", "role": "manager", "branch_id": None})
        stored = self.fixture.rows("SELECT token_hash FROM user_sessions")[0][0]
        self.assertNotEqual(stored, token)
        self.assertEqual(stored, hashlib.sha256(token.encode()).hexdigest())

    def test_wrong_unknown_and_inactive_login_are_identical(self):
        wrong = self.login(password="incorrect password")
        unknown = self.login(username="unknown")
        with self.connection.transaction():
            self.connection.execute("UPDATE users SET is_active = FALSE WHERE id = 1")
        inactive = self.login()
        self.assertEqual([wrong.status_code, unknown.status_code, inactive.status_code], [401] * 3)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json(), inactive.json())
        self.assertEqual(self.fixture.rows("SELECT COUNT(*) FROM user_sessions"), [(0,)])

    def test_logout_revokes_only_current_session(self):
        first, second = self.headers(), self.headers()
        self.assertEqual(self.client.post("/auth/logout", headers=first).status_code, 204)
        self.assertEqual(self.client.get("/auth/me", headers=first).status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers=second).status_code, 200)

    def test_expired_unknown_and_disabled_sessions_are_rejected(self):
        headers = self.headers()
        with self.connection.transaction():
            self.connection.execute("UPDATE user_sessions SET expires_at = NOW() - INTERVAL '1 second'")
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.get("/auth/me", headers={"Authorization": "Bearer invalid"}).status_code, 401)
        headers = self.headers()
        with self.connection.transaction():
            self.connection.execute("UPDATE users SET is_active = FALSE WHERE id = 1")
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)

    def test_salesperson_can_read_history_but_cannot_write(self):
        headers = self.headers("seller")
        self.assertEqual(self.client.get("/stock-movements", headers=headers).status_code, 200)
        for route, body in (
            ("/products", dict(name="Test", category="Feed", base_unit="bag")),
            ("/stock-receipts", dict(branch_id=1, product_id=1, quantity=1)),
            ("/stock-transfers", dict(source_branch_id=1, destination_branch_id=2, product_id=1, quantity=1)),
        ):
            self.assertEqual(self.client.post(route, json=body, headers=headers).status_code, 403)
        self.assertEqual(self.client.patch("/products/1", json={"name": "Changed"}, headers=headers).status_code, 403)
        self.assertEqual(self.fixture.snapshot(), ([(1, 1, 50)], []))

    def test_admin_and_manager_can_receive_and_transfer(self):
        for username in ("tester", "admin"):
            headers = self.headers(username)
            self.assertEqual(self.client.post("/stock-receipts", json=dict(branch_id=1, product_id=1, quantity=5),
                                              headers=headers).status_code, 201)
            headers["Idempotency-Key"] = str(uuid.uuid4())
            self.assertEqual(self.client.post("/stock-transfers", json=dict(source_branch_id=1, destination_branch_id=2,
                                                                           product_id=1, quantity=5), headers=headers).status_code, 201)

    def test_role_change_takes_effect_for_existing_session(self):
        headers = self.headers()
        with self.connection.transaction():
            self.connection.execute("UPDATE users SET role = 'salesperson' WHERE id = 1")
        self.assertEqual(self.client.post("/stock-receipts", json=dict(branch_id=1, product_id=1, quantity=1),
                                          headers=headers).status_code, 403)

    def test_saved_response_is_private_to_request_owner(self):
        headers = self.headers()
        body = dict(branch_id=1, product_id=1, quantity=10)
        self.assertEqual(self.client.post("/stock-receipts", json=body, headers=headers).status_code, 201)
        other = self.headers("admin")
        other["Idempotency-Key"] = headers["Idempotency-Key"]
        before = self.fixture.snapshot()
        self.assertEqual(self.client.post("/stock-receipts", json=body, headers=other).status_code, 409)
        self.assertEqual(self.fixture.snapshot(), before)

    def test_five_failures_lock_username_and_expiry_allows_login(self):
        for _ in range(5):
            self.assertEqual(self.login(password="wrong password").status_code, 401)
        blocked = self.login()
        self.assertEqual(blocked.status_code, 429)
        self.assertTrue(1 <= int(blocked.headers["retry-after"]) <= 900)
        self.assertEqual(self.fixture.rows("SELECT failures FROM login_attempts WHERE username = 'tester'"), [(5,)])
        self.assertEqual(self.fixture.rows("SELECT COUNT(*) FROM user_sessions"), [(0,)])
        with self.connection.transaction():
            self.connection.execute("UPDATE login_attempts SET locked_until = NOW() - INTERVAL '1 second', window_started_at = NOW() - INTERVAL '16 minutes'")
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.fixture.rows("SELECT failures FROM login_attempts WHERE username = 'tester'"), [(0,)])

    def test_success_resets_failures_and_usernames_are_independent(self):
        for _ in range(4):
            self.login(password="wrong password")
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.fixture.rows("SELECT failures FROM login_attempts WHERE username = 'tester'"), [(0,)])
        for _ in range(5):
            self.assertEqual(self.login(username="unknown").status_code, 401)
        self.assertEqual(self.login(username="unknown").status_code, 429)
        self.assertEqual(self.login().status_code, 200)

    def test_old_failure_window_resets(self):
        self.login(password="wrong password")
        with self.connection.transaction():
            self.connection.execute("UPDATE login_attempts SET failures = 4, window_started_at = NOW() - INTERVAL '16 minutes'")
        self.assertEqual(self.login(password="wrong password").status_code, 401)
        self.assertEqual(self.fixture.rows("SELECT failures FROM login_attempts WHERE username = 'tester'"), [(1,)])

    def test_only_admin_can_manage_accounts(self):
        for username in ("tester", "seller"):
            headers = self.headers(username)
            self.assertEqual(self.client.get("/users", headers=headers).status_code, 403)
            self.assertEqual(self.client.post("/users", headers=headers, json=dict(
                username="newuser", password=self.password, role="manager")).status_code, 403)
            self.assertEqual(self.client.patch("/users/1", headers=headers, json={"role": "admin"}).status_code, 403)
        self.assertEqual(self.client.get("/users").status_code, 401)

    def test_admin_create_list_and_duplicate_account(self):
        headers = self.headers("admin")
        body = dict(username="newuser", password=self.password, role="manager")
        created = self.client.post("/users", headers=headers, json=body)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(set(created.json()), {"id", "username", "role", "is_active", "branch_id"})
        self.assertEqual(self.client.post("/users", headers=headers, json=body).status_code, 409)
        listed = self.client.get("/users?limit=1&offset=1", headers=headers)
        self.assertEqual([user["username"] for user in listed.json()], ["admin"])
        self.assertEqual(self.login(username="newuser").status_code, 200)

    def test_account_input_validation(self):
        headers = self.headers("admin")
        self.assertEqual(self.client.patch("/users/999", headers=headers, json={"role": "manager"}).status_code, 404)
        self.assertEqual(self.client.patch("/users/1", headers=headers, json={}).status_code, 400)
        for body in ({"role": None}, {"role": "owner"}, {"is_active": "false"}, {"password": "ignored"}):
            self.assertEqual(self.client.patch("/users/1", headers=headers, json=body).status_code, 422)
        self.assertEqual(self.client.post("/users", headers=headers, json=dict(
            username="newuser", password="short", role="manager")).status_code, 422)

    def test_cannot_remove_last_active_admin(self):
        headers = self.headers("admin")
        for body in ({"role": "manager"}, {"is_active": False}):
            self.assertEqual(self.client.patch("/users/2", headers=headers, json=body).status_code, 409)
        self.assertEqual(self.client.get("/auth/me", headers=headers).json()["role"], "admin")
        self.assertEqual(self.client.patch("/users/1", headers=headers, json={"role": "admin"}).status_code, 200)
        self.assertEqual(self.client.patch("/users/2", headers=headers, json={"role": "manager"}).status_code, 200)
        self.assertEqual(self.client.get("/users", headers=headers).status_code, 403)

    def test_deactivation_revokes_sessions_even_after_reactivation(self):
        seller_headers = self.headers("seller")
        admin_headers = self.headers("admin")
        self.assertEqual(self.client.patch("/users/3", headers=admin_headers, json={"is_active": False}).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=seller_headers).status_code, 401)
        self.assertEqual(self.client.patch("/users/3", headers=admin_headers, json={"is_active": True}).status_code, 200)
        self.assertEqual(self.client.get("/auth/me", headers=seller_headers).status_code, 401)
        self.assertEqual(self.login("seller").status_code, 200)

    def test_admin_assigns_and_validates_salesperson_branch(self):
        headers = self.headers('admin')
        body = dict(username='branchseller', password=self.password, role='salesperson')
        self.assertEqual(self.client.post('/users', headers=headers, json=body).status_code, 422)
        self.assertEqual(self.client.post('/users', headers=headers, json={**body, 'branch_id': 99}).status_code, 404)
        created = self.client.post('/users', headers=headers, json={**body, 'branch_id': 2})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()['branch_id'], 2)
        self.assertEqual(self.client.patch('/users/3', headers=headers, json={'branch_id': None}).status_code, 422)
        self.assertEqual(self.client.patch('/users/3', headers=headers, json={'branch_id': 2}).status_code, 200)
        self.assertEqual(self.client.patch('/users/1', headers=headers, json={'role': 'salesperson'}).status_code, 422)

    def test_salesperson_branch_scope_cannot_be_overridden(self):
        admin_headers = self.headers('admin')
        for branch_id in (1, 2):
            admin_headers['Idempotency-Key'] = str(uuid.uuid4())
            self.assertEqual(self.client.post('/stock-receipts', headers=admin_headers, json=dict(
                branch_id=branch_id, product_id=1, quantity=10)).status_code, 201)
        headers = self.headers('seller')
        branches = self.client.get('/branches', headers=headers).json()
        self.assertEqual([row['id'] for row in branches], [1])
        for route in ('/inventory', '/stock-movements'):
            response = self.client.get(route, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual({row['branch_id'] for row in response.json()}, {1})
            self.assertEqual(self.client.get(route + '?branch_id=2', headers=headers).status_code, 403)
            self.assertEqual({row['branch_id'] for row in self.client.get(route, headers=admin_headers).json()}, {1, 2})

    def test_unassigned_salesperson_has_no_branch_access(self):
        headers = self.headers('seller')
        with self.connection.transaction():
            self.connection.execute('UPDATE users SET branch_id = NULL WHERE id = 3')
        for route in ('/branches', '/inventory', '/stock-movements', '/stock-transfers'):
            self.assertEqual(self.client.get(route, headers=headers).status_code, 403)

    def test_dispatch_waits_for_assigned_receiver_and_confirmation_is_repeat_safe(self):
        admin_headers = self.headers('admin')
        dispatched = self.client.post('/stock-transfers', headers=admin_headers, json=dict(
            source_branch_id=1, destination_branch_id=2, product_id=1, quantity=10))
        self.assertEqual(dispatched.status_code, 201)
        self.assertEqual(dispatched.json()['status'], 'in_transit')
        self.assertEqual(self.fixture.snapshot(), ([(1, 1, 40)], [(1, -10, 'transfer_out', None)]))
        route = '/stock-transfers/' + str(dispatched.json()['transfer_id']) + '/confirm'
        seller_headers = self.headers('seller')
        self.assertEqual(self.client.post(route, headers=seller_headers).status_code, 403)
        self.assertEqual(self.client.patch('/users/3', headers=admin_headers, json={'branch_id': 2}).status_code, 200)
        confirmation = self.client.post(route, headers=seller_headers)
        self.assertEqual(confirmation.status_code, 200)
        before = self.fixture.snapshot()
        self.assertEqual(self.client.post(route, headers=seller_headers).json(), confirmation.json())
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(before[0], [(1, 1, 40), (2, 1, 10)])
        self.assertEqual(self.client.get('/stock-transfers', headers=seller_headers).json()[0]['status'], 'received')

    def test_confirm_unknown_transfer_and_restrict_list_filters(self):
        headers = self.headers('seller')
        self.assertEqual(self.client.post('/stock-transfers/999/confirm', headers=headers).status_code, 404)
        self.assertEqual(self.client.post('/stock-transfers/0/confirm', headers=headers).status_code, 422)
        self.assertEqual(self.client.get('/stock-transfers?branch_id=2', headers=headers).status_code, 403)

    def test_salesperson_sale_uses_assigned_branch_and_discount_limit(self):
        with self.connection.transaction():
            self.connection.execute('UPDATE products SET selling_price = 100, max_discount_percent = 5 WHERE id = 1')
        headers = self.headers('seller')
        body = dict(branch_id=1, product_id=1, quantity=1, unit_price='95.00', payment_method='pos')
        self.assertEqual(self.client.post('/sales', headers=headers, json=body).status_code, 201)
        headers['Idempotency-Key'] = str(uuid.uuid4())
        self.assertEqual(self.client.post('/sales', headers=headers, json={**body, 'branch_id': 2}).status_code, 403)
        self.assertEqual(self.client.post('/sales', headers=headers, json={**body, 'unit_price': '94.99'}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
