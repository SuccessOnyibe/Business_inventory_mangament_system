# FESTY AGRIC SERVICES: Sale Voids and Customer Returns

## Approval and frontend workflow

Only Admin/Manager can approve and record corrections. Salespersons can read their
branch's history/receipts but cannot create corrections. There is no separate request
queue: the Manager/Admin submitting the correction is its recorded approver.

1. In Sales → Purchase history, choose Correct sale.
2. Choose Customer return or Void entire sale.
3. Confirm the actual Cash/POS refund/reversal method. It defaults to the original
   known method. Unknown legacy payments require an explicit choice.
4. For a return, enter whole quantities and choose Resellable — restock or Do not
   restock for each selected item. The default is Do not restock. Check the preview.
5. Enter the required reason and click Approve correction.
6. Print the correction, or reprint the original to see its correction history,
   original amount, refunded/reversed amount, net amount, approvers, and timestamps.

A void corrects an incorrect entry on an untouched receipt: it reverses the full
recorded payment and restores all sold quantities. A receipt with previous returns
cannot be voided; return its remaining quantities instead. Use returns for goods
that physically come back, especially damaged/expired goods. Non-resellable returns
are recorded outside available inventory with no stock increase or zero movement.

Refunds use original discounted prices, never today's price. The server calculates
the amount and blocks quantities already returned, including concurrent requests.
Approval records the operator's action; it does not contact a terminal or bank.
Original sale rows, timestamps, and movements remain unchanged. Corrections are
immutable; editing a mistaken correction needs a future controlled adjustment flow.

## API and retries

POST /sale-corrections requires Admin/Manager and an Idempotency-Key UUID:

```json
{
  "receipt_type": "checkout",
  "receipt_id": 1,
  "kind": "return",
  "reason": "Unopened goods returned by customer",
  "refund_method": "cash",
  "items": [{"sale_id": 2, "quantity": 1, "restock": true}]
}
```

sale_id is the original item ID from GET /checkouts/{id}. For old standalone sales,
use receipt_type: legacy and the ID from GET /sales/{id}/receipt. Linked checkout
items cannot be corrected as standalone receipts. A void uses kind: void and omits
items, since the server includes the entire receipt. Return rows require explicit
boolean restock values. Omit refund_method to use the known original method.

GET /sale-corrections supports branch_id, limit, and offset. GET /sale-corrections/{id}
returns printable items/condition, approver, reason, payment method, and timestamp.
Correction numbers use FAS-C-00000001-style identifiers linked to the original.
Original receipt details include status, corrections, refunded_total, net_total,
and each item's returned_quantity/remaining_quantity. Re-fetch details for current
annotations; replaying an original checkout still returns its original saved result.

Successful corrections return 201. Retry the same key/body/user, retaining originally
omitted/default fields, to retrieve the event without another refund/restock. New
keys cannot bypass cumulative limits. Conflicting keys, over-returns, voids after
prior corrections, and stock overflow return 409. Invalid/foreign/repeated items or
missing reasons return 422; missing receipts 404; insufficient permission/access 403.
The frontend preserves uncertain corrections in tab storage, locks their details,
and offers Retry saved request, including after reload and signing in again.

## Transaction safety

Header/items, stock increases/movements, and the saved response commit together.
Failure rolls all of them back and releases the key. Movements link via
correction_item_id and use sale_return or sale_void; original sale_id movements
stay intact. Branch and receipt locks prevent concurrent over-refunds/restocking.
An Admin/Manager approves directly; there is no staff-request approval queue yet.

## Refund-day reconciliation

Gross sales stay on their original Lagos date. Refunds/reversals subtract on their
own recorded Lagos date, by the actual payout method:

- Expected net cash = gross cash sales − cash refunds/reversals.
- Expected net POS = gross POS sales − POS refunds/reversals.

A POS sale refunded in cash reduces cash on the refund day without changing the
original POS sale. Refund-only days may have negative expected net values. Actual
count fields now accept signed net amounts too: sales collections less refunds,
excluding float, expenses, and terminal fees. Differences remain actual minus expected.

Summary shows gross, refunds, net totals, and refund count. New refunds make a
refund-day snapshot out of date, even for zero-value returns, requiring a new
revision before review. Later-day refunds do not rewrite the original sale day or
its reviewed counts. Unknown original payment methods still block reconciliation
of the original day; selecting an actual refund method does not invent that history.

## Migration and limits

Apply sale_corrections_schema.sql after checkout_schema.sql. It adds correction
headers/items, movement links, request type, and reconciliation refund snapshots.
Old nonnegative count checks are removed for signed net amounts. Only new gross
columns are populated from previous expected totals; original submitted/reviewed
amounts, notes, and timestamps stay unchanged. No real correction is created.

Tests cover partial/damaged returns, voids, original-price refunds, previous-day
sales, negative counts, stale snapshots, permissions, rollback/overflow, concurrent
returns, and duplicate voids. Browser tests verify damaged returns without restock,
voids with restock, printing, and refund-aware reconciliation. Mixed refunds on one
correction, tax/fees, transfer returns, and correction editing remain future work.
