# Authentication and Initial Permissions

## Create your first account

The authentication migration has been applied to the current development database.
For a new database, apply stock_requests_schema.sql, auth_schema.sql, then
account_management_schema.sql, branch_transfers_schema.sql, then
sales_pricing_schema.sql, sale_payments_schema.sql, reconciliation_schema.sql, then
checkout_schema.sql, sale_corrections_schema.sql, then reports_adjustments_schema.sql
in that order.
There are no default accounts or passwords and there is no public signup endpoint.

From the project root in PowerShell:

```powershell
.\backend\.venv\Scripts\python.exe backend\create_user.py owner --role admin
```

Enter and confirm your own password privately when prompted. Passwords must have
12-128 characters. Usernames use 3-50 lowercase letters, numbers, dots, underscores,
or hyphens, and start with a letter or number. The terminal does not echo passwords.
To create other accounts, choose a different username and use --role manager or
--role salesperson. This local command requires access to the database credentials;
it is an administrator tool, not an API endpoint available to sales staff.

## Log in and use the API

Start the API from backend as usual, then open /docs.
POST /auth/login accepts JSON:

```json
{"username": "owner", "password": "your privately chosen password"}
```

The response contains access_token, token_type (bearer), and expires_in (28800
seconds, or eight hours). In /docs, click Authorize and enter the access_token.
For other clients, send Authorization: Bearer followed by the token.

GET /auth/me returns your ID, username, and role. POST /auth/logout revokes only
the current session and returns 204. Expired, revoked, missing, or invalid tokens
return 401. Log in again after a session expires. Keep tokens private.

Stock receipts and transfers still require a separate Idempotency-Key UUID header.
The successful request is owned by the signed-in user. Another user cannot replay
its saved response; an existing key belonging to someone else returns 409.
Legacy request keys with no owner remain reserved and cannot be replayed.

## Initial role rules

| Operation | Admin | Manager | Salesperson |
|---|---|---|---|
| List branches/products/inventory/movements | Yes | Yes | Yes |
| Create/update/deactivate products | Yes | Yes | No |
| Receive stock and transfer stock | Yes | Yes | No |
| Record whole-unit sales | Yes | Yes | Assigned branch |
| Create/edit customers | Yes | Yes | Assigned branch |
| Record credit sales and Cash/POS repayments | Yes | Yes | Assigned branch |
| Change customer active/inactive status | Yes | Yes | No |
| Reverse repayment entries | Yes | Yes | No |
| Set catalogue selling prices | Yes | Yes | No |
| Set maximum discount percentages | Yes | No | No |
| Submit daily cash/POS counts | Yes | Yes | Assigned branch |
| Review daily cash/POS counts | Yes | Yes | No |
| Approve/record sale voids and returns | Yes | Yes | No |
| Read correction records/receipts | Yes | Yes | Assigned branch |
| Investigate/resolve count discrepancies | Yes | Yes | No |
| Read financial reports / export CSV | Yes | Yes | No |
| Record stock counts/damage/expiry/corrections | Yes | Yes | No |
| Read investigation/stock adjustment history | Yes | Yes | Assigned branch |
| Inspect own profile and log out | Yes | Yes | Yes |

Insufficient permission returns 403. Current role and active status are read from
the database on every authenticated request, so changes affect existing sessions.
Admins and Managers can read all branches. Salespersons are restricted to their
assigned branch for branch-specific data; an unassigned account receives 403.
Products remain a shared catalogue. See BRANCHES_AND_TRANSFERS.md for assignment
and delivery confirmation. Destination Salespersons can confirm incoming transfers.
The root status endpoint and login remain public. Password-reset endpoints are
not implemented. Account management is available through the Admin-only routes below.

## Manage accounts as Admin

After logging in as Admin and authorizing in /docs:

- GET /users lists account IDs, usernames, roles, and active status. It supports
  limit (1-500, default 100) and offset (default 0).
- POST /users creates an active account. Supply username, password (12-128
  characters), and role (admin, manager, or salesperson). Duplicate usernames return 409.
- PATCH /users/{user_id} changes role and/or is_active. Empty updates return 400,
  invalid/null/unknown fields return 422, and missing users return 404.

For example, PATCH /users/3 with {"is_active": false} deactivates account 3 and
revokes all its sessions. Reactivating it does not restore those sessions; the
person must log in again. Password hashes and session tokens never appear in
account-management responses. Managers and Salespersons receive 403 on these routes.

Active Salespersons require a valid branch_id on creation/update. Use PATCH /users/3
with {"branch_id": 2} to assign a branch. Inactive legacy accounts can remain unassigned.

The last active Admin cannot be demoted or deactivated (409). Account changes are
serialized in PostgreSQL, so two simultaneous requests cannot remove both remaining
Admins. These checks protect the API workflow; direct database edits bypass them.

## Failed-login throttling

Five failed attempts for the same username within 15 minutes lock that username
for 15 minutes from the fifth failure. The five failures return 401; subsequent
attempts, including correct passwords, return 429 with Retry-After in seconds.
Successful login clears the failure count. Attempts after an expired failure
window start a new count. Unknown usernames are treated the same way as real ones.
Counters live in login_attempts, so separate API workers share the same limit.
An existing session is not revoked by failed login attempts.

This is a per-username limit, not an IP-wide limit. Someone can deliberately lock
a known username for 15 minutes. Hosting-layer IP throttling and cleanup of old
counter rows remain future work.

## How storage works

Passwords are stored as salted scrypt hashes, never plaintext. Each password gets
a fresh random salt, so matching passwords do not produce matching stored values.
Login verifies the hash and creates a random session token. Only a SHA-256 digest
of that token is stored in user_sessions; the original token is returned once.
Sessions expire after eight hours and can be revoked by logout.

Before internet deployment, add IP-based rate limiting and HTTPS at the hosting layer.
Password reset, expired-session cleanup, and branch-specific permissions remain
future work. This stage is intended for continued local backend development.

## Tests

Run the existing unittest commands from DEVELOPMENT_LOG.md. Stock tests override
authentication to focus on stock behavior; test_auth.py separately exercises real
password checking, sessions, permissions, and request ownership using temporary
PostgreSQL tables. No test accounts are created in the business database.

## Cash ledger removed

Cash-ledger routes are removed for every role, including Admins/Managers. There
is no cash-movement entry or approval permission. Normal customer Cash/POS sale,
repayment and refund permissions remain unchanged.

Receipt history (`GET /stock-receipts`) requires authentication and uses the same
assigned-branch scope. Receiving with optional batch/expiry labels remains
Manager/Admin only. Apply receipt_batches_schema.sql after cash_movements_schema.sql.

Customer directory: authenticated staff can list contacts in their allowed branch
scope. Only Managers/Admins create or update/deactivate customers. Both writes
require Idempotency-Key UUIDs. Apply customers_schema.sql after receipt_batches_schema.sql.

## Credit permissions

Only Admins/Managers can create credit sales, record repayments and reverse
repayment entries. Salespersons can read credit invoices/balances/payment history
only in their assigned branch. Credit customer/order/repayment branch consistency
is also enforced by composite foreign keys. No public password-reset or email
service is configured; use the existing Admin account management process.


## Browser refresh

The frontend keeps its opaque bearer token in tab-scoped sessionStorage and calls
/auth/me after reload before showing account data. It never stores the password
or trusts a cached role. Refresh reuses the same server session and does not extend
its eight-hour expiry. Logout and 401 responses remove the saved token. Temporary
connection failures preserve it so a refresh can retry. If browser storage is
blocked, sign-in still works in memory and refresh requires sign-in again.
