# FESTY AGRIC SERVICES staff guide

Dates and times use Africa/Lagos (WAT). Use each staff member's own account.
Salespersons see their assigned branch. Managers/Admins can work across branches.

## Start a day

1. Sign in and check the branch filter.
2. Check that customer payments are recorded with their actual Cash/POS method.
3. Check available stock and physical expiry labels. Staff choose physical
   batches; the delivery history does not show quantities remaining per batch.

## Sales, credit and repayments

Sales now offers a till: choose the branch, browse Feeds/Veterinary medication/
Poultry equipment/Other products, and click products into the basket. Scan assigned
barcodes into search with a keyboard-style scanner. See CATEGORIES_AND_POS.md.

- Cash/POS sale: add all items to the cart, check the permitted discount and
  choose the method actually paid. Save once, then print the receipt.
- Credit sale: a Manager/Admin chooses **Credit - full amount owed** and an active
  registered customer in that branch. The entire sale starts owed. No deposit or
  mixed payment is supported. Do not enter it as Cash/POS until money arrives.
- Repayment: Manager/Admin opens **Customer credit**, chooses the invoice and
  records the actual amount and Cash/POS method. Partial payments are allowed;
  overpayment is rejected. Print the repayment receipt from history.
- Wrong repayment entry: use **Reverse entry**, give a reason, and enter the
  correct payment separately. Reversal is dated today, preserves the original,
  and changes today's expected collections. It does not contact a bank or refund
  money automatically. A payment already used for a customer refund cannot be
  reversed; reconcile the transaction with the Manager instead.
- Check a customer's full current debt using **Customers → View balance**.
  Credit history is paginated; never total only the visible page as a full balance.
- A credit return/void first reduces unpaid debt. Any remainder is an actual
  Cash/POS refund, and requires the method actually used. Only resellable returned
  goods go back into available stock. Never add the same refund as a cash expense.

If a connection fails, use **Retry saved request**. The locked form keeps the
original UUID and body, even after a reload and signing back in. Do not re-enter
the same real transaction with a fresh key: that would be a second transaction.

## Receiving and branch transfers

Managers/Admins receive deliveries, entering supplier batch/expiry labels when
known. Use separate receipts for different labels; never invent missing dates.
Dispatch removes stock from the sending branch and marks it in transit. The
receiving branch confirms only after physical delivery; stock becomes available
there upon confirmation. Record physical damage/shortage with the Manager rather
than confirming goods that did not arrive as expected.

## End-of-day collections

Cash ledger and drawer-movement entry have been removed. No staff member or
Admin needs to enter opening floats, cash transfers, deposits or expenses here.

Compare actual customer Cash/POS collections for the Lagos business date with
recorded sales and credit repayments, less refunds and payment reversals. Credit
sales are revenue, not money received until the customer pays. Historical reports
retain previously posted amounts rather than silently changing old records.

Submit the count; a Manager/Admin reviews it. Later transactions make that count
out of date: submit a new revision. Investigate differences, assign responsibility
and record a resolution explanation. Resolving a difference does not post money.
Record an explanation and check the underlying customer payments with the Manager.

## Admin routine

Review active staff/branches, price and discount permissions, in-transit stock,
unreviewed counts, customer debts and recent reversals. Check the daily backup
status and available disk space. Keep the computer and PostgreSQL running when
staff need access. Check off-device backups and perform periodic restore drills.
Do not put real test transactions into the business database.

## Add and edit products

Choose **Manage products** in the sidebar. The Add a
product and Edit product forms appear before the catalogue. Admins/Managers can
use Inventory's Create new product/Edit product buttons or an item's Edit product action
as shortcuts. Choose a product in the edit form to load its details, then save.
New catalogue items need a stock receipt before they can be sold. Salespersons
can view the catalogue but cannot add/edit products.


## Add delivered stock to a specific branch

1. Choose **Add stock** in the sidebar, or **Add stock to a branch** on Inventory.
2. Select the **branch receiving the goods**.
3. Select the product and enter the quantity delivered, in its base unit (for example, bags).
4. If the product does not exist, choose **Product not in the list? Create it here**.
   Save its name, category, unit and selling price. You return to the delivery form
   with the new product selected, keeping your branch and quantity. You can also
   go back without creating a product.
5. Optionally expand batch, expiry and notes. Check the summary and select
   **Add stock to branch**. This saves a delivery and increases only that branch's stock.
6. The confirmation shows the branch, received quantity and new stock balance.
   Choose **View this branch's stock** to see the filtered inventory.

Product details belong to the shared catalogue; saving them does not create stock.
For a product created directly in Manage products, **Add stock for this product**
opens the delivery form. Existing request keys still protect delivery retries.
Only Admins/Managers can create products and receive stock. Salespersons continue
using their assigned branch. No schema change is required for this workflow.
