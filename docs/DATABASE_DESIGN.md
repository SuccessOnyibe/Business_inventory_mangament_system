# Database Design

## 1. Database Information

Database: business_inventory_db
Database Management System: PostgreSQL

The application connects using a dedicated database user:
inventory_app

Database credentials are stored in backend/.env and must
never be committed to GitHub.

## 2. Tables

### branches

Stores information about the business's three branches.

Columns:
- id: INTEGER, primary key, automatically generated
- name: VARCHAR(100), required
- type: VARCHAR(50), required

Current records:
- 1: Main Branch (General)
- 2: Branch 2 (General)
- 3: Branch 3 (Feed Only)

### products

Stores products available in the business.

Columns:
- id: INTEGER, primary key, automatically generated
- name: VARCHAR(150), required
- category: VARCHAR(50), required
- base_unit: VARCHAR(30), required
- is_active: BOOLEAN, required, defaults to TRUE

Examples:
- Chikun Starter Feed: Feed, bag
- Ultima Grower Feed: Feed, bag
- Newcastle Vaccine: Vaccine, vial
- Amprolium: Medicine, sachet
- Poultry Drinker: Equipment, piece
- Top Feed Starter: Feed, bag

Products are stored independently of branch inventory.

### inventory

Stores current product quantities at each branch.

Columns:
- id: INTEGER, primary key, automatically generated
- branch_id: INTEGER, required, references branches(id)
- product_id: INTEGER, required, references products(id)
- quantity: INTEGER, required, defaults to 0

Constraints:
- Quantity cannot be negative.
- Each branch/product combination must be unique.

A product can exist at multiple branches with different
stock quantities.

### stock_movements

Records changes to inventory quantities.

Columns:
- id: INTEGER, primary key, automatically generated
- branch_id: INTEGER, required, references branches(id)
- product_id: INTEGER, required, references products(id)
- quantity_change: INTEGER, required
- movement_type: VARCHAR(30), required
- notes: TEXT, optional
- created_at: TIMESTAMPTZ, required, defaults to NOW()

Constraints:
- quantity_change cannot equal zero.

Positive quantity changes represent stock increases.
Negative quantity changes represent stock decreases.

Examples of planned movement types:
- stock_received
- sale
- transfer_in
- transfer_out
- damage
- adjustment

Movement types are not yet restricted by a database constraint.

## 3. Table Relationships

branches (1) ---- (many) inventory

products (1) ---- (many) inventory

branches (1) ---- (many) stock_movements

products (1) ---- (many) stock_movements

Foreign keys ensure that inventory records and stock
movements reference existing branches and products.

## 4. Inventory Transactions

Inventory changes should update both:
1. The inventory table.
2. The stock_movements table.

These operations must occur inside the same database
transaction.

If either operation fails, neither change should be saved.

## 5. Completed Transaction Test

Test scenario:
- Branch: Main Branch (ID 1)
- Product: Chikun Starter Feed (ID 1)
- Initial quantity: 50 bags
- Quantity received: 100 bags
- Final quantity: 150 bags

Operations:
1. BEGIN
2. UPDATE inventory
3. INSERT INTO stock_movements
4. COMMIT

Result:
- Inventory updated successfully.
- Stock movement recorded successfully.
- Transaction committed successfully.

## 6. Important Design Decisions

- Products are shared across branches.
- Inventory quantities are tracked separately for each branch.
- Stock movements record changes rather than current balances.
- Product deactivation is preferred over deleting historical products.
- Stock changes should be traceable.
- Database transactions protect consistency.

## 7. Duplicate Request Protection

The additive schema file stock_requests_schema.sql creates stock_requests:
- request_id: UUID primary key, supplied as the Idempotency-Key HTTP header.
- operation: stock_received or stock_transfer.
- request_payload: JSONB containing the validated request, including notes.
- response: JSONB containing the original successful response.
- created_at: timestamp with time zone, defaults to NOW().

The request reservation, inventory changes, stock movements, and saved response
commit together. A unique request_id makes simultaneous retries wait for the
first transaction. A successful duplicate returns the original HTTP 201 response;
different content or a different endpoint with that key returns HTTP 409.
Failed transactions roll back the key as well, allowing a corrected retry.
Keys remain globally unique across these two endpoints. Since authentication was
added, stock_requests.user_id references users(id); only the owner can replay a
successful result. Legacy NULL owners remain reserved and cannot be replayed.
Retain request records: removing them would allow old requests to change stock again.

Both stock POST endpoints now require an Idempotency-Key header containing a UUID.
Generate one key for each new business operation and reuse it for every retry of
that operation. A new key always means a new operation; this does not detect two
entries for the same supplier delivery if they use different keys.
The saved quantities describe the original transaction, not the current balance.

For an existing database, apply docs/stock_requests_schema.sql once before using
the updated endpoints. The application role needs SELECT, INSERT, and UPDATE on
stock_requests. The migration creates no sequences and changes no business rows.

## 8. Authentication Tables

auth_schema.sql creates users (id, unique username, password_hash, role, is_active,
created_at) and user_sessions (token_hash, user_id, expires_at, revoked_at,
created_at). Role is restricted to admin, manager, or salesperson. A user has many
sessions and stock request records. Session tokens are stored only as hashes.
Existing stock_requests rows receive NULL user_id; new endpoint requests record
the authenticated owner. See AUTHENTICATION.md for provisioning and API usage.

## 9. Login Throttling

account_management_schema.sql adds login_attempts: username (primary key), failures
(nonnegative integer), window_started_at, and optional locked_until. It deliberately
has no user foreign key because unknown usernames follow the same throttling rules.
Counters and lock expiry persist across API restarts and are shared by all workers.
Failed login counters commit before the HTTP error is raised. Account-management
changes serialize access to users while checking the last-active-Admin invariant.

## 10. Assigned Branches and Confirmed Transfers

branch_transfers_schema.sql adds users.branch_id referencing branches(id), and
stock_transfers with source/destination branches, product, positive quantity,
in_transit/received status, notes, created_by, confirmed_by, creation/receipt times,
and a saved destination_quantity for repeat confirmations. Foreign keys preserve
references; checks enforce different branches and consistent confirmation fields.

stock_movements.transfer_id links the dispatch/receipt pair. A partial unique index
on (transfer_id, movement_type) prevents duplicate movements of the same type for
one transfer. Legacy movements have NULL transfer_id and are not rewritten.
In-transit quantities are excluded from available branch inventory until receiving
confirmation. See BRANCHES_AND_TRANSFERS.md for the workflow and current limits.

## 11. Prices and Whole-unit Sales

sales_pricing_schema.sql adds products.selling_price (optional positive NUMERIC(12,2))
and max_discount_percent (NUMERIC(5,2), 0-100, defaults to 0). Existing products
remain unpriced until an Admin/Manager sets their prices. Only Admin can set discount
limits through the API.

sales stores a positive whole quantity, branch/product/user foreign keys, unit_price,
original list_price and discount-policy snapshots, generated total_amount, product
name/unit snapshots, optional customer/notes, and a TIMESTAMPTZ created_at. Database
checks enforce the saved discount range. Stock movements link through unique sale_id.
The request ledger allows the sale operation alongside receiving/transfers.

All sale and transfer timestamps are recorded in the database and exposed in API
history with timezone information. Transfer responses include dispatch created_at
and confirmation received_at. See SALES_AND_PRICING.md for Africa/Lagos display
guidance and examples. Transaction history is independent of later catalogue edits.

## 12. Cash/POS Method Recording

sale_payments_schema.sql adds sales.payment_method (cash or pos). It is nullable
for historical sales, whose payment method is unknown. New POST /sales requests
must explicitly provide a valid method; the application saves it in the sale and
duplicate-request response in the same transaction. The migration does not guess
or rewrite historical methods. POS here records the operator's reported method;
terminal settlement, split payments, and reconciliation are future work.

## 13. Daily Reconciliation

reconciliation_schema.sql adds daily_reconciliations, with unique branch/date/revision,
expected and actual cash/POS NUMERIC totals, generated signed differences, original
sales count/last ID, notes, submitter/reviewer foreign keys, and event timestamps.
Corrections append revisions. Only the current latest snapshot can be newly reviewed;
older reviews remain historical. The request ledger permits reconciliation requests.
Day boundaries use Africa/Lagos midnight; unknown historical payment methods block
submission. Reconciliation does not mutate stock or sales. See DAILY_RECONCILIATION.md.

## 14. Multi-product Checkout

checkout_schema.sql adds sale_orders: branch/staff foreign keys and name snapshots,
one payment method, total_amount, item_count, optional customer/notes, and created_at.
sales.order_id links existing sales rows as receipt items. A partial unique index
prevents duplicate products within one order. Historical standalone rows remain NULL.
Each item's existing stock movement still references its unique sale_id.

The request ledger permits checkout. Header, items, stock, movements, and saved
response commit atomically. Reconciliation uses headers plus standalone rows to
avoid double-counting purchases. New full receipts preserve branch/staff names;
legacy reprints resolve their current names because no such snapshot existed.
See MULTI_PRODUCT_CHECKOUT.md for endpoints, print behavior, and limits.

## 15. Sale Corrections and Refund-aware Reconciliation

sale_corrections_schema.sql adds immutable sale_corrections headers (one checkout
or legacy receipt, branch/name, reason, kind, refund method/total, approver/name,
customer, timestamp) and sale_correction_items (original sale/product, quantity,
original price, generated refund amount, restock decision). Movements link uniquely
through correction_item_id; original movements/sales remain unchanged.

Application branch/receipt locks protect cumulative returned quantities. Refunds
apply to their own event date and payout method. Daily snapshots add gross totals,
refund totals/count/last ID; expected/actual net counts can be signed. Existing
expected/actual/review values remain intact; only new gross columns are backfilled.
Zero-value corrections still invalidate an older snapshot via count/last ID.
See SALE_VOIDS_AND_RETURNS.md for transactions, receipt annotations, and limitations.

## 16. Discrepancy Events, Reports, and Stock Adjustments

reports_adjustments_schema.sql adds discrepancy_events (count FK, action,
explanation/resolution action, responsible user/name, actor/name, timestamp) and
stock_adjustments (branch/product snapshots, mode, before/after/generated change,
reason, actor/name, timestamp). Each nonzero adjustment movement links uniquely
through stock_adjustment_id. Matching counts remain audited without zero movements.
The request ledger gains discrepancy_event and stock_adjustment operations.

Resolutions never overwrite financial snapshots. Stock adjustments use expected
balance checks and transaction locks; stale requests, negative balances, and overflow
are rejected. Reports derive transactions/latest snapshots/decisions in one SQL
statement with Lagos-day grouping and separate unknown-method amounts. CSV text is
formula-escaped. See REPORTS_RESOLUTIONS_AND_STOCK_ADJUSTMENTS.md for scope/limits.

## 17. Future Database Improvements

Planned additions include:
- Users and roles
- Sales and sale items
- Payments and daily reconciliation
- Branch stock transfers
- Customer credit accounts
- Product batches and expiry dates
- Inventory adjustments
- Audit records

The current inventory model uses integer quantities.

Additional modelling will be required for:
- Feed sold by bag, paint, half-paint, or naira amount.
- Prepackaged retail feed at Branch 3.
- Eggs sold by crate or individually.
- Damaged stock converted into retail stock.

These requirements should be addressed before implementing
the corresponding sales and stock operations.

## Cash ledger extension

Apply cash_movements_schema.sql after reports_adjustments_schema.sql. cash_movement_requests references branches, requesting/deciding users, and optionally a reviewed daily_reconciliation. cash_movements has one unique request_id, a branch, approving user, generated cash direction, Lagos business date, and posting timestamp. Daily reconciliation snapshots now retain cash in/out, drawer effect, movement count, and last posting ID. See [Cash movements](CASH_MOVEMENTS.md).

## Receipt label extension

Apply receipt_batches_schema.sql after cash_movements_schema.sql. Stock movements
gain nullable batch_number, expires_on, received_by (users FK) and received_by_name.
These fields are constrained to stock_received rows. Existing rows remain null.
These are delivery metadata, not batch inventory balances; see
[Batch and expiry labels](BATCHES_AND_EXPIRY.md).

## Customer directory extension

Apply customers_schema.sql after receipt_batches_schema.sql. customers references
a branch and creating/updating users; customer_changes references a customer and
acting user, retaining each saved version as JSON. No debts or payments are
created. Customer IDs/branches stay fixed, with deactivation instead of deletion.
See [Customer credit](CUSTOMER_CREDIT.md).

## Credit ledger extension

Apply credit_schema.sql after customers_schema.sql. sale_orders gains customer_id
and credit payment classification; sales receipt lines also accept credit. Composite
FKs enforce customer/order/repayment branch consistency. credit_repayments is an
append-only signed collection/reversal ledger linked to an order, actor, method
and timestamp. One reversal_of per payment prevents duplicate reversals.
sale_corrections.debt_reduction distinguishes unpaid cancellation from actual
refund_total; zero-cash corrections may omit refund_method. Daily snapshots track
repayment count/last ID. No existing record is converted into a debt.

## Product barcode extension

Apply product_barcodes_schema.sql after credit_schema.sql. products.barcode is
nullable, unique and limited to 64 printable non-space ASCII characters. Existing
values stay unknown; no categories, stock or prices are rewritten. Four display
departments group existing category labels; see CATEGORIES_AND_POS.md.
