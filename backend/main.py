"""Application setup, router registration, health checks and frontend hosting."""

from pathlib import Path as FilePath
import os

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from accounts import router as accounts_router
from auth import router as auth_router
from credit import router as credit_router
from customers import router as customers_router
from database import db_connection
from inventory import router as inventory_router
from products import router as products_router
from reconciliations import router as reconciliations_router
from reports import router as reports_router
from sale_corrections import router as sale_corrections_router
from sales import router as sales_router
from stock_adjustments import router as stock_adjustments_router
from stock_receipts import router as stock_receipts_router
from stock_transfers import router as stock_transfers_router


app = FastAPI(title="FESTY AGRIC SERVICES Inventory API")
app.include_router(auth_router)
app.include_router(accounts_router)
# Routers own workflows; this module only assembles the application.
app.include_router(products_router)
app.include_router(inventory_router)
app.include_router(stock_receipts_router)
app.include_router(stock_transfers_router)
app.include_router(customers_router)
app.include_router(sales_router)
app.include_router(sale_corrections_router)
app.include_router(credit_router)
app.include_router(reconciliations_router)
app.include_router(stock_adjustments_router)
app.include_router(reports_router)
if os.getenv('APP_ALLOWED_HOSTS'):
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host.strip() for host in os.environ['APP_ALLOWED_HOSTS'].split(',') if host.strip()])


@app.middleware('http')
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    if request.url.path.startswith('/app'):
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    if request.url.scheme == 'https':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response


@app.get('/health')
def health():
    return {'status':'ok'}


@app.get('/health/ready')
def readiness():
    try:
        with db_connection() as connection:
            ready = connection.execute("""SELECT to_regclass('public.credit_repayments') IS NOT NULL
                AND to_regclass('public.customer_changes') IS NOT NULL AND EXISTS (
                SELECT 1 FROM information_schema.columns WHERE table_schema='public'
                AND table_name='products' AND column_name='barcode')""").fetchone()[0]
        if ready:
            return {'status':'ready'}
    except Exception:
        pass  # Never expose credentials or database errors through public probes.
    raise HTTPException(status_code=503, detail='Database or required schema unavailable')


@app.get("/")
def home():
    return {"message": "FESTY AGRIC SERVICES Inventory API is running"}


# Serve only the public frontend folder, never backend configuration or credentials.
app.mount('/app', StaticFiles(directory=FilePath(__file__).resolve().parents[1] / 'frontend', html=True), name='frontend')
