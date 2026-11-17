# Deployment preparation

The app is ready for a local release check. Render Free + Neon Free staging preparation is documented in [FREE_HOSTING.md](FREE_HOSTING.md).
The Free sample staging app is live at
https://festy-agric-staging.onrender.com/app/ (Frankfurt), using Neon PostgreSQL.
Render manages its HTTPS address; no custom domain or PC firewall changes were
needed. Production business-data migration and cloud backup recovery are pending.
The local Caddy instructions below are an alternative, not the active deployment.

## Local release on this Windows PC

Run the read-only check from backend:

```powershell
.\.venv\Scripts\python.exe -B release_check.py
```

It checks required tables, an active Admin, branch assignments, stock/credit
invariants and validated constraints, without printing customer details or
passwords. Warnings require an operator review; success does not certify physical
stock, off-device backups, staff training or external hosting readiness.

Start the release server from the project root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_release.ps1
```

Open `http://127.0.0.1:8001/app/`. It uses two workers, no development reload,
loopback binding and trusted proxy headers from loopback only. Closing the runner
stops the server. The existing development command on port 8000 is unchanged.
`GET /health` is process liveness; `/health/ready` also checks database/schema
availability and returns a generic 503 on failure. Probes disclose no credentials.
Database connections have a five-second connection timeout.

The PowerShell execution-policy option applies only to that process, because
this PC blocks unsigned script files by default; it does not change system policy.
The server adds no-store, clickjacking and MIME protections and a self-only content
policy for frontend pages. API documentation stays available locally. Production
host allowlisting is set by APP_ALLOWED_HOSTS, with comma-separated hostnames.

## Branch access through HTTPS (requires host/domain)

On a suitable always-on server, create a least-privileged application database
role with access to required tables/sequences. Keep schema migration permissions
separate. Provision backend/.env privately; never include it in Git or a public
web directory. Install the pinned Python requirements in a virtual environment,
and use matching PostgreSQL client tools for backups.

Point a domain you control at the server and install Caddy. Review
`deployment/Caddyfile.example`, replace the example hostname and use:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_local_release.ps1 -AllowedHosts 'inventory.YOUR-DOMAIN,localhost,127.0.0.1'
```

Configure Caddy in front of `127.0.0.1:8001`; permit only the needed HTTPS/HTTP
certificate ports to Caddy, not direct public access to PostgreSQL or Uvicorn.
The [official Caddy reverse-proxy guide](https://caddyserver.com/docs/quick-starts/reverse-proxy)
explains automatic HTTPS, hostname/DNS and certificate port requirements.
The example configuration has not been exercised here because Caddy is absent.
Do not use the example domain or publish plaintext HTTP for remote staff.

Configure automatic startup/restart for both processes under a dedicated service
account on the chosen host. Then verify HTTPS, real-device branch access, role
isolation, backups and restore recovery before business go-live. Those remote
checks require the selected infrastructure and owner approval of business data.

## Backup automation

`scripts/install_backup_task.ps1` installs a current-user task named
`FestyAgricServices-DailyBackup` at **02:00 WAT daily**. It checks the PC timezone,
uses limited privileges, stores no Windows or PostgreSQL password in task arguments,
and does not overwrite an unrelated task at a different project location.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_backup_task.ps1 -WhatIf
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_backup_task.ps1
```

This interactive-user task requires that user to be signed in, the PC awake and
PostgreSQL available. Missed runs start when available. It does not wake the PC
or operate while fully logged out; an always-on server/service-account schedule
must be configured on the deployment host for unattended business availability.

The runner creates unique archives and checks their structure, then writes
`backups/last-backup-status.json` with success/failure and a Lagos timestamp.
Check freshness and Task Scheduler's LastTaskResult, not merely task existence.
Scheduled structure checks are not full restore drills. Run the isolated restore
verification periodically using BACKUP_AND_RECOVERY.md. Archives are never
automatically deleted or uploaded. Monitor disk space and choose a retention and
encrypted off-device storage policy with the owner. Git exclusions do not prevent
OneDrive synchronization of this project's folder.

Change the destination using `-BackupRoot 'D:\PRIVATE-BACKUP-PATH'` only after that
storage exists and its access/encryption has been checked. No backup drive or
external account is assumed or provisioned by this project.
