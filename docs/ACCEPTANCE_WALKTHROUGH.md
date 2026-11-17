# First-release business walkthrough

The automated suite uses disposable PostgreSQL databases and test accounts.
These are acceptance scenarios to review with the business owner; automation
cannot establish whether physical goods, bank records or opening balances match.

| Scenario | Expected result |
| --- | --- |
| Cash/POS checkout, multi-item and permitted discount | One receipt; exact amounts; stock deducted once |
| Lost successful response, reload, sign in and retry | Same receipt; no second deduction |
| Credit sale by Salesperson | Rejected; no stock/debt changes |
| Manager credit sale for active branch customer | Stock deducted; full debt; revenue increases; collected cash/POS unchanged |
| Partial Cash then POS repayment | Debt reduces; each method increases expected collections on payment day; revenue unchanged |
| Two concurrent payments exceeding debt together | Only one succeeds; debt cannot become negative |
| Unpaid credit return | Debt reduces; no cash payout |
| Part-paid credit return/void | Unpaid portion reduces debt; paid portion refunds actual method; stock restored only if resellable |
| Mistaken repayment reversal | Signed audit entry today; original intact; repeated reversal rejected |
| Customer inactive or in another branch | New credit sale rejected; existing debt can still be paid |
| Customer balance after contact edit/deactivation | Same stable identity and debt; audit version retained |
| Dispatch, then receiving confirmation | Stock in transit unavailable; destination credited once on confirmation |
| Staff access to another branch | Server rejects it, including direct API calls |
| Cash ledger removed | No ledger navigation/forms for any role; all legacy entry URLs return 404 |
| Archived adjustments | Removing entry features does not rewrite old financial snapshots |
| Later credit payment or refund | Posting-day collections change; original-day sales revenue retained |
| Counts, review, later transaction | Old snapshot intact and flagged out of date |
| Stock adjustment conflicts with a new sale | Stale count rejected instead of overwriting stock |
| Receipts/CSV and malicious customer/product text | Text rendered safely; no formulas/scripts executed |
| Backup and isolated restore | Archive checksum, schema constraints and table counts verified; business source read only |

Before live use, the owner must confirm branch assignments, product units/prices,
physical opening stock, opening cash and existing customer debts. This release
does not invent opening debts from past receipts. Agree a controlled migration
for any real debts that predate the credit ledger; never create fake stock sales
to represent those balances. Owner/staff walkthrough sign-off remains pending.
