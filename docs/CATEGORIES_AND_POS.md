# Product departments and supermarket-style checkout

FESTY AGRIC SERVICES now presents products in four departments:

| Department | Existing labels shown here |
| --- | --- |
| Feeds | Feed, Feeds, Poultry feed |
| Veterinary medication | Medicine, Medication, Vaccine and plural forms |
| Poultry equipment | Equipment, Poultry equipment |
| Other products | Other and unrecognized/custom categories |

Inventory and Products & pricing have category buttons, search and department
tables. Quantities keep their own base units: feed bags are not added to medicine
vials as one stock total. Category badges count distinct products, not quantities.
Department table record counts can include a product at several branches.

Existing stored categories are not rewritten. Vaccine and Medicine remain valid
stored labels but appear under Veterinary medication. New product forms offer
the four standard departments. Editing retains the old category as a labelled
option, so changing a price does not silently reclassify the product. Managers/
Admins can choose another category explicitly.

## Product order

Products display A-Z within each department in Inventory, Manage products and
Sales. Sorting ignores letter case and treats numbers naturally (Feed 2 before
Feed 10). Repeated inventory rows for the same product sort by branch name.
Product-selection dropdowns are alphabetical too. These are display-only sorts:
stock quantities, product IDs, stored records and existing receipts are unchanged.

## Using the till

1. Open Sales and choose the sale branch. Salespersons use their assigned branch.
2. Select a department or search by product name, barcode or item number.
3. Click Add to basket. Clicking again adds one unit at the existing cart price.
   Edit quantities and permitted discounts in the basket. Manual product/quantity/
   price controls remain available for larger quantities.
4. Check the total and actual Cash/POS payment, or Manager/Admin credit with a
   registered customer. Complete the sale and print the receipt.
5. The till retains the branch and returns focus to search for the next customer.
   Stock refreshes after the sale. The latest receipt appears below the till.

Product buttons show branch stock and base units. Inactive products are omitted;
unpriced and out-of-stock products cannot be added through the buttons. Displayed
stock is a snapshot: the server still checks current stock, prices, discounts and
permissions atomically at checkout. Retry a saved locked request after a lost
response rather than entering the same real sale again with a fresh request key.

## Optional barcodes

Admins/Managers can set a printed barcode in Products & pricing. It is optional,
exact text up to 64 printable non-space ASCII characters. Leading zeroes stay
intact. Duplicate codes return 409 without saving other edits. Omitting a barcode
in the API preserves it; explicit null/blank clears it. Existing codes and prices
are never guessed.

Use a keyboard-style USB/Bluetooth scanner that types the code and sends Enter,
with the till search field focused. Typing the code and Enter works too. An exact
assigned code adds one unit; unknown codes do not charge anything. Internal item
numbers such as `#000001` also work with their `#` prefix and Enter. Name search
shows matches to choose rather than guessing a product.

Browser tests simulate keyboard input. A physical scanner has not been tested;
serial/network scanners need their own integration. Bag sizes or product variants
should remain distinct catalogue products when sold at different prices; no bag
weights or unit conversions are invented by this change.

## Schema and testing

Apply product_barcodes_schema.sql after credit_schema.sql. It adds nullable unique
products.barcode and a format constraint. Product GET/POST/PATCH includes barcode;
existing Manager/Admin permissions protect catalogue edits. Department grouping
uses category. Migration does not change quantities, prices, stored categories,
sales or historical receipt snapshots.

Tests cover barcode validation, uniqueness and rollback, permissions, department
separation, product buttons, scanner input, checkout/retry/credit/returns and
desktop/mobile layout, with business writes restricted to isolated databases.


## Instant Sales search suggestions

Click the Sales search box or start typing to see up to 12 active matching
products directly below it. Matches are alphabetical and show price/unit plus
available stock for the selected branch. Partial names, categories, barcodes and
item numbers use the loaded catalogue, with no network request per keystroke.
Typing searches across categories so an old category selection cannot hide a match.

Click a suggestion to add one unit, or use Arrow Up/Down and Enter. Escape/clicking
outside closes the list. Enter on a partial name with several matches highlights
a choice instead of reporting a barcode error or silently adding a random product.
Exact barcode/scanner matches still work. Choose a sale branch before adding;
normal pricing, stock and pending-request protections remain in force.
