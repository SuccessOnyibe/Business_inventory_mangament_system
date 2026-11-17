# First-release status — 15 November 2026, Africa/Lagos

## Completed locally

- Customer credit checkout: Manager/Admin only, full amount owed, active customer
  in the same branch, atomic stock deduction and immutable receipt snapshots.
- Partial Cash/POS repayments, complete customer balances, signed payment-entry
  reversals, concurrent overpayment protection, retry safety and printable receipts.
- Credit returns/voids: unpaid debt reduction first, actual refund of any paid
  portion, stock restoration only for resellable returns, preserved audit history.
- Credit revenue/collections separated in financial reports/CSV and daily counts.
  Later payments/refunds/reversals use their actual Lagos posting dates.
- Security headers, frontend content policy, production host allowlisting,
  connection timeout, public liveness and generic database readiness probes.
- Read-only release checker, two-worker loopback release launcher, HTTPS proxy
  example, staff guide and business acceptance walkthrough.
- Current-user daily backup task installed at 02:00 WAT. Actual task invocation
  succeeded (LastTaskResult 0), followed by a full isolated restore verification.
  Next scheduled run observed: 16 November 2026 at 02:00 WAT.

## Verification evidence

- Full backend suite: **165 tests passed**, including real PostgreSQL constraints,
  transaction rollbacks, parallel credit repayments, permissions and backup tests.
- Complete Chrome walkthrough passed credit checkout, repayments, payment reversal,
  debt/refund split, unchanged repayment-day revenue, existing operations and mobile
  layout. Focused credit/release tests were repeated after final receipt changes.
- Two-worker release launcher passed live read-only `/health/ready`, `/app/` and
  security-header checks on port 8001; its owned preview processes were then stopped.
  The existing development server was not replaced or stopped.
- Credit schema applied only after a verified pre-migration backup. Business
  inventory balances and record counts remained unchanged. No real sample credit
  sales, customers, repayments or refunds were created.
- Pre-migration archive: `FAS-backup-20261115T192825Z-e2d2be58e477467c90c220297ffb5e08`.
- Post-migration archive: `FAS-backup-20261115T192828Z-e1eae1cbe43d41e5aac96e1c7a298973`.
- Actual scheduled archive: `FAS-backup-20261115T192908Z-b68399895d1c48c39a76db682b1542c0`.
  These are in the ignored backups folder. All three were restore-verified on the
  disposable server. Restore-created databases were removed and that server stopped.
- Read-only release check: no blocking errors; warning that some active products
  need selling prices. No prices were guessed or changed.

## Requires owner/infrastructure choices

- Enter correct prices for unpriced products and confirm physical stock, branch
  assignments, opening cash and staff walkthrough sign-off.
- Identify any pre-existing customer debts and approve a separate opening-debt
  migration. Current credit accounting starts with newly recorded credit sales;
  it does not infer debts from historical paid receipts.
- Choose/provision an always-on host and domain for branch access. DNS, TLS,
  remote device connectivity and service startup on that host cannot be verified
  without that infrastructure. Caddy/Docker are not installed on this PC. The
  provided HTTPS proxy configuration is prepared, not deployed or executed.
- Choose private encrypted off-device backup storage and retention. Nothing is
  uploaded to an external account. Local archives are not encrypted by this tool.
- This PC's backup task needs it awake and this user signed in. That limitation
  remains until an always-on host/service-account schedule is provisioned.

This is a locally verified release candidate, not a claim that public deployment
or business acceptance has happened. See DEPLOYMENT.md and OPERATIONS_GUIDE.md.

## Cash workflow update

Staff cash requests and approval controls are removed. Cash ledger is available
only to Admins/Managers for direct confirmed entries. The backend denies staff
cash requests/direct entries. Legacy tables/history and finance calculations
remain intact; no migration or real cash entry was made. All 167 backend tests
and the complete browser suite passed after this change.

## Department and POS update

Inventory/catalogue now group Feeds, Veterinary medication, Poultry equipment
and Other products. The till offers category/product buttons, basket, fixed
desktop payment controls and optional barcode entry. The 170-test backend suite,
focused readiness/barcode tests and full desktop/mobile Chrome checks passed.
The barcode migration preserved product classifications, stock and prices.
Updated backup FAS-backup-20261115T213111Z-9225e5c424ae4ad784546f0ba7b1df89 passed
isolated restore verification. Physical scanner hardware was not tested; enter
actual product codes before using a keyboard-style scanner.

## 16 November layout repair

Fixed malformed Sales closing tags that detached later screens from main and
placed their left edges behind the fixed sidebar. Navigation now starts at the
new screen's heading; form widths, table containment and long barcode wrapping
are protected. Three frontend unit tests and 55 layout/viewport combinations
passed, with screenshots checked at the user's 150%-equivalent display size.
No business data or database schema was changed.

## 16 November: cash ledger removed; product management made prominent

Cash ledger, including Admin/Manager entry and all old APIs, is removed. Archival
rows are retained solely to preserve historical reports. Customer Cash/POS sale,
repayment and refund workflows remain. Manage products is second in navigation;
Add/Edit forms come first, with additional Inventory shortcuts and row edit
buttons. The full 163-test suite and complete browser workflow passed. No business
data or database schema was changed. This supersedes earlier cash-entry features.


## Backend organization ? 17 November 2026, Africa/Lagos

Workflow routes and their request models now live in separate APIRouter modules,
following auth/accounts. main.py retains application infrastructure only. Shared
helpers avoid circular imports. API contract comparison passed, with only new
documentation tags; all 165 backend tests passed on disposable PostgreSQL.
No database migration is required. See [backend structure](BACKEND_STRUCTURE.md).

Browser smoke checks also passed for product creation, branch receiving, checkout,
transfers, credit, repayments, returns, reports, adjustments, retries and mobile layout.
