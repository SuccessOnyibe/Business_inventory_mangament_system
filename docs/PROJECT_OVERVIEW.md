# FESTY AGRIC SERVICES Inventory Management System

## 1. Project Description

A web-based inventory management system for a family-owned
poultry and veterinary supplies business operating three branches
in Delta State, Nigeria.

The system will manage products, inventory, stock transfers,
sales, payments, and stock accountability across all branches.

## 2. Technology Stack

### Frontend
- HTML
- CSS
- Vanilla JavaScript

### Backend
- Python
- FastAPI

### Database
- PostgreSQL

### Version Control
- Git
- GitHub

## 3. Business Structure

The business operates three branches.

### Main Branch
- Sells poultry feed, veterinary medicines, vaccines,
  poultry equipment, and other supplies.
- Receives stock from suppliers.
- Can transfer stock to other branches.

### Branch 2
- Sells poultry feed, veterinary medicines, vaccines,
  poultry equipment, and other supplies.
- Can receive stock and transfer stock between branches.

### Branch 3
- Primarily sells poultry feed.
- Receives stock from the main branches.
- Operated by a salesperson who reports daily sales
  and payments to management.

## 4. Core Features

### Product Management
- Add new products.
- View existing products.
- Update product information.
- Deactivate products without deleting their history.

### Inventory Management
- Track stock quantities by branch.
- Record stock received from suppliers.
- Record stock movements.
- Transfer stock between branches.
- Record damaged or discarded stock.
- Perform physical stock reconciliation.

### Sales Management
- Record sales.
- Support different selling units and prices.
- Automatically update stock after sales.
- Track cash and POS payments.
- Record approved credit sales and customer payments.

### Accountability
- Maintain stock movement history.
- Track daily sales and payment reconciliation.
- Restrict sensitive operations based on user roles.
- Record corrections and adjustments for auditing.

## 5. User Roles

- Admin
- Manager
- Salesperson

Permissions will depend on the user's role.

## 6. Development Approach

- Build the backend first.
- Test APIs using FastAPI's interactive documentation.
- Develop the frontend after establishing core backend functionality.
- Use PostgreSQL transactions to protect inventory consistency.
- Implement features incrementally.
- Keep the project documentation updated.

## 7. Current Development Status

The backend is under development.

Completed foundations include:
- FastAPI setup.
- PostgreSQL connection.
- Branch and product tables.
- Inventory table.
- Stock movement table.
- Product management endpoints.
- Inventory retrieval endpoints.
- Initial testing of stock receiving using SQL transactions.

The next major task is implementing stock receiving through FastAPI.