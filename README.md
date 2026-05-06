# SSMS Backend

Django REST Framework backend for the Stock and Sales Management System.

## Scope in this scaffold

- Tenant and store-aware data model
- Product catalog with inventory, restocking, barcode registration, and expiry alerts
- Customer records with cached debt and credit balances
- Sales workflow with per-line pickup/payment states and pending list prioritization
- JWT-ready API configuration and media support for product images or voice notes

## Setup

1. Create and activate a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and update the database settings.
4. Run `python manage.py makemigrations` and `python manage.py migrate`.
5. Start the server with `python manage.py runserver`.

## Notes

- The settings fall back to SQLite when `DB_NAME` is empty, which keeps local bootstrapping simple while preserving PostgreSQL support for the target deployment.
- Multi-tenancy is row-based. Requests resolve the active tenant from the authenticated user first, then from the `X-Tenant-Slug` header.
