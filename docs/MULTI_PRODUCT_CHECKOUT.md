# FESTY AGRIC SERVICES: Multi-product Checkout and Receipts

Voids/returns are now supported through Manager/Admin approval. See
SALE_VOIDS_AND_RETURNS.md. Reprinting a corrected original shows its immutable
original items, linked corrections, refunded/reversed total, and remaining net amount.

## Frontend workflow

1. Open Sales and choose the selling branch.
2. Choose a product, whole-unit quantity, and unit price, then click Add item.
3. Repeat for the other products. Quantities/prices can be edited in the cart and
   items removed before checkout. Adding the same product at the same price merges
   quantities; use the existing cart row to change its price.
4. Choose one Cash or POS terminal payment for the entire purchase. Customer and
   notes are optional. Click Complete sale.
5. Use Print receipt to print or Save as PDF through the browser. Purchase history
   also offers Print receipt for earlier purchases.

One selected product can be completed directly without first clicking Add item.
If a cart already exists, add any newly selected product before completing it; the
page does not silently discard a selected extra product. A cart supports 1-100
different products, with one row per product. Discounts stay within each product's
Admin-approved limit. Salespersons are restricted to their assigned branch.

Draft carts are held in memory. Submitted requests retain their UUID/body in tab
storage for safe retry after network loss or reload. Do not close the tab while a
request is unconfirmed. Existing pending standalone-sale requests still use their
original endpoint/key; the frontend can finish and print them without duplication.

## Receipts and dates

A new purchase receives a unique FAS-00000001-style number. Its receipt contains:
FESTY AGRIC SERVICES, branch, salesperson, customer (or walk-in), item names/units,
quantities, actual unit prices, line totals, purchase total, Cash/POS method, and
timezone-aware date/time displayed in Africa/Lagos (WAT). Branch/staff names and
item/price/unit details are snapshots; later catalogue/account edits do not rewrite
new receipts. Printing again does not create a new sale or timestamp.

Print media shows only the selected receipt, not the application navigation or
other customers' history. The browser chooses the printer or PDF destination.
No address, phone number, VAT/tax identity, or POS reference has been invented.

Older standalone sales remain visible and printable with a FAS-S-00000001-style
identifier. Their original price/product/unit/time values are preserved. Those old
records did not store branch/staff-name snapshots, so legacy reprints resolve the
current branch and username. Historical unknown payment methods remain Not recorded.

## API

POST /checkouts requires login and an Idempotency-Key UUID:

```json
{
  "branch_id": 1,
  "payment_method": "pos",
  "items": [
    {"product_id": 1, "quantity": 2, "unit_price": "24000.00"},
    {"product_id": 2, "quantity": 3}
  ],
  "customer_name": "Regular customer",
  "notes": "Approved customer discount"
}
```

Omitting an item's unit_price uses the current catalogue price. The server
calculates all totals. Duplicate product rows, fractional/nonpositive quantities,
extra client totals, and out-of-policy prices are rejected. Items are normalized
into product-ID order, including for idempotency: reordered identical items are
the same request. Do not change fields originally omitted on a retry.

- GET /checkouts lists new purchases and old standalone sales together, with
  branch_id, limit, offset, receipt_type, receipt_number, item count, total, and time.
  Linked new receipt items are not separately listed as extra purchases.
- GET /checkouts/{id} returns the full new receipt and its items for printing.
- GET /sales/{id}/receipt returns a full legacy standalone receipt.
- POST /sales remains compatible with the previous single-product API.
- GET /sales remains item-level history; new receipt items are sales rows. Use
  /checkouts to count customer purchases and /reconciliations/summary for daily totals.

Missing records return 404, branch violations 403, insufficient stock/inactive or
unpriced products 409, and invalid items/prices 422. Duplicate keys return the
original saved result; key/body/user conflicts return 409. Receipt reprints require
the same branch access as viewing the purchase.

## Transactions and reconciliation

The sale_orders header, all sales item rows, every stock deduction/movement, and
the saved request response share one transaction. If even the last item fails,
earlier deductions and the entire purchase roll back. A failed checkout does not
consume its request key. Branch and product locks follow a consistent order;
duplicate or competing purchases cannot partially consume a cart or oversell.

One purchase has one header payment/total. Each stock movement references its
individual sales item. Reconciliation combines new headers with standalone sales
whose order_id is NULL. It counts a multi-item purchase once and includes its full
amount once, using its recorded Lagos business date. Earlier standalone sales and
reconciliation snapshots remain intact. New purchases can mark a prior daily count
out of date, just as earlier single-product sales did.

## Migration and verification

Apply checkout_schema.sql after reconciliation_schema.sql. It creates sale_orders,
adds nullable sales.order_id with a unique order/product index, and extends the
request ledger's operation check. It does not rewrite stock or historical sales.

Tests verify last-item/movement failures roll back the entire cart, snapshots,
discount rules, duplicate/concurrent checkout, branch access, legacy history, and
purchase-based reconciliation. Browser tests exercise a two-product purchase,
exact totals, Cash/POS retry across reload, print-only styling, and PDF generation
against an isolated database. Returns/voids now have their own documented workflow;
mixed payments, cash change, and tax calculation remain later stages.
