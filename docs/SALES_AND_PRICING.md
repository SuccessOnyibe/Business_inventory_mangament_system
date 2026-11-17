# Whole-unit Sales, Prices, Discounts, and Timestamps

The frontend now uses multi-product checkout. See MULTI_PRODUCT_CHECKOUT.md for
cart purchases, printable receipts, and purchase-based reconciliation. The single-
product POST /sales API described below remains supported for existing clients.

## Set a product price

Admins and Managers can set selling_price through POST /products or
PATCH /products/{product_id}. Only Admin can set max_discount_percent, including
on product creation. The limit is per product, and defaults to 0% (no discount).
Existing products start with no price; set one before recording a sale.

Admin example, PATCH /products/1:

```json
{"selling_price": "25000.00", "max_discount_percent": "5.00"}
```

A Salesperson can then sell that item for NGN 25,000.00 down to NGN 23,750.00
per base unit. The limit is checked on the server for every new sale, and also
enforced by a database check against the price/policy saved on the sale.
A fractional-kobo minimum is rounded upward: a 5% limit on NGN 10.01 permits
NGN 9.51, not NGN 9.50. Money uses Decimal/NUMERIC and is returned as text with two
decimal places; do not calculate money using binary floating-point numbers.
Prices above the catalogue price or below the permitted minimum return 422.
The same discount rules apply to all roles when recording a sale.

Managers cannot change the Admin's percentage limit. Product responses include
selling_price and max_discount_percent, so a future frontend can display them.
The planned Admin Add Product form will call the existing product creation API.

## Record a sale

POST /sales requires login and an Idempotency-Key UUID, as receipts/transfers do.
Salespersons can sell only at their assigned branch; Admins/Managers can choose any.
This first version records one product per request, in whole base units only.

```json
{
  "branch_id": 1,
  "product_id": 1,
  "quantity": 2,
  "unit_price": "24000.00",
  "payment_method": "pos",
  "customer_name": "Regular customer",
  "notes": "Agreed customer discount"
}
```

Omit unit_price to use the catalogue selling price. Supply a lower unit_price to
give a permitted discount. Customer name and notes are optional. The API calculates
total_amount itself (quantity multiplied by unit_price); clients cannot submit a
total or override the discount policy. Currency for this version is NGN.
payment_method is required and must be cash or pos. It is saved with the sale and
returned in creation/history responses. Changing it on a retry is a different body
and returns 409. Old sales without recorded methods stay null (Not recorded), and
are never assumed to have been cash. Apply sale_payments_schema.sql after the pricing
migration; it adds only the nullable historical field, with no invented backfill.

The transaction saves the sale, deducts inventory, records a linked sale movement,
and saves the duplicate-request response together. Any failure rolls back all four.
Missing products/branches return 404; inactive/unpriced products and insufficient
stock return 409; invalid numbers/quantities and excessive discounts return 422.
Concurrent sales and transfers cannot consume the same available stock twice.

Reusing the same key/body/user returns the original sale, balance, price, and
timestamp. Changing the body or using someone else's key returns 409. For retries,
send the same fields originally supplied; do not replace an omitted unit_price
with a price after the fact. New keys represent new sales.

## History and recorded date/time

GET /sales lists visible sales newest first, with optional branch_id, limit
(default 100, maximum 500), and offset. Salespersons see only their assigned branch.
Every sale stores quantity, actual unit price, original catalogue price, permitted
discount percentage, product-name/unit snapshots, customer/notes, seller ID, and
created_at. Later product edits never change those historical values.

Every sale and transfer has a PostgreSQL TIMESTAMPTZ date/time in its operational
record. API timestamps use ISO 8601 with an explicit offset, for example
2026-11-15T15:34:47+01:00 (illustrative). Display these in Africa/Lagos (WAT, UTC+1)
in the future frontend and on printed receipts or transfer records. Keep the full
timestamp when exporting; avoid ambiguous date-only or time-only records.

- Sale creation and sale history include created_at.
- Transfer dispatch includes created_at.
- Transfer confirmation includes the original created_at and received_at.
- Transfer history includes both timestamps (received_at is null while in transit).
- Stock movement history retains its created_at and links through sale_id/transfer_id.
- Retries preserve the original event dates/times; they do not create a new event.

The database history is the transaction documentation; Markdown files describe the
workflow and fields. No real sales or transfers are generated just to update docs.
Legacy saved transfer responses predate the new response fields; they remain intact.

## Current limits

Cash/POS method recording, daily reconciliation, and multi-product receipts are
implemented. Terminal integration, settlement verification, split/partial payments, credit balances,
refunds/voids, fractional selling units, and tax calculations are not implemented.
A method is an operator-reported payment record; settlement verification needs a separate stage.
Apply sales_pricing_schema.sql once after branch_transfers_schema.sql on a new
database. Existing stock, accounts, and historical movements are not rewritten.
