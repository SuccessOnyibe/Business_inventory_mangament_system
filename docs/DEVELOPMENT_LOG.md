# Development Log

## Project
Family Business Inventory Management System

## Current Phase
Backend Development: Inventory Management

## Latest Change: Alphabetical Products Within Categories

Recorded: 2026-11-16 17:02 WAT (Africa/Lagos, UTC+1).

- Inventory, Manage products and till cards now show A-Z products within each
  existing category; selectors are alphabetical too. Names ignore case and sort
  embedded numbers naturally. Repeated stock rows use branch names as tie-breaks.
- Sorting uses filtered/copied arrays, preserving product data and receipt/cart
  ordering. No business database writes or schema changes.
- Browser assertions passed for all four categories across the three displays,
  followed by all 50 layout/viewport combinations on isolated fixtures.

## Previous Change: Remove Cash Ledger and Expose Product Management

Recorded: 2026-11-16 16:41 WAT (Africa/Lagos, UTC+1).

- User clarified that the entire cash ledger is unwanted. Removed its navigation,
  screen, entry logic, all API routes and request/decision models for every role.
  This supersedes the earlier Admin/Manager-only cash-entry implementation.
- Kept archival tables/snapshot effects so old financial records are not rewritten.
  No business data or database schema was changed. Customer Cash/POS payments,
  credit repayments, refunds and reconciliation remain operational.
- Manage products is now second in the sidebar. Add/Edit forms precede catalogue
  tables; Inventory has Add product/Edit product shortcuts and each row has an
  edit action for Admins/Managers. Read-only Salesperson access is unchanged.
- Full 163-test backend suite and complete browser workflow passed on isolated
  data, including retired endpoints returning 404 and product shortcut discovery.
- Added optional backend checks to the reusable UI runner. See CASH_MOVEMENTS.md
  for retirement notes and OPERATIONS_GUIDE.md for the current product workflow.

## Previous Fix: Screens Clipped Behind the Sidebar

Recorded: 2026-11-16 15:56 WAT (Africa/Lagos, UTC+1).

- Reproduced the user's screenshots with a failing browser containment assertion:
  Products headings/forms began at x=25 while main began beyond the sidebar.
- Fixed an extra closing div after the Sales receipt and the missing closing div
  for its correction-history card. Those tags had caused the browser to move
  subsequent screens outside main/workspace. Reformatted Sales markup for review.
- New navigation resets page and internal table horizontal scroll instead of
  carrying a deep scroll position into another screen. Constrained form/grid
  minimum widths and wide table wrappers, kept the sidebar in its own layer,
  and wrapped long barcode text inside product cards.
- Added a markup regression test that rejects mismatched tags or screens outside
  main. All three frontend unit tests passed. Added a dedicated layout suite:
  55 page/viewport combinations passed, including 150%/200% zoom-equivalent sizes,
  focused controls, bottom scroll and all 11 screens. Inspected screenshot evidence
  for Accounts and Products at the scale shown by the user.
- Added a reusable Windows isolated UI runner. This fix changes frontend layout
  only; no business database writes, schema changes or price/stock changes.
- Earlier UI checks covered transactions and page width but missed incorrect
  screen ancestry. The new containment and markup checks cover that failure.

## Previous Milestone: Product Departments and Supermarket-style Till

Validation recorded: 2026-11-15 22:31 WAT (Africa/Lagos, UTC+1).

- Grouped Inventory and Products & pricing into Feeds, Veterinary medication,
  Poultry equipment and Other products, with category counts and search. Existing
  Feed/Medicine/Vaccine/Equipment values are displayed without rewriting them.
- Added department product buttons and barcode/name/item-number search beside a
  basket and payment panel. Desktop keeps total/completion visible while basket
  fields scroll. Mobile stacks panels. Manual entries, discounts and receipts stay
  available; the till retains branch and search focus for the next customer.
- Optional unique product barcodes preserve leading zeroes. Manager/Admin product
  APIs handle collisions atomically; omitted codes are preserved and null clears.
  Keyboard-style scanner Enter and explicit #item numbers add one unit to basket.
- Full 170-test backend suite passed; focused barcode/readiness checks and full
  Chrome desktop/mobile workflows passed again after layout refinements. Inspected
  1440px desktop screenshots and measured basket/payment geometry.
- Verified pre-migration backup; applied product_barcodes_schema.sql; verified
  post-migration backup FAS-backup-20261115T213111Z-9225e5c424ae4ad784546f0ba7b1df89.
  Stored categories, names, units, prices and inventory balances were unchanged.
  No real test transactions or guessed barcodes were created.
- Read-only release check has no errors; some active products still need owner
  prices. Physical barcode scanner testing still needs actual hardware/codes.
- See [department/POS guide](CATEGORIES_AND_POS.md) for staff use and schema details.

## Previous Milestone: Remove Staff Cash Requests

Recorded: 2026-11-15 21:34 WAT (Africa/Lagos, UTC+1).

- User removed the staff cash-request requirement. Removed request/decision forms
  and request list from the frontend; Cash ledger is now Admin/Manager only.
- Added direct confirmed cash recording through POST /cash-movements with one
  atomic audit/posting/retry transaction. No separate user-facing approval step.
- Staff are denied by the backend for both direct entries and legacy request
  creation. Legacy manager APIs are hidden from generated docs for compatibility.
- Preserved tables/history and reporting calculations; no database migration or
  business cash writes. Read-only inspection found zero pending cash requests.
- All 167 backend tests and the complete browser suite passed, including staff
  cash UI removal, direct posting/retries and rollback cases.
- Updated cash, permissions, walkthrough and staff instructions to the new policy.

## Previous Milestone: Credit Accounting and Local Release Preparation

Validation recorded: 2026-11-15 20:56 WAT (Africa/Lagos, UTC+1).

- Implemented full-owed Manager/Admin credit sales, partial Cash/POS repayments,
  current customer balances, signed repayment reversals, and debt/refund-aware
  sale corrections. Branch and receipt locks protect concurrent balances.
- Reports/CSV separate credit revenue and actual collections. Daily snapshots
  track repayments/reversals; receipts show debt, actual refunds and timestamps.
- Added connection timeout, security headers/content policy, host allowlisting,
  liveness/readiness probes, read-only release checks and a two-worker launcher.
- All 165 backend tests and full browser workflows passed on disposable databases.
  Focused credit/release checks passed again after final receipt metadata changes.
- Verified backup before credit schema migration; stock balances and existing
  business record counts were unchanged. No real test financial entries created.
- Installed current-user FestyAgricServices-DailyBackup at 02:00 WAT. Actual
  invocation returned result 0; its archive passed full isolated restore verification.
  This PC must be awake and the user signed in. Archives are not deleted/uploaded.
- Local release launcher passed read-only probes and security-header checks;
  its preview process tree was stopped without touching the development server.
- Added staff guide, acceptance walkthrough, HTTPS proxy template and deployment
  runbook. No external hosting/domain/storage has been provisioned or published.
- Release check found no blocking errors, with an unpriced-active-product warning.
  Prices, opening debts, physical stock and business sign-off need owner input.
- See [release status](RELEASE_STATUS.md) for evidence, backups and remaining choices.

## Previous Milestone: Branch Customer Directory

Implementation recorded: 2026-11-15 19:52 WAT (Africa/Lagos, UTC+1).

- Added branch-scoped customer contacts, Manager/Admin creation and updates,
  inactive status instead of deletion, version checks, and audit snapshots.
  Stable customer IDs will support the next credit-accounting stage.
- Customer writes, audit snapshots and retry responses use one transaction.
  Saved frontend retries survive reload; stale edits are rejected rather than
  overwriting a different Manager's changes. Salespersons can only view contacts
  within their assigned branch. No opening debt or credit transaction is created.
- Added Customers frontend tab and [credit policy documentation](CUSTOMER_CREDIT.md).
- Confirmed user policy: only Managers/Admins record credit sales; each full sale
  is initially owed, with no upfront deposit and repayments recorded later.
  Actual credit sales/collections/refunds/reporting remain the next separate stage.
- All 152 backend tests passed on isolated PostgreSQL before the additional
  simultaneous-customer-edit test was added; that test is checked separately.
- All 46 stock/concurrency tests then passed, including the new simultaneous
  customer-edit test. Browser checks passed customer creation, editing,
  deactivation, literal text rendering, branch privacy and unchanged revenue,
  alongside the existing workflows and mobile layout. An earlier Chrome
  disconnection was followed by this successful complete browser run.
- Applied customers_schema.sql to the configured database. Stock balances and
  existing business record counts stayed unchanged; no sample customers or debts
  were created. Customer credit transactions remain disabled until the next stage.
- Created and restore-verified backup
  `backups/FAS-backup-20261115T185824Z-ce62048f011f469ea14703dc1c555ed9`.

## Previous Milestone: Delivery Batch and Expiry Labels

Implementation recorded: 2026-11-15 19:30 WAT (Africa/Lagos, UTC+1).

- Added optional batch numbers and expiry dates to stock receiving, stored on the
  same stock movement as the received quantity. New receipts record receiver ID,
  username and timestamp. Old movements remain unknown; no stock is reassigned.
- Added authenticated, branch-scoped delivery history with pagination/filtering
  and an Inventory history table. Received quantities are explicitly historical,
  not current per-batch balances. Staff continue choosing physical batches.
- Rejected past expiry dates on new receipts, while keeping successful retries
  valid after expiry. Null new fields are omitted from retry payloads to preserve
  keys saved before this upgrade. Receipt label failures roll back with stock.
- User confirmed that staff know which batches to sell; no automatic allocation
  or extra batch selection at checkout is planned. Added commented code and
  [batch label documentation](BATCHES_AND_EXPIRY.md).
- All 147 backend tests passed on isolated PostgreSQL, including six focused
  receipt-label tests and backup/restore verification.
- Browser QA exposed an early-submit race during page loading. Sign-in now stays
  disabled until JavaScript handlers are ready, and its native fallback uses POST
  so credentials are not placed in the URL. The browser harness waits for readiness.
- The repeated browser suite passed delivery-label entry/history, all existing
  sale/cash/transfer/correction/report/adjustment flows, and mobile layout.
  Applied receipt_batches_schema.sql to the configured database; inventory balances
  and business record counts were unchanged, with no real test transactions created.
- Created and verified post-migration backup
  `backups/FAS-backup-20261115T184023Z-d72da552f84b46eabae60518c6ad88da`.

## Previous Milestone: Database Backup and Restore Verification

Implementation recorded: 2026-11-15 19:21 WAT (Africa/Lagos, UTC+1).

- Added a commented operator command to create unique custom-format PostgreSQL
  archives using the existing connection settings. A shared read-only snapshot
  keeps the archive and manifest table counts consistent during business activity.
- Added checksum verification and transactional restores restricted to a new
  random database on the isolated loopback test server. Table counts and validated
  constraints are checked; only the database created by the check is removed.
- Credentials stay out of process arguments and manifests. Archive files and
  the default backup folder are ignored by Git. Encryption, scheduling, off-device
  storage and actual production recovery remain separate operator tasks.
- Added [backup instructions](BACKUP_AND_RECOVERY.md) and focused safety/restore tests.
- Validation: 141 regression tests passed on isolated PostgreSQL. After tightening
  the snapshot setup, all five backup tests passed again, including a committed
  concurrent branch insertion between snapshot export and table counting.
- Created `backups/FAS-backup-20261115T182342Z-cd0b99862f5b4923bec2d6f8923e5405`
  from the configured database and successfully restored/verified it on the
  disposable server. The working database was read only; test databases created
  by restore verification were removed and the test server stopped.

## Previous Milestone: Cash Requests and Approved Drawer Movements

Implementation recorded: 2026-11-15 19:13 WAT (Africa/Lagos, UTC+1).

- Staff submit branch-scoped requests; Managers/Admins approve or reject with
  actor/name/time history. Pending/rejected requests do not change cash totals.
- Added opening float, cash additions, shortage recoveries, cash expenses,
  bank deposits, and drawer withdrawals. One opening float per branch/day.
- Approval and ledger posting commit atomically, using branch/request locks and
  idempotency keys. Retries cannot duplicate postings; failed decisions roll back.
- Cash postings use the approval's Lagos date. Daily count snapshots and reports
  include approved drawer movements separately from sales revenue and POS totals.
- Same-day recovery restores already-expected cash without double counting.
  Older-day recovery adds to today's drawer. References must be reviewed/current,
  same branch, and within the remaining recorded shortage.
- Added commented backend/frontend sections and [operator documentation](CASH_MOVEMENTS.md).
- Validation: all 136 tests passed against the isolated PostgreSQL instance,
  including nine focused cash tests and a competing-decision test. Chrome passed
  the staff-request/Admin-approval workflow, opening float and drawer totals,
  unchanged sales revenue, existing workflows, and mobile layout. The first full
  run timed out in an existing concurrent-login test; the repeat full run passed.
- Applied the additive cash ledger migration to the configured database after
  validation. Existing sales/inventory/movement/reconciliation record counts
  remained unchanged. No business cash requests or postings were created.

## Previous Milestone: Resolution Audit, Financial Reports, and Stock Adjustments

Validation recorded: 2026-11-15 17:50:09 WAT (Africa/Lagos, UTC+1; 16:50:09 UTC).

- Added Manager/Admin investigation, assignment, resolution-action and reopening
  events for latest/current reconciliation differences, preserving original amounts.
  Resolve requires prior review. Responsible staff must be active and eligible.
- Added Manager/Admin branch/date financial reports and CSV: gross Cash/POS,
  unknown methods, refund-day payouts, net sales, snapshot variance, unresolved
  decisions, missing/stale counts, responsible staff, and generation timestamp.
- Report reads use one coherent SQL statement, Lagos dates, bounded ranges/rows,
  exact decimal amounts, and formula-safe CSV text with signed numeric values intact.
- Added Manager/Admin physical counts, damage, expiry, and signed stock corrections.
  Required reasons, before/after/name snapshots, actor/name/time, expected-balance
  guards, atomic movements, and idempotency preserve audit history and avoid overwrites.
- Matching counts are recorded without zero movements. Adjustments do not change
  sales or invent costs/revenue. Expiry declarations are manual, not batch detection.
- Added frontend Reports & CSV, Stock adjustments/history, and discrepancy decisions.
  Pending decision/adjustment requests remain safely retryable across reload.
- All 126 backend/static tests passed on isolated PostgreSQL, including concurrent
  resolutions, duplicate adjustments, count-vs-sale races, CSV safety, and dates.
  Real browser checks passed investigation/resolution, report CSV, physical-count
  and expiry adjustments, plus prior checkout/refund/printing/branch/mobile flows.
- Test processes were stopped. Applied reports_adjustments_schema.sql without
  changing business sales/stock/counts/reviews or creating real actions.
- Added REPORTS_RESOLUTIONS_AND_STOCK_ADJUSTMENTS.md. Decisions do not post cash
  recoveries/write-offs; a cash-movement ledger remains a separately modelled stage.

Next small stage: business walkthrough and backup/restore validation, then cash
movement/expense/recovery posting and batch/expiry tracking as separately agreed.

## Previous Milestone: Manager-approved Sale Voids and Returns

Validation recorded: 2026-11-15 17:12:28 WAT (Africa/Lagos, UTC+1; 16:12:28 UTC).

- Added Manager/Admin-only sale corrections: full voids of untouched receipts and
  partial/full returns of remaining quantities, including legacy standalone sales.
- Refunds use original discounted unit prices. Cumulative quantities are checked
  under branch/receipt locks, blocking over-refunds and concurrent double returns.
- Resellable returns and voids restore stock; damaged/non-resellable returns stay
  outside available stock. Original sale rows/movements and receipt dates are intact.
- Added required reason, actual refund method (defaults to the known original),
  approver ID/name, timestamps, FAS-C correction receipts, and original-receipt
  annotations with refunded/reversed and net totals. Pending requests are retry-safe.
- Reconciliation now shows gross sales, refund-day payouts, and expected net cash/POS.
  Refund-only days can be negative. New refunds invalidate old refund-day snapshots;
  prior original-day reviews remain historical rather than being rewritten.
- Added frontend correction quantities, condition/restock choices, amount preview,
  approval, history, printing, and signed net count inputs.
- All 111 backend/static tests passed on the isolated PostgreSQL instance. Browser
  tests passed damaged return without restock, cash void with restock, original and
  correction printing, and stale reconciliation after a refund, plus prior flows.
  Test browser/API/PostgreSQL processes were stopped; no test used business tables.
- Applied sale_corrections_schema.sql. Original sales, stock balances, submitted
  amounts, notes, reviews, and timestamps preserved. Only new gross snapshot fields
  were populated from old expected totals. No real business correction was created.
- Added SALE_VOIDS_AND_RETURNS.md. POS/bank refunds remain external operator actions;
  this application records their method/amount and approval, not terminal integration.

Next small stage: discrepancy-resolution workflow and financial reports/exports,
then controlled inventory adjustments and correction-error reversal if needed.

## Previous Milestone: Multi-product Checkout and Printable Receipts

Recorded: 2026-11-15 16:49:07 WAT (Africa/Lagos, UTC+1; 15:49:07 UTC).

- Added POST /checkouts: 1-100 distinct products per customer purchase, one Cash/POS
  payment, exact totals, item discount limits, branch scope, and idempotency.
- Header, all existing sales item rows, inventory deductions, movements, and saved
  response share a transaction. A later-item failure rolls everything back.
- Added GET /checkouts history/details and legacy standalone receipt retrieval.
  Old sales remain visible; linked checkout items are not counted as extra purchases.
- Reconciliation now combines new purchase headers and old standalone sales, counting
  each customer purchase and its payment once. Earlier snapshots remain intact.
- Added an editable frontend cart, quantity merging, purchase history reprints, and
  Print receipt / Save as PDF. New receipts snapshot branch/staff names and include
  FESTY AGRIC SERVICES, a unique FAS number, items, totals, method, and Lagos date/time.
- Kept old pending standalone-sale keys compatible. Cart request retries survive
  lost responses/reload without creating a second purchase.
- All 98 backend/static tests passed on the isolated PostgreSQL instance. Browser
  tests passed a two-product purchase, exact total, receipt reprint, print-only CSS,
  generated PDF, Cash/POS retry across reload, branch access, and reconciliation.
  All test processes were stopped; no browser test wrote to business tables.
- Applied checkout_schema.sql without rewriting historical sales or changing stock.
  Added MULTI_PRODUCT_CHECKOUT.md with the API, workflow, snapshots, and limits.

Next small stage: controlled sale voids/returns with stock/payment audit, then
discrepancy resolution and financial reports/exports. Mixed payments remain pending.

## Previous Milestone: FESTY AGRIC SERVICES Daily Reconciliation

Recorded: 2026-11-15 16:25:14 WAT (Africa/Lagos, UTC+1; 15:25:14 UTC).

- Added daily cash/POS expected totals by branch and Lagos calendar date, staff
  submissions, exact signed differences, and Manager/Admin review with notes/time.
- Salespersons are scoped to their assigned branch. Managers/Admins can see all.
- Submissions are immutable snapshots; corrections append revisions. Extra sales
  flag a snapshot as out of date and block new review until an updated count is submitted.
- Preserved submission/review IDs, notes, and timezone-aware timestamps. Existing
  reviewed snapshots remain in history even if later sales require a new revision.
- Protected submissions with existing idempotency keys and transaction/branch locks.
  Unknown legacy payment methods block reconciliation instead of being guessed.
- Added Daily reconciliation frontend with summaries, differences, history, and review.
  Money formatting now handles negative differences exactly with integer kobo values.
- All 88 backend/static tests passed in the isolated PostgreSQL instance. Browser
  tests passed a Salesperson's POS-shortage submission and Admin review, alongside
  the existing sales/transfers/retry/mobile workflows. Test processes were stopped.
- Applied reconciliation_schema.sql without changing business sales/stock or
  creating real financial submissions. Added DAILY_RECONCILIATION.md.

Next small stage: multi-product checkout/receipts, then discrepancy-resolution
and financial reports/exports. Float/expenses and POS settlement need separate modelling.

## Previous Milestone: Local Frontend and Cash/POS Sales

Recorded: 2026-11-15 16:10:45 WAT (Africa/Lagos, UTC+1; 15:10:45 UTC).

- Built a responsive HTML/CSS/vanilla-JavaScript frontend, locally served by FastAPI
  at /app/. Includes login/logout, inventory, supplier receiving, products/pricing,
  Admin Add Product and discount controls, accounts/branch assignment, whole-unit
  sales, paginated history, and transfer dispatch/receiving confirmation.
- Sales require explicit payment_method (cash or pos), preserved in saved responses
  and history. Historical sales remain unknown/Not recorded, with no guessed backfill.
- Applied sale_payments_schema.sql, adding the nullable historical payment field.
  Existing business stock, accounts, and historical sale values were unchanged.
- All UI dates display in Africa/Lagos. Exact integer-kobo arithmetic is used for
  displayed totals and minimum prices; API Decimal/NUMERIC validation remains final.
- Login tokens stay in memory. Pending stock/sale keys and bodies use account-scoped
  tab storage; uncertain responses lock the form and can be retried without duplicates.
- Backend suite: 74 tests passed, plus 2 static frontend tests (76 total). JavaScript
  syntax checks passed. Real Chrome testing passed product/account creation,
  receiving, Cash/POS sales, a lost successful response followed by retry, receiving-
  branch confirmation, branch scope, safe text rendering, and mobile layout.
- Browser write tests used a uniquely named database on the disposable PostgreSQL
  instance, never business tables. The browser, test API, and test server were stopped.
- Added FRONTEND.md with setup, workflows, payment semantics, and retry behavior.
- Local-only implementation; no public hosting or POS terminal integration configured.

Next small stage: review the frontend with the business owner, then implement
payment reconciliation/reporting and multi-product sales in separate tested steps.

## Previous Milestone: Priced Sales and Event Timestamps

Recorded: 2026-11-15 15:40:47 WAT (Africa/Lagos, UTC+1; 14:40:47 UTC).

- Admin/Manager can set product selling_price. Only Admin can set each product's
  max_discount_percent. Existing products start unpriced with a 0% discount limit.
- Added POST /sales for one product in whole base units, with branch scoping,
  server-side discount validation, decimal NGN calculations, and duplicate protection.
- Added GET /sales with branch scope and pagination. Sales preserve original prices,
  units, product names, seller, optional customer/notes, and timestamp snapshots.
- Stock deduction, sale, linked movement, and saved request response share one
  transaction. Invalid prices and failed movements do not leave partial records.
- Transfer dispatch/confirmation responses now include recorded date/time with
  timezone offsets. Repeated confirmations retain original received_at.
- Added SALES_AND_PRICING.md, including exact discount rules, timestamp formats,
  and Africa/Lagos display guidance for future frontend and printed records.
- All 71 tests passed on the isolated PostgreSQL instance, including discount
  rounding, ownership, rollback, concurrent sales, and sales competing with transfers.
  The isolated instance was stopped after testing.
- Applied sales_pricing_schema.sql. Existing stock/accounts/historical movements
  unchanged; no real sale or price values were entered. The request-type check was
  extended to allow sales, preserving all previous keys and responses.

Next small stage: frontend for login, products (including Admin Add Product and
pricing/discount controls), stock, confirmed transfers, and whole-unit sales.
Payments/reconciliation and multi-product sales remain separate later stages.

## Previous Milestone: Branch Scope and Confirmed Transfers (2026-11-15)

- Confirmed business rules: Salespersons see their assigned branch, Admin/Manager
  see all branches, transfers require receiving confirmation, initial sales use
  whole base units, and the future frontend must let Admins create products.
- Added branch assignments to /users and /auth/me. The API and local account tool
  require a valid branch for new active Salespersons. Existing accounts remain
  unassigned until an Admin assigns them; no business assignments were guessed.
- Inventory, movement history, branch lists, and transfer lists enforce branch
  access on the server. The shared product catalogue remains available.
- POST /stock-transfers now dispatches only: source stock decreases, transfer_out
  is recorded, and a transfer stays in_transit until receiving confirmation.
- Added GET /stock-transfers and POST /stock-transfers/{transfer_id}/confirm.
  The destination Salesperson, Admin, or Manager can confirm. Source Salespersons
  cannot confirm for another branch. Repeated confirmations do not duplicate stock.
- Transfer movements now carry transfer_id; old movements remain unchanged.
- Added docs/branch_transfers_schema.sql and BRANCHES_AND_TRANSFERS.md.
- All 56 tests passed on the isolated PostgreSQL instance, including branch
  isolation, dispatch/confirmation rollback, repeat confirmations, and concurrent
  stock operations. The isolated server was stopped after testing.
- Applied the additive migration to development without changing existing stock,
  rewriting historical movements, or assigning real users to branches.
- Sales implementation is waiting for the price-entry decision. The Add Product
  frontend is planned; POST /products already supports adding new items.

## Previous Milestone: Account Administration and Login Throttling (2026-11-15)

- Added commented accounts.py with Admin-only GET /users, POST /users, and
  PATCH /users/{user_id}. API responses exclude passwords, hashes, and tokens.
- Admins can create accounts, change roles, and deactivate/reactivate accounts.
  Deactivation revokes all current sessions; reactivation does not restore them.
- Prevented demotion or deactivation of the last active Admin. Account changes
  serialize before counting Admins, and recheck the actor's current permissions.
- Five failed logins per username within 15 minutes cause a 15-minute lock from
  the fifth failure. Subsequent attempts return 429 with Retry-After. Successful
  login clears failures; unknown usernames follow the same throttling flow.
- Added account_management_schema.sql and applied its new login_attempts table.
  Existing accounts, passwords, sessions, business stock, and movements unchanged.
- All 50 tests passed on the isolated PostgreSQL instance, including concurrent
  login failures and simultaneous Admin demotions. The test server was stopped.
- Updated AUTHENTICATION.md with Admin workflows and exact throttling behavior.
- Limits: throttling is per username; hosting-layer IP throttling and cleanup of
  old counter/session records remain future work. Password reset is not implemented.

Next small stage: define branch-specific access, transfer acceptance, and selling
units with the business owner before implementing branch restrictions and sales.

## Previous Milestone: Authentication and Roles (2026-11-15)

- Added POST /auth/login, GET /auth/me, and POST /auth/logout.
- Added commented auth.py with salted scrypt password hashing and eight-hour opaque
  bearer sessions. Only token digests are stored; logout revokes the current session.
- Business endpoints require login. Admin/Manager can change products and stock;
  Salesperson can read business data. All branches remain visible initially.
- Roles and account active status are checked on every authenticated request.
- Stock request keys now record their owner; other users cannot replay saved results.
  Legacy keys with no owner remain reserved and cannot expose their saved responses.
- Added create_user.py for private terminal account provisioning. No public signup,
  default passwords, or live test accounts were created.
- All 40 tests passed on the isolated PostgreSQL instance, including real auth,
  stock rollback, idempotency, and concurrency checks. The test server was stopped.
- Applied auth_schema.sql to development: users and user_sessions start empty, and
  stock_requests gains a nullable user_id foreign key. Stock/movement rows unchanged.
- Setup and role rules are documented in AUTHENTICATION.md. Create the first Admin
  locally before using the now-protected endpoints.

Next small stage: define branch access and transfer policy with the business owner,
then implement account administration and login throttling. Sales and selling-unit
rules still need decisions before sales deduction is implemented.

## Previous Milestone: Duplicate Request Protection (2026-11-15)

- Receipt and transfer POST endpoints require an Idempotency-Key UUID header.
- Reusing a key with the same validated body and endpoint returns the saved HTTP
  201 result. Reusing it with different content or another endpoint returns 409.
- The request key, stock updates, movements, and saved result share one transaction.
  Failed operations do not consume the key. Concurrent duplicates apply stock once.
- Added explanatory comments to request reservation, replay, and response handling.
- Added docs/stock_requests_schema.sql, an additive stock_requests table migration.
- All 29 tests passed on the isolated PostgreSQL instance, including simultaneous
  duplicates, conflicting keys, rollback and retry, and replays after stock changes
  or product deactivation, and failure to save the final response. The isolated
  server was stopped after testing.
- Applied the additive migration using the existing application account; verified
  that stock_requests starts empty. Existing business rows were not changed.
- New keys are required for new operations. Existing clients/tests must include the
  header; missing or invalid UUID headers return 422 before opening a connection.
- Keys have no expiry and must be retained. Duplicate real-world deliveries entered
  under different keys are outside this protection.

Next small stage: authentication and roles, including scoping request keys and
stored responses to the authenticated user. Business rules for transfers and
feed-only branches still need clarification before enforcement.

## Previous Milestone: Movement History and Concurrency (2026-11-15)

- Added GET /stock-movements, with optional branch_id and product_id filters.
- Returns id, branch_id, product_id, quantity_change, movement_type, notes, and
  created_at. Results are ordered newest first by timestamp, then ID for ties.
- Pagination uses limit (default 100, maximum 500) and offset (default 0).
  Missing filter matches return an empty list; invalid filters return HTTP 422.
- Example: GET /stock-movements?branch_id=1&product_id=1&limit=20&offset=0
- All 18 tests passed on a disposable local PostgreSQL 17 instance, including
  four simultaneous receipts creating one destination balance, competing transfers
  that cannot oversell, and opposite-direction transfers running alongside a receipt.
- History tests cover filtering, pagination, empty results, and timestamp ties.
- The existing inventory_app role cannot create schemas. Its permissions were not
  changed. Concurrency tests instead ran on a separate loopback-only PostgreSQL
  cluster, which was stopped after testing. Business tables were untouched.
- Standard PostgreSQL tests still use connection-local temporary tables.
  Concurrency tests additionally require RUN_POSTGRES_CONCURRENCY=1 and a separate
  test database configured through DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.
  The test role needs CREATE privilege. They create UUID-named schemas and remove
  only those schemas during cleanup; never enable them against a business database.
- Concurrent tests exercise representative interleavings, not an exhaustive load test.
- No production schema or connection-helper changes were required.

Next small stage: duplicate-request protection for receipts and transfers, followed
by authentication and roles before operational use. Transfer pairing and branch
product restrictions still need business rules. Earlier milestones below record
the previous state of the project.

## Previous Milestone: Receiving and Transfers (2026-11-15)

- Implemented POST /stock-receipts and POST /stock-transfers.
- Transfers accept source_branch_id, destination_branch_id, product_id, quantity,
  and optional notes. Quantities are positive whole base units.
- Both branch balances and transfer_out/transfer_in movements are saved in one
  transaction. Missing destination inventory is created automatically.
- Invalid inputs return 422; missing branches/products return 404; inactive
  products, insufficient source stock, and balance overflow return 409.
- Branches are locked in ascending ID order to serialize overlapping transfers.
- No schema changes or connection-helper changes were required.
- All 12 tests passed, including real PostgreSQL rollback tests for failed
  movement inserts and destination overflow. Tests use only connection-local
  temporary tables with a pg_temp-only search path, not business tables.
- Concurrent requests have not yet been integration-tested. Temporary test table
  definitions model the verified constraints rather than inspecting live tables.

Run from backend in PowerShell:

```powershell
# Validation tests only (database tests are skipped by default).
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
# Include isolated PostgreSQL tests using backend/.env credentials.
$env:RUN_POSTGRES_TESTS = '1'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
Remove-Item Env:RUN_POSTGRES_TESTS
```

Successful transfer responses use HTTP 201 and return source_branch_id,
destination_branch_id, product_id, quantity_transferred, source_quantity,
and destination_quantity.

Next small stage: concurrent stock-operation tests and movement history retrieval.
Before operational use, implement duplicate-request protection and permissions.
Transfers complete immediately; dispatch/acceptance, paired movement identifiers,
and feed-only branch policy are not implemented yet.
The earlier next-task sections below describe the previous project state.

## Completed Milestones

### 1. Project Setup
- Created backend, frontend, and docs folders.
- Initialized Git repository.
- Created GitHub repository.
- Configured Python virtual environment.
- Installed FastAPI and required dependencies.
- Configured .gitignore to exclude secrets.

### 2. Database Setup
- Installed PostgreSQL.
- Created business_inventory_db.
- Created dedicated database user: inventory_app.
- Configured database connection using environment variables.
- Successfully connected Python to PostgreSQL.

### 3. Branch Management
- Created branches table.
- Added three business branches.
- Implemented GET /branches.
- Verified that database changes appear in API responses.

### 4. Product Management
- Created products table.
- Added sample products.
- Implemented GET /products.
- Implemented POST /products.
- Implemented product update functionality.
- Tested product creation and updates using FastAPI documentation.

### 5. Inventory Management
- Created inventory table.
- Added sample inventory records.
- Implemented GET /inventory.
- Implemented inventory filtering by branch.
- Verified inventory results using PostgreSQL and FastAPI.

### 6. Stock Movement Tracking
- Created stock_movements table.
- Implemented foreign key constraints.
- Added quantity validation.
- Successfully tested a stock-receiving transaction.

## Most Recent Completed Task

Recorded a supplier delivery using PostgreSQL.

Branch: Main Branch
Product: Chikun Starter Feed

Initial quantity: 50 bags
Quantity received: 100 bags
Final quantity: 150 bags

Actions performed:
1. Started transaction using BEGIN.
2. Updated inventory quantity.
3. Inserted a stock movement record.
4. Committed both changes using COMMIT.

Result: SUCCESS

## Current Database Tables

- branches
- products
- inventory
- stock_movements

## Current API Endpoints

- GET /
- GET /branches
- GET /products
- POST /products
- PATCH /products/{product_id}
- GET /inventory

Note: Confirm endpoint paths against main.py
when resuming development.

## Next Task

Walk through the completed business workflows and choose private off-device
backup storage and a backup schedule. Backup creation/isolated restore verification
is implemented; unattended scheduling and production deployment are not configured.

Delivery batch/expiry labels are implemented. Staff manually choose physical
batches; do not introduce automatic allocation without a new business request.
Credit accounting and locally testable release work are complete. Next actions
require business/infrastructure input: correct missing prices, confirm opening
stock/cash and any pre-existing debts, complete owner/staff acceptance, choose an
always-on host/domain and private encrypted off-device backup storage. No automatic
batch allocation is planned; staff choose physical batches. See RELEASE_STATUS.md.

## Upcoming Features

- Per-batch remaining balances only if requested; current expiry removals are manual.
- Opening-debt migration and credit limits only after business rules/data are supplied.
- Automated private backup storage and scheduling.
- Production deployment and business acceptance walkthrough.

## Development Rules

- Explain new concepts before implementing them.
- Build features incrementally.
- Test each endpoint before proceeding.
- Never delete existing database tables without reviewing consequences.
- Use database transactions for stock changes.
- Keep documentation synchronized with implementation.
- Commit completed milestones to GitHub.
- Do not commit credentials or .env files.

## Notes for Future Conversations

Technology stack:
- Frontend: HTML, CSS, JavaScript
- Backend: Python FastAPI
- Database: PostgreSQL

Development environment:
- Windows
- VS Code
- Git Bash
- Python virtual environment

The user is learning full-stack development while
building a real inventory management application.

Provide step-by-step guidance rather than implementing
multiple major features at once.

Before recommending database changes, inspect the
existing schema and avoid destructive operations.

Resume development from the Next Task section.


## Latest Change: Clear Branch Stock Receiving

Date/time: 16 November 2026, Africa/Lagos (WAT).

Added a dedicated Manager/Admin Add stock screen and prominent Inventory action.
The form explicitly asks for the receiving branch, product and base-unit quantity,
with a plain-language delivery summary. Creating an unknown product from this
screen keeps the delivery draft and selects the new product on return; catalogue
creation still never writes stock. Standalone product creation offers an Add stock
shortcut. A saved delivery shows its branch and balance, with a shortcut to that
branch's inventory. Existing idempotent receiving endpoint and transaction remain
unchanged. Comments explain the catalogue/branch distinction and saved retries.

Validation: three frontend/static/markup tests; JavaScript syntax; 55 browser
page/viewport layout checks; browser workflow checks including connected product
creation, separate branch balances, receiving confirmation and stock navigation.
All business test writes use a disposable PostgreSQL database, never live data.
