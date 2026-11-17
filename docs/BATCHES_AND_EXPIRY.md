# Batch and expiry labels

FESTY AGRIC SERVICES can now record the supplier's **batch number** and exact
**expiry date** when receiving stock. This is the first stage of batch tracking.

## Receiving a delivery

In Inventory, open **Receive stock from a supplier**. Enter the normal branch,
product and quantity, then copy the printed batch number and expiry date if
known. Leave unknown labels blank rather than guessing. For different batches
or expiry dates, submit separate receipts with their respective quantities.

If packaging only gives a month/year, confirm how the business interprets it
before entering an exact date. The application does not invent a day.

Manager/Admin permission is required. Receiving increases total product stock,
writes the stock movement with the labels, records the receiving user's ID/name
and timestamp, and saves the retry response **in the same transaction**. A failed
write saves none of these changes. There is no second stock balance to drift.

An expiry date before today in Africa/Lagos is rejected. Stock expiring today is
accepted: the date is treated as valid through that labelled calendar day. Check
the packaging and product requirements before receiving or selling it. This
date rule does not certify product safety. Unknown expiry is not assumed valid.

Retry the same request after a connection failure. An unchanged request returns
the original successful receipt even if its expiry date has since passed; it
does not receive the stock again. Changing a label requires a new delivery key,
but do not submit a new delivery merely to fix an already-recorded label: this
would incorrectly add stock twice. Label correction controls remain future work.

## Delivery history

Inventory's **Delivery history and batch labels** shows branch-scoped deliveries,
including quantity received, batch, expiry, actor and date/time in Lagos.
Salespersons see only their assigned branch. Managers/Admins can see all branches.
The list is paginated. Product and branch names use the current catalogue.

The API is `GET /stock-receipts`, with optional branch_id, product_id, limit and
offset. `POST /stock-receipts` accepts optional batch_number (up to 100 characters,
trimmed/nonblank when supplied) and expires_on (`YYYY-MM-DD`). Existing clients
can omit both. Existing retry keys keep their original payload shape and work.

## What the labels do and do not tell you

**Quantity received is historical, not stock currently remaining in that batch.**
Some or all of that delivery may already have been sold or transferred. The
history must not be used as an available-stock or expiry-alert report.

Existing stock and historical movements remain unchanged, with unknown labels
and unrecorded receiving users where that information was never stored. This
stage does not guess their batch identities or relabel existing inventory.

Business policy confirmed: staff choose the physical batch to sell. Checkout does
not automatically choose batches or require extra batch selection fields.

Sales, transfers, returns and adjustments still use total product quantities.
They do not allocate batches or block sales of stock that expires after receipt.
Staff must continue checking physical expiry labels. Automatic allocation is
not planned under the current policy. Per-batch remaining balances, eligible-stock
expiry alerts and opening-stock assignment are not implemented.

If per-batch balances are requested later, that work must cover every stock writer
together: receipts, standalone and
multi-item sales, dispatched/in-transit/confirmed transfers, voids, resellable
returns and physical/damage/expiry adjustments. Updating sales alone would make
batch totals disagree with inventory. Existing stock needs an explicit unknown
batch allocation and a controlled counting/assignment process, not invented dates.

## Schema and testing

Apply `receipt_batches_schema.sql` after `cash_movements_schema.sql`. It adds
nullable label/receiving-user fields and constraints to stock_movements, plus a
receipt-history index. Non-receipt movements cannot carry these receipt-only
fields. No existing quantities, prices, sales, cash entries or historical labels
are rewritten.

Tests cover optional labels, invalid/past dates, receiving permissions, scoped
history and pagination, normalization, rollback, retries after expiry, and old
payload compatibility. Browser checks enter labels and verify delivery history.
All write tests use the isolated PostgreSQL server.
