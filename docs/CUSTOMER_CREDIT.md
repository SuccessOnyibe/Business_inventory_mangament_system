# Customer credit and repayments

## Confirmed business rules

- Salespersons record credit sales and repayments for their assigned branch.
- Managers/Admins can work across branches and approve corrections/reversals.
- The entire credit sale is owed initially; no upfront deposit or mixed payment.
- Repayments happen later and may be recorded separately from the original sale.

Credit checkout, repayments, payment reversals, balances, corrections, printed
receipts and Cash/POS reconciliation/reporting are now implemented. Existing
Cash/POS receipts are not converted to debts. Opening historical debt migration
and credit limits are not implemented.

## Customer directory

Open **Customers** in the frontend. Managers/Admins can add contacts to a branch,
edit their name/phone/notes, and deactivate/reactivate them. Phone is optional.
Check the existing list before creating another record. Names and phone numbers
are not unique: different customers may legitimately share them. The customer ID
is the permanent identity that the future ledger will reference.

Salespersons can add, edit and view customer contacts only for their assigned
branch. Only Managers/Admins change active/inactive status. Managers/Admins see all branches and use the branch filter to narrow the
list. Notes are visible to staff with access to that branch's customer directory.
The same person at two branches currently has separate branch customer records;
this stage does not merge identities across branches.

Editing keeps the same ID and branch. Deactivation retains the contact; there is
no delete endpoint. Each successful creation/update saves an audit snapshot with
the acting user's ID and timestamp. Date/time is displayed in Africa/Lagos.
Changing contact information does not change any existing receipt's customer
name or invent a debt from historical cash/POS sales.

Each update includes the version displayed when the form was opened. If another
staff member saved a change first, the stale form gets 409: refresh and reopen it to
avoid silently overwriting that change. Creation/update, audit and saved retry
response commit in one transaction. A failure rolls them all back. A retry with
the original UUID key and unchanged body returns the original result. Saved
requests survive reload through the existing locked-form retry mechanism.

## API and schema

- `GET /customers`: optional branch_id, limit (1-500), offset; scoped by role.
- `POST /customers`: branch_id, name, optional phone and notes; assigned-branch staff,
  Idempotency-Key UUID; returns 201.
- `POST /customers/{id}/update`: name, optional phone/notes, is_active boolean,
  expected_version integer; assigned-branch staff and Idempotency-Key; returns 200.

Update replaces the editable contact fields; null/omitted phone or notes clears
them. Branch cannot be changed. Names are trimmed and must not be blank. Invalid
input, absent records, unauthorized access and stale/reused requests return the
existing 422/404/401/403/409 responses.

Apply `customers_schema.sql` after `receipt_batches_schema.sql`. It creates
customers (branch/user foreign keys, version and timestamps) and customer_changes
(customer/user foreign keys, JSON snapshot and timestamp). Existing inventory,
sales, cash, receipt labels and other business records are unchanged.

## Credit accounting and API

In Sales, staff choose Credit and an active registered customer in the
same branch. Stock and the sale commit together. The whole amount is initially
owed; no upfront deposit or mixed payment is accepted. Discounts still follow
Admin-set limits. The customer name on the receipt is a snapshot, so later
contact edits cannot rewrite historical documents.

- `POST /checkouts`: payment_method credit and customer_id, alongside normal
  branch/items, using an Idempotency-Key. Salespersons receive 403 for another branch or when unassigned.
- `GET /credit-sales`: branch-scoped paginated invoices and current balances.
- `GET /customers/{id}/balance`: current outstanding over ALL customer invoices,
  independent of the history page displayed in the UI.
- `POST /credit-repayments`: order_id, positive amount, actual payment_method cash
  or pos, optional notes, and Idempotency-Key. Assigned-branch staff may record payments. Partial payments
  allowed; overpayments rejected, including competing concurrent payments.
- `GET /credit-repayments`: branch-scoped history, optional order_id and pagination.
- `POST /credit-repayments/{id}/void`: required reason and Idempotency-Key;
  Manager/Admin only. Appends one signed reversal with its own actor/time/receipt.
  Cannot reverse a reversal, reverse twice, or reverse money already refunded.

Repayments/reversals post on the actual recording date in Africa/Lagos. They do
not contact a bank or POS terminal. Record only actual confirmed collections;
reverse only mistaken entries, not genuine repayments the customer still made.
Repayment recording is available to assigned-branch Salespersons and Managers/Admins.
Repayment reversals and sale corrections remain Manager/Admin only.

Credit balances are derived: original sale minus debt-only reductions minus net
repayments. Each write locks the branch then receipt, checks the balance, and
commits its ledger entry and saved retry response together. It never updates an
editable customer balance field. Customer deactivation blocks new credit sales,
but does not block collection of existing debts.

Credit sale revenue is recognized on the sale's date; expected Cash/POS collected
is zero until repayment. Repayments affect expected collections on their own
recording date and never count as new revenue. Reports and CSV now distinguish
gross credit sales, debt reductions and credit Cash/POS collections. Daily count
snapshots also track repayment count/last ID, so a later collection or reversal
makes a submitted count out of date. Original reviewed snapshots remain intact.

Returns and voids first reduce outstanding debt. A correction larger than the
unpaid portion refunds only the already-paid remainder through the actual method
selected. For a 200 sale with 50 paid, voiding reduces debt by 150 and refunds 50.
With nothing paid, voiding refunds zero and needs no refund method. Revenue falls
by the entire corrected value, including debt-only reductions. Resellable return
quantities are restored atomically with correction records and debt/refund effects.

Print invoices, correction documents and repayment/reversal receipts through the
existing browser print/Save as PDF workflow. Invoices show original credit value,
net collections, debt reduced, current outstanding and the balance timestamp.
Receipts retain the acting staff name and date/time. Paginated history is not an
aggregate balance: use View balance for the complete current customer balance.

Apply `credit_schema.sql` after `customers_schema.sql`. It extends payment
constraints, links credit orders to customers in the same branch, adds the signed
repayment ledger, debt-only correction amounts and repayment snapshot markers.
There are no real sample credit transactions in the working database.

See OPERATIONS_GUIDE.md for staff instructions and ACCEPTANCE_WALKTHROUGH.md for
business review scenarios. Opening debts that predate this ledger need a separate
owner-approved migration, rather than fake stock sales.
