# Assigned Branches and Delivery Confirmation

## Branch access

Admins and Managers can see all branches. Each Salesperson is assigned one branch:
inventory, movement history, the branch list, and transfer lists are filtered on
the server. Asking explicitly for another branch returns 403. An unassigned
Salesperson cannot read branch data until an Admin assigns the account.
Products remain a shared catalogue; listing products does not reveal stock in
another branch. Admin/Manager product creation and update remain available.

Use Admin PATCH /users/{user_id} with {"branch_id": 2} to assign a Salesperson.
New active Salesperson accounts require branch_id. Existing accounts were not
assigned automatically during migration. /auth/me and /users include branch_id.
The local create_user.py command also accepts --branch-id for a Salesperson.

## Send stock

Admin or Manager POST /stock-transfers, using a new Idempotency-Key UUID:

```json
{"source_branch_id": 1, "destination_branch_id": 2,
 "product_id": 1, "quantity": 20, "notes": "Branch delivery"}
```

The transaction deducts stock from branch 1, records transfer_out, creates an
in_transit transfer, and saves the duplicate-request response together. It does
not credit branch 2 yet. The response includes transfer_id and source_quantity.
GET /stock-transfers lists visible incoming/outgoing transfers, with pagination
and an optional branch_id filter. In-transit stock is tracked by these records,
so it is not available for sale at either branch.

## Confirm delivery

POST /stock-transfers/{transfer_id}/confirm after the goods arrive. The destination
branch's assigned Salesperson can confirm; Admins and Managers can confirm on
behalf of any branch. Salespersons cannot initiate transfers or receive suppliers'
stock. This is a deliberate exception to their otherwise read-only stock access.

Confirmation credits the destination, records transfer_in, and marks the transfer
received, with confirmed_by and received_at. These changes share one transaction.
Both movement records contain transfer_id, linking the dispatch to its receipt.
A partial unique index allows only one movement of each type per transfer.

Repeated/concurrent confirmations return the saved destination balance without
adding stock again. No extra idempotency header is needed: the locked transfer
and its status provide duplicate protection. A failed confirmation leaves the
transfer in transit, with no destination stock increase, so it can be retried.
Product deactivation after dispatch does not prevent recording physical delivery.

An integer overflow at the destination returns 409; stock stays in transit. The
source deduction is not undone because the goods have already been dispatched.
Partial delivery, rejection, cancellation, and returns are not implemented yet.

## Existing records and the next sales stage

branch_transfers_schema.sql adds users.branch_id, stock_transfers, and an optional
stock_movements.transfer_id. It does not rewrite existing inventory or historical
movements. Transfers completed under the old immediate workflow stay historical;
their saved idempotency responses are preserved. Do not submit them under new keys.

Whole-base-unit sales now use Admin/Manager prices, with customer discounts bounded
by an Admin-only per-product percentage. See SALES_AND_PRICING.md for dates/times,
pricing examples, sales history, and transactions. The frontend is still pending; an Admin Add Product form will
use the existing POST /products endpoint to add items without editing code or SQL.
