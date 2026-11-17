# Cash ledger removed

The business owner removed the cash-ledger feature on 16 November 2026. The
Cash ledger screen, navigation, entry forms, request/approval controls and API
routes have been removed for every role. There is no replacement drawer workflow.

Cash/POS customer payments, credit repayments, refunds and daily reconciliation
remain available. Reconciliation compares customer collections for the business
day; it does not require cash transfers, expenses or opening-float entries.

Existing database tables and historical records are retained without deletion.
Previously posted amounts remain included when reading older financial reports
and snapshots, so removing the feature cannot silently rewrite past totals.
Legacy storage fields in report JSON/CSV exist for that compatibility, not for new
cash posting. All old cash movement/request/recovery URLs now return 404.

Historical schema migration files remain in the documented installation chain
because later migrations and old snapshots reference those tables. Keeping the
storage does not re-enable the removed application routes. No business database
writes or schema migration were needed for this removal.
