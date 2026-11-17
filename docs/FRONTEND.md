# Local Inventory Frontend

New screens: Reports & CSV (Manager/Admin), Stock adjustments (Manager/Admin
entry and branch-scoped history), and investigation/resolution within Daily
reconciliation. See REPORTS_RESOLUTIONS_AND_STOCK_ADJUSTMENTS.md for exact rules.

## Open the application

From the project root in PowerShell:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open http://127.0.0.1:8000/app/ and sign in with your existing account. The frontend
uses HTML, CSS, and vanilla JavaScript, served by FastAPI from frontend/. No npm
installation, separate frontend server, hosting account, or CORS configuration is
needed. /docs still provides API testing. The root / remains the API status route.

## Daily workflows

- Inventory: view available balances. Admin/Manager can choose Add stock to a branch, select branch/product, enter whole units, and save.
- Products & pricing: Admin/Manager can add items with any name/category/base unit,
  set prices, edit products, and deactivate them. Only Admin sees discount controls.
  Receive inventory after adding a product; adding a catalogue item does not add stock.
- Sales: add products to the editable cart, then complete one Cash/POS purchase.
  Each item's price follows its Admin discount limit. Customer/notes are optional.
  Saved receipts and purchase history offer Print receipt / Save as PDF, with
  branch, salesperson, items, payment, and Lagos date/time. See MULTI_PRODUCT_CHECKOUT.md.
- Transfers: Admin/Manager dispatch stock. The destination Salesperson (or
  Admin/Manager) confirms after arrival. Dispatch and receipt timestamps are visible.
- Accounts: Admin can create users, assign branches, change roles, and deactivate
  accounts. Last-active-Admin protection remains enforced by the API.
- Daily reconciliation: staff submit actual cash/POS counts by branch/date; Managers
  and Admins review them. Original totals, differences, notes, and timestamps are
  retained. Later sales require a new revision. See DAILY_RECONCILIATION.md.
- Voids/returns: Managers/Admins use Correct sale in purchase history. Returns
  restore only resellable quantities; voids reverse untouched receipts in full.
  Corrections have printable records, approver/reason/date, and refund-day net totals.
  See SALE_VOIDS_AND_RETURNS.md. Pending correction retries use the same tab storage.

Salespersons see only their assigned branch's stock, sales, and transfer records.
Products are shared catalogue data; their pricing fields are read-only for Salespersons.
Admin/Manager can filter all branches or choose one. Sales and transfer history use
100 records per page; the in-transit summary describes the currently loaded list.

All event dates display in Africa/Lagos (WAT, UTC+1), including time. The API stores
timezone-aware timestamps. Backend permissions apply even if someone edits the page.

## Cash and POS recording

New sales require payment_method: cash or pos. Select the actual method after cash
is collected or the POS terminal confirms payment. This records the operator's
reported method; it does not communicate with the terminal or verify settlement.
Historical sales with no method show Not recorded. Split payments, partial payments,
POS references, refunds, and financial reconciliation are future stages.

## Retries and sessions

Login tokens stay only in browser memory. A reload requires signing in again;
logout revokes the current server session. Passwords are not stored by application code.
The browser's own password manager may separately offer to save credentials.

Before submitting a sale, receipt, or dispatch, the page saves its request UUID and
body in tab-scoped sessionStorage, partitioned by account ID. If the response is
lost, the form is locked and its button becomes Retry saved request. Retry it to
retrieve the original result without duplicate stock changes. Pending requests also
restore after reload and signing back in with the same account. Do not close the
tab or clear its storage while a request is unconfirmed; this removes the local key.
This tab storage contains transaction details, never your token or password.

Product/account creation is not idempotent. After an uncertain network error, refresh
the list to check the result before submitting again. Delivery confirmation itself
is repeat-safe. Lists that fail to refresh after saving do not resubmit the change.

## Verification

Backend tests include cash/POS validation, unknown historical methods, retries,
rollback, and public static-file access without exposing backend files.
tests/ui_smoke.mjs tests Chrome through its DevTools protocol with no extra Node
packages. tests/prepare_ui_test.py creates a fresh inventory_ui_test_* database only
on the disposable PostgreSQL instance at 127.0.0.1:55439; it refuses the usual server.
The browser harness expects UI_TEST_URL=http://127.0.0.1:58541, a headless test Chrome
on port 9223, and UI_TEST_PASSWORD for its isolated accounts. Never use real accounts
or the business database for these write tests. Test processes are stopped after QA.

The browser checks product/account creation, stock receiving, POS/Cash sales,
lost-response retry across reload, dispatch/receiving confirmation, branch scope,
literal rendering of product text, and mobile width. This is a local application;
deployment and hosting have not been configured.

## Cash ledger removed

Cash ledger and all movement-entry routes have been removed for every role.
Customer Cash/POS payments, repayments, refunds and historical report integrity
are unchanged. See CASH_MOVEMENTS.md for archival storage notes.

## Delivery batch labels

Inventory receiving now accepts optional batch numbers and exact expiry dates.
The delivery history shows these labels, receiving user and Lagos timestamp.
Its quantities are received amounts, not remaining batch balances. Sales still
use total product stock; check physical labels before selling. See
[Batch and expiry labels](BATCHES_AND_EXPIRY.md) for the staged rollout.

## Customers

The Customers tab lists branch-scoped contacts. Managers/Admins can add, edit or
deactivate records; Salespersons can only view their assigned branch. Credit invoices and repayments are in the separate Customer credit tab. See [Customer credit](CUSTOMER_CREDIT.md)
for the confirmed business rules and the next accounting stage.

## Credit and release operations

Managers/Admins can record full credit sales for active registered customers,
then record later Cash/POS repayments and print receipts in Customer credit.
Credit corrections reduce unpaid debt before paying any actual refund.
Customer balances include all invoices, independent of the visible history page.
See [Customer credit](CUSTOMER_CREDIT.md) and [staff instructions](OPERATIONS_GUIDE.md).

The read-only release check, local launcher, health/security settings and daily
backup schedule are described in [Deployment](DEPLOYMENT.md). Remote hosting
remains unconfigured until a host/domain and private off-device storage are chosen.

## Departments and till

Inventory/catalogue have category sections and filters. Sales uses product
buttons, search/optional scanner input and a basket beside payment controls.
See [Categories and POS](CATEGORIES_AND_POS.md) for use and barcode setup.

## Layout regression checks

`backend/tests/ui_layout.mjs` checks every screen stays inside main and to the
right of the desktop sidebar, with no page-wide horizontal overflow. It exercises
1440px desktop, 1280px at 1.5x pixel density, 960px at 2x density, tablet and phone
sizes. These approximate browser zoom layout sizes rather than changing Chrome's
UI zoom setting. Deep scrolling/focusing controls and navigation are included.
Long names/barcodes are seeded only into the disposable database.

On this Windows development environment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File backend/tests/run_ui_checks.ps1 -Suite layout
powershell -NoProfile -ExecutionPolicy Bypass -File backend/tests/run_ui_checks.ps1 -Suite smoke
```

The runner requires the existing dedicated temporary PostgreSQL cluster,
PostgreSQL 17 tools, Chrome and Node. It refuses occupied test ports or an already
running cluster. It prepares a fresh guarded database on port 55439, serves only
on 58541, prints its temporary artifact/log folder and stops processes it started.
A static HTML nesting test also protects all screens from escaping main through
stray closing tags. No real business transactions are sent by either suite.

## Product management access

Manage products follows Add stock in the sidebar. Add/Edit forms are above the catalogue.
Inventory offers Create new product/Edit product buttons plus per-row edit actions for
Admins/Managers. No scrolling through product groups is needed to find the forms.


## Add delivered stock to a specific branch

1. Choose **Add stock** in the sidebar, or **Add stock to a branch** on Inventory.
2. Select the **branch receiving the goods**.
3. Select the product and enter the quantity delivered, in its base unit (for example, bags).
4. If the product does not exist, choose **Product not in the list? Create it here**.
   Save its name, category, unit and selling price. You return to the delivery form
   with the new product selected, keeping your branch and quantity. You can also
   go back without creating a product.
5. Optionally expand batch, expiry and notes. Check the summary and select
   **Add stock to branch**. This saves a delivery and increases only that branch's stock.
6. The confirmation shows the branch, received quantity and new stock balance.
   Choose **View this branch's stock** to see the filtered inventory.

Product details belong to the shared catalogue; saving them does not create stock.
For a product created directly in Manage products, **Add stock for this product**
opens the delivery form. Existing request keys still protect delivery retries.
Only Admins/Managers can create products and receive stock. Salespersons continue
using their assigned branch. No schema change is required for this workflow.
