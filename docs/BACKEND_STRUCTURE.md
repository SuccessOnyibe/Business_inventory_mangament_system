# Backend structure

`main.py` creates the FastAPI application, registers routers, adds security headers
and allowed-host middleware, provides home/health endpoints, and serves `/app/`.
Run it the same way as before: `uvicorn main:app --reload` from `backend`.

A **router** groups related API endpoints. Registering it with `include_router`
makes those endpoints part of the same application. The existing authentication
and accounts modules already use this pattern; the other workflows now follow it.
Request models stay beside the routes that accept them.

| Module | Responsibility |
| --- | --- |
| `auth.py`, `accounts.py` | Login, sessions, permissions and user administration |
| `products.py` | Shared product catalogue, barcode validation and pricing |
| `inventory.py` | Branches, available balances and movement history |
| `stock_receipts.py` | Supplier deliveries and receiving history |
| `stock_transfers.py` | Dispatch, in-transit history and delivery confirmation |
| `sales.py` | Single-item sales, checkout and sale receipts |
| `sale_corrections.py` | Returns, voids and correction receipts |
| `customers.py` | Branch customer directory and contact changes |
| `credit.py` | Credit balances, repayments and payment reversals |
| `reconciliations.py` | Daily counts, reviews and discrepancy follow-up |
| `stock_adjustments.py` | Audited stock corrections |
| `reports.py` | Financial report and CSV export |

Shared functions have small, separate homes:

- `stock_requests.py`: reserve and finish retry keys inside the caller's transaction.
- `receipt_helpers.py`: format sale/correction receipts and attach correction details.
- `credit_helpers.py`: calculate credit totals for receipts, repayments and returns.
- `reconciliation_helpers.py`: compare daily snapshots and interpret discrepancy states.
- `database.py`: open and close PostgreSQL connections, as before.

Helpers do not import routers or `main.py`. This avoids circular imports: for
example, a sale receipt can show repayment totals without importing the repayment
router back into the sales router.

No database migration, endpoint URL change or frontend update is needed. Existing
SQL, explicit transactions, locks, retry behavior, validation and permissions are
preserved. Swagger `/docs` now groups endpoints by workflow.

Tests override the authentication dependency from `auth.py`. Database fixtures
patch the connection in every workflow module so tests remain on their isolated
PostgreSQL connection. Clock patches target the module that uses that clock.
