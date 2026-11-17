# Free staging deployment: Render + Neon

Prepared: 17 November 2026, Africa/Lagos (WAT).

This deploys sample data first. It does not publish or copy the local business
database. Hosting can remain free while usage fits the providers' free limits.
There is no account access or cloud deployment configured in this workspace yet.

## 1. Create the two free accounts

Sign up at https://render.com and https://neon.com. GitHub sign-in is fine.
Select Free plans. No domain purchase is needed. Keep passwords and connection
strings private; do not put them in Git, chat, screenshots, or terminal commands.

## 2. Create an empty Neon staging database

Create a Neon Free project named `festy-agric-staging`. Choose PostgreSQL 17 and
an available region reasonably close to Nigeria; choose the same region in Render
where available. Inside the project create a database named **festy_staging**.
Neon's project/development branch names are database environments, not the
business's Main Branch/Branch 2/Branch 3.

Open **Connect**, choose festy_staging and turn **Connection pooling off** for
initial setup. Copy the direct connection string, including sslmode=require and
channel_binding=require. You do not need to share it with anyone.

## 3. Initialize only the staging database from this PC

From the project root:

```powershell
.\backend\.venv\Scripts\python.exe -B backend/setup_staging.py
```

Paste the Neon direct connection string at the hidden prompt. Choose your staging
Admin username and a new password of 12-128 characters. This is the web-app login;
it is separate from your Neon account and database credentials.

The command accepts only an encrypted direct Neon target named festy_staging.
It refuses an occupied database and never falls back to backend/.env. All schema
files, three branch records, three clearly labelled SAMPLE products, ten units of
each at Main Branch, movement history and the Admin account commit together.
Failure rolls the entire setup back. Re-running on a completed database is refused.
No shared/default Admin password is shipped. This is not a production migration tool.

Keep the local backend/.env unchanged. Your local business app continues using
its existing PostgreSQL database. Do not add the staging URL to that file.

## 4. Create the Render Free web service

Once these files are on GitHub, in Render choose **New > Blueprint**, connect the
Business_inventory_mangament_system repository, select main and use render.yaml.
Review the resources: exactly one **Free web service**, no Render database or paid
resource. The database lives separately in Neon. If a dashboard suggests a paid
resource, return to Free before continuing.

Enter these environment variables when prompted (use Neon's Connect details):

| Variable | Value |
| --- | --- |
| DB_HOST | Neon hostname, without a scheme or slash; the pooled hostname may be used for the running app |
| DB_USER | Neon database role, not the web-app Admin username |
| DB_PASSWORD | Neon database password, entered privately in Render |
| DB_NAME | festy_staging (already configured) |
| DB_PORT | 5432 (already configured) |
| PGSSLMODE | require (already configured) |
| PGCHANNELBINDING | require (already configured) |

The app currently reads the separate DB_* settings, **not DATABASE_URL**. Copy
component values from Neon's connection details; do not paste the whole URL into
DB_HOST. The Render values never go into the repository. For the database password,
use the original password shown by Neon, not a URL-percent-encoded representation.

The repository root must remain the Render root: backend/ needs sibling frontend/
and docs/. render.yaml installs backend/requirements.txt and starts one Uvicorn
worker on Render's PORT. .python-version selects the Python 3.13 family used locally.
Only Render's managed proxy exposes this process; it terminates HTTPS and forwards
scheme headers. The start command trusts that managed proxy and allowlists the
service's exact RENDER_EXTERNAL_HOSTNAME. Do not reuse that proxy trust setting
for a server directly exposed to untrusted clients.

Automatic deployment on future commits is off; use **Manual Deploy > Deploy latest
commit** for reviewed changes. Creating the service still performs its first deploy.
No schema or sample setup runs automatically at startup or build time.

## 5. Verify the online staging app

Open the service's assigned HTTPS address with `/app/` appended. Sign in with the
staging Admin account from step 3. Check `/health/ready` once: it should say ready.
The Render health check uses `/health`, which does not wake Neon on every probe.

Test only sample transactions: receiving to a branch, dispatch and confirmation,
cash/POS checkout, credit, repayments, returns and reports. Create a test Salesperson
assigned to Branch 2 and check that it cannot view another branch's stock. Test on
phones and a device at each location. Close your local server to confirm online
access is independent of this PC.

## Limits, backups and production cutover

Render Free sleeps after idle periods; the next visit may take around a minute.
Neon Free also scales to zero and has storage/compute/transfer limits. Check both
dashboards and current plan documentation. This is not guaranteed always-on hosting.

Local filesystem files on Render Free are temporary: never store the only backup
there. Your existing Windows backup task still backs up the LOCAL database, not
Neon. Do not treat that task as coverage for online records. Before real business
use, configure separate encrypted off-host backups for Neon and perform a restore
drill. Neon Free's short restore window does not replace those archives.

Production go-live remains a separate step: inspect readiness, use a separate
production database and limited application role, take a verified local backup,
pause local transaction entry, migrate/verify data and balances, then switch all
branches to the online app. Do not enter real transactions independently into local
and staging copies: they do not synchronize. The staging sample database must not
be mistaken for the business's real inventory.

Official references:

- https://render.com/docs/deploy-fastapi
- https://render.com/docs/blueprint-spec
- https://render.com/docs/python-version
- https://render.com/docs/free
- https://neon.com/docs/connect/connect-from-any-app
- https://neon.com/pricing
