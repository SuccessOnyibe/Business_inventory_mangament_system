# FESTY AGRIC SERVICES: Daily Cash/POS Reconciliation

Managers/Admins can now investigate, assign responsible staff, resolve with an
action explanation, or reopen a discrepancy. These are appended decisions; original
count differences remain intact. Resolve requires a reviewed, current, latest count.
Reports & CSV show unresolved decisions and stale/missing counts. See
REPORTS_RESOLUTIONS_AND_STOCK_ADJUSTMENTS.md.

Refund-aware update: use collections less refunds/reversals recorded on this Lagos
date, by actual payout method. Expected/actual net amounts can be negative. Gross
sales, refunds, and net totals are displayed separately. New refunds also make a
snapshot out of date. See SALE_VOIDS_AND_RETURNS.md for approval and accounting rules.

## Staff workflow

1. Open Daily reconciliation in /app/.
2. Choose a branch and business date. Salespersons are restricted to their assigned
   branch; Admins and Managers can choose any branch.
3. Compare the expected totals from recorded sales with cash collected and the day's
   successful POS sales. Enter actual_cash and actual_pos; neither is autofilled.
4. Add notes explaining shortages/excesses, then Submit daily count.
5. A Manager or Admin reviews the latest submission and adds optional review notes.

Use cash collected for these sales less refunds/reversals paid today, excluding
opening float, cash introduced, withdrawals, and expenses. POS counts are successful
sales less POS refunds, before terminal fees, not bank settlement. There is no float/expense ledger or
terminal integration. Differences are actual minus expected: a negative amount is
a shortage and a positive amount is an excess. Review records the check and notes;
it does not erase the difference or record a payment to settle it.

## Records, dates, and corrections

The business day runs from midnight to the next midnight in Africa/Lagos (WAT,
UTC+1). API queries use explicit timezone-aware boundaries, independent of the
database/browser's timezone. A submission records its business date, original
expected/actual totals, differences, sales count, last sale ID, staff ID, notes,
and submitted_at. Review records reviewed_by, reviewed_at, and review_notes.
All event timestamps include offsets and display in Lagos time in the frontend.

Multi-product checkout counts as one purchase: expected totals use its complete
header amount once. Existing standalone sales are included separately; linked
checkout item rows are not counted again. sales_count now means customer purchases,
and last_sale_id remains the latest underlying item ID for detecting newer sales.

Counts are immutable snapshots. A correction creates a new revision for that
branch/date, preserving earlier counts and reviews. Only the latest, current
submission can be newly reviewed. If more sales arrive or recorded payment totals
change, the summary flags the latest submission as out of date and review returns
409. Recount and submit a new revision before reviewing it. Sales remain possible
after a review; this is a reconciliation history, not a permanent sales-day lock.

A reviewed snapshot stays reviewed in history even if later sales make it stale.
The summary shows that a new submission is needed. Repeated review requests return
the first review without changing its reviewer, date/time, or notes.

Historical sales with unknown payment methods are displayed separately in the
summary. Submission/review is blocked while such records exist for that day; their
amounts are never silently treated as cash or POS. A controlled correction workflow
for those historical methods is a future stage.

## API

- GET /reconciliations/summary?branch_id=1&business_date=2026-11-15 returns expected
  cash/POS, sale count, unknown-method amounts/counts, latest snapshot, and is_stale.
- POST /reconciliations requires an Idempotency-Key UUID, with this body:

```json
{
  "branch_id": 1,
  "business_date": "2026-11-15",
  "actual_cash": "50000.00",
  "actual_pos": "74900.00",
  "notes": "POS report is 100 below the recorded sales"
}
```

- GET /reconciliations supports optional branch_id, limit (1-500, default 100), and
  offset. It includes all revisions, review notes, and an is_latest marker.
- POST /reconciliations/{id}/review accepts {"notes": "Checked cash and terminal report"}
  and requires Manager/Admin. Staff may submit; they cannot review.

New submissions return 201. Same key/body/user returns the original snapshot and
timestamp without another revision, even if reviewed or superseded later. Read
history/summary for its current review state. A conflicting key returns 409.
Delivery-review-style retries are repeat-safe without another request key.
Unassigned Salespersons and requests for other branches receive 403. Missing
branches/records return 404; invalid amounts and future dates return 422. Signed net amounts are valid.
Monetary values use Decimal/NUMERIC, with signed differences returned as exact text.

The snapshot and duplicate-request result commit together. Branch locks serialize
sales, snapshots, and review so a review cannot accidentally ignore a sale that
committed first. Concurrent new submissions get different revision numbers; duplicate
requests create only one. No reconciliation changes inventory or sale records.

## Scope and verification

The migration is reconciliation_schema.sql, applied after sale_payments_schema.sql.
It adds daily_reconciliations and permits reconciliation in the existing request
ledger. It does not create real submissions or change business sales/stock.
Managers/Admins may submit and review counts, including their own; mandatory
separation of submitter/reviewer has not been requested or enforced.

Tests cover day boundaries, exact differences, branch isolation, unknown methods,
out-of-date snapshots, append-only revisions, duplicate and parallel submissions,
review retries, and rollback. Browser tests verify Salesperson submission, a POS
shortage, and Admin review on an isolated database. Multi-product checkout, cash
movements/expenses, settlement import, discrepancy resolution, and exports remain
separate stages.

## Approved cash movements

Expected drawer cash now includes approved opening floats, additions, expenses, deposits, withdrawals, and eligible shortage recoveries. This extends the sales/refund-only formula described above. Approval makes that day's previous count stale, including zero-effect same-day recoveries. No automatic opening carry-forward occurs. See [Cash movements](CASH_MOVEMENTS.md).

## Credit collections

Credit sales add revenue but no Cash/POS collected. Later repayments and signed
repayment reversals affect their own Lagos recording day. Expected Cash/POS now
includes those collections less actual refunds; debt-only return reductions do
not remove cash. Snapshot repayment count/last ID detect later activity. See
[CUSTOMER_CREDIT.md](CUSTOMER_CREDIT.md) for examples.
