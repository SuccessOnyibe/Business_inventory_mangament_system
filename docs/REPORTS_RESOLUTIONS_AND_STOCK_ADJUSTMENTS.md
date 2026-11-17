# FESTY AGRIC SERVICES: Resolution, Reports, and Stock Adjustments

## Investigate and resolve a shortage/excess

In Daily reconciliation, Managers/Admins choose Investigate / resolve on a latest
count with a nonzero difference. Assign an active member of that branch or a
Manager/Admin, enter the explanation, and save an investigation. To resolve, first
review the count, then record the action taken. A resolved discrepancy can be
reopened with a new explanation. Each decision is an appended event with responsible
staff, approver/name, and a timezone-aware timestamp; earlier events remain visible.

Only the latest current count can receive new decisions. Additional sales/refunds
or a superseding count require a new current submission first. Balanced counts have
no discrepancy to resolve. A resolved explanation leaves the original financial
difference intact. It does not change sales, counts, payments, or stock. Notes may
describe recovery, acceptance, or follow-up; cash recovery receipts, expenses,
write-offs, and bank settlement posting need a future cash-movement ledger.

- GET /reconciliations/{id}/assignees lists eligible active staff for Manager/Admin.
- POST /reconciliations/{id}/discrepancy-events requires Manager/Admin and an
  Idempotency-Key UUID. Body:

```json
{
  "action": "resolve",
  "responsible_user_id": 3,
  "explanation": "Receipts and terminal report checked",
  "resolution_action": "Documented difference accepted; staff follow-up completed"
}
```

Actions are investigate, resolve, or reopen. resolution_action is required only for
resolve and must be omitted/null otherwise. Resolved records must be reopened before
another decision. GET /discrepancy-events supports branch_id, limit, and offset;
Salespersons can read only their assigned branch. Submission/replay is atomic,
same-key safe, and conflict-checked; competing resolutions cannot both finalize.

## Financial reports and CSV

Managers/Admins open Reports & CSV, choose a date range and optional branch, and
Load report. The report includes each branch/day, gross Cash/POS, unknown-method
sales, refund-day payouts, expected net collections, net sales, latest count status,
submitted differences, resolution status/responsible staff, and generation time.
Download CSV exports the last successfully loaded filters using fresh database values.
Changing filters disables export until reloading. Reports are Manager/Admin-only.

Date boundaries are Lagos midnight-to-midnight. New multi-product purchases count
once; their item rows are not double-counted. Old standalone sales remain included.
Gross sales include unknown-method revenue, shown separately rather than guessed as
Cash/POS. Net sales is gross sales less refunds/reversals on their own recorded day.
Net sales measures revenue after refunds; cost/profit valuation awaits cost data.

Financial totals use current immutable transactions. Count differences shown are
from the latest submitted snapshot and retain their values after resolution. Missing,
unreviewed, and out-of-date counts are flagged. A previously resolved snapshot that
becomes stale shows out_of_date and cannot hide a current unresolved difference.
Zero-activity days are included. Unresolved-day counts include nonzero latest count
differences not currently resolved; missing/stale counts have separate indicators.

- GET /reports/financial?start_date=2026-11-01&end_date=2026-11-15&branch_id=1
- GET /reports/financial.csv uses the same parameters and permissions.

Ranges include both dates, cannot extend into the future, and allow at most 366
days/5,000 branch-day rows. All branches may be selected by omitting branch_id.
One SQL statement computes a coherent view of transactions, snapshots, and decisions.
Money is Decimal/NUMERIC and exact two-decimal text. CSV is UTF-8 with BOM for Excel;
formula-leading text is escaped while valid signed numeric amounts are preserved.
The CSV includes its generation time and is served without browser caching.

## Controlled stock adjustments

Managers/Admins open Stock adjustments, select branch/product, and Read balance.
Then choose:

- Physical count: enter actual whole available units, including zero.
- Damaged stock: enter the positive quantity to remove.
- Expired stock: enter the positive quantity to remove.
- Signed correction: enter a nonzero positive or negative change.

Enter a required reason and Record adjustment. Each record preserves branch/product
name/unit snapshots, before/after/change, reason, approver/name, and Lagos timestamp.
Salespersons can read their assigned branch's history but cannot change quantities.
Inactive products can still be counted/removed. Expiry is manually declared; batch
expiry dates and automatic expiry detection are not implemented. Confirm delivered
transfers before counting available stock; goods still in transit are separate.

The loaded balance is an expected_quantity precondition. If sales, deliveries, or
another adjustment change it, the server returns 409. Refresh and recount before
retrying, rather than overwriting an intervening transaction. Branch/row locks and
the saved request key protect concurrent and duplicate submissions. Negative final
balances, integer overflow, and positive damage/expiry changes are rejected.

POST /stock-adjustments requires Manager/Admin and an Idempotency-Key UUID:

```json
{
  "branch_id": 1,
  "product_id": 1,
  "mode": "physical_count",
  "expected_quantity": 50,
  "counted_quantity": 48,
  "reason": "Shelf count confirmed by Manager"
}
```

For damage/expiry/correction, omit counted_quantity and supply quantity_change;
damage/expiry must be negative. A matching physical count is still audited, with no
zero stock movement. Missing inventory is treated as zero and can be initialized by
an approved positive adjustment. GET /stock-adjustments supports branch/pagination.

The inventory change, adjustment record, linked nonzero stock movement, and saved
response commit together. Failure rolls everything back. Adjustments never rewrite
old movements or sales and do not invent purchases, refunds, costs, or revenue.
They are immutable; a later error correction requires another reasoned adjustment.
Uncertain frontend submissions retain their original body/key for safe retry.

## Migration and tests

Apply reports_adjustments_schema.sql after sale_corrections_schema.sql. It adds
discrepancy_events, stock_adjustments, stock_movements.stock_adjustment_id, and request
types. It does not create business decisions/adjustments or change existing counts,
sales, stock, reviews, or timestamps. Tests cover event lifecycle, review/stale guards,
assignment/permissions, exact reports, unknown methods, Lagos dates, CSV text safety,
all adjustment modes, matching counts, rollback, stale balances, and concurrency.
Browser checks exercise investigation/resolution, CSV export, physical count and
expiry adjustments, alongside the prior checkout/refund/transfer workflows.

## Cash ledger reporting

Reports and CSV exports now include approved cash in/out and drawer effect separately from revenue. Expected cash includes these effects; cash ledger entries never change net sales or POS totals. Summed daily expected cash is not a cumulative drawer/bank balance. See [Cash movements](CASH_MOVEMENTS.md).

## Credit revenue versus collections

Reports/CSV now include gross_credit, debt_reduced, repaid_cash and repaid_pos.
Net revenue includes credit sales and subtracts the whole corrected value.
Repayments/reversals change actual collections on their recording day without
counting as new sales. Outstanding customer debt is available through Customers
View balance and the credit-sales ledger.
