# Database Design

## 1. Database Information

Database: business_inventory_db
Database Management System: PostgreSQL

The application connects using a dedicated database user:
inventory_app

Database credentials are stored in backend/.env and must
never be committed to GitHub.

## 2. Tables

### branches

Stores information about the business's three branches.

Columns:
- id: INTEGER, primary key, automatically generated
- name: VARCHAR(100), required
- type: VARCHAR(50), required

Current records:
- 1: Main Branch (General)
- 2: Branch 2 (General)
- 3: Branch 3 (Feed Only)

### products

Stores products available in the business.

Columns:
- id: INTEGER, primary key, automatically generated
- name: VARCHAR(150), required
- category: VARCHAR(50), required
- base_unit: VARCHAR(30), required
- is_active: BOOLEAN, required, defaults to TRUE

Examples:
- Chikun Starter Feed: Feed, bag
- Ultima Grower Feed: Feed, bag
- Newcastle Vaccine: Vaccine, vial
- Amprolium: Medicine, sachet
- Poultry Drinker: Equipment, piece
- Top Feed Starter: Feed, bag

Products are stored independently of branch inventory.

### inventory

Stores current product quantities at each branch.

Columns:
- id: INTEGER, primary key, automatically generated
- branch_id: INTEGER, required, references branches(id)
- product_id: INTEGER, required, references products(id)
- quantity: INTEGER, required, defaults to 0

Constraints:
- Quantity cannot be negative.
- Each branch/product combination must be unique.

A product can exist at multiple branches with different
stock quantities.

### stock_movements

Records changes to inventory quantities.

Columns:
- id: INTEGER, primary key, automatically generated
- branch_id: INTEGER, required, references branches(id)
- product_id: INTEGER, required, references products(id)
- quantity_change: INTEGER, required
- movement_type: VARCHAR(30), required
- notes: TEXT, optional
- created_at: TIMESTAMPTZ, required, defaults to NOW()

Constraints:
- quantity_change cannot equal zero.

Positive quantity changes represent stock increases.
Negative quantity changes represent stock decreases.

Examples of planned movement types:
- stock_received
- sale
- transfer_in
- transfer_out
- damage
- adjustment

Movement types are not yet restricted by a database constraint.

## 3. Table Relationships

branches (1) ---- (many) inventory

products (1) ---- (many) inventory

branches (1) ---- (many) stock_movements

products (1) ---- (many) stock_movements

Foreign keys ensure that inventory records and stock
movements reference existing branches and products.

## 4. Inventory Transactions

Inventory changes should update both:
1. The inventory table.
2. The stock_movements table.

These operations must occur inside the same database
transaction.

If either operation fails, neither change should be saved.

## 5. Completed Transaction Test

Test scenario:
- Branch: Main Branch (ID 1)
- Product: Chikun Starter Feed (ID 1)
- Initial quantity: 50 bags
- Quantity received: 100 bags
- Final quantity: 150 bags

Operations:
1. BEGIN
2. UPDATE inventory
3. INSERT INTO stock_movements
4. COMMIT

Result:
- Inventory updated successfully.
- Stock movement recorded successfully.
- Transaction committed successfully.

## 6. Important Design Decisions

- Products are shared across branches.
- Inventory quantities are tracked separately for each branch.
- Stock movements record changes rather than current balances.
- Product deactivation is preferred over deleting historical products.
- Stock changes should be traceable.
- Database transactions protect consistency.

## 7. Future Database Improvements

Planned additions include:
- Users and roles
- Sales and sale items
- Payments and daily reconciliation
- Branch stock transfers
- Customer credit accounts
- Product batches and expiry dates
- Inventory adjustments
- Audit records

The current inventory model uses integer quantities.

Additional modelling will be required for:
- Feed sold by bag, paint, half-paint, or naira amount.
- Prepackaged retail feed at Branch 3.
- Eggs sold by crate or individually.
- Damaged stock converted into retail stock.

These requirements should be addressed before implementing
the corresponding sales and stock operations.