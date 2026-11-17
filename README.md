# FESTY AGRIC SERVICES Inventory Management System

A web-based inventory management application for
a family-owned veterinary and poultry supply business.

## Features

- Multi-branch inventory tracking
- Product management
- Stock receiving and transfers
- Sales recording
- Retail inventory management
- Financial reconciliation
- Reporting
- Branch customer directory, credit sales and repayments

## Technology Stack

- Frontend: HTML, CSS, JavaScript
- Backend: Python, FastAPI
- Database: PostgreSQL

## Status

Locally tested first-release candidate. Remote hosting and owner business acceptance remain pending.

## Run locally

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open http://127.0.0.1:8000/app/ and sign in with your existing inventory account.
API documentation remains at http://127.0.0.1:8000/docs.
See docs/FRONTEND.md for product creation, Cash/POS sales, stock, and transfer workflows.

See [Backup and recovery](docs/BACKUP_AND_RECOVERY.md) for creating consistent
database backups and checking restores on the isolated test server.

The [customer credit guide](docs/CUSTOMER_CREDIT.md) explains contacts,
credit sales, repayments and debt/refund accounting.

See [staff guide](docs/OPERATIONS_GUIDE.md), [business walkthrough](docs/ACCEPTANCE_WALKTHROUGH.md),
and [deployment/backup automation](docs/DEPLOYMENT.md) for first-release operation.

[Release status](docs/RELEASE_STATUS.md) records completed checks and the remaining
business/hosting choices. Daily local backups run at 02:00 WAT while this PC is
awake and the current user is signed in.

The [department and POS guide](docs/CATEGORIES_AND_POS.md) covers categorized
inventory, the supermarket-style till and optional barcode scanning.

See [backend structure](docs/BACKEND_STRUCTURE.md) for workflow routers and shared helpers.
