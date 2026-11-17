# Backup and recovery

FESTY AGRIC SERVICES now has a local operator tool: `backend/backup.py`.
No database password needs to be pasted into chat. It uses the existing
`backend/.env` connection settings. This tool has no web endpoint.

## Create a backup

From the project folder in PowerShell:

```powershell
cd backend
.\.venv\Scripts\python.exe -B backup.py create
```

The command reads the configured database and creates a uniquely named folder
under `backups/`. A second backup creates a new folder; it never replaces one.
The working database is not changed. If PostgreSQL tools are elsewhere, use:

```powershell
.\.venv\Scripts\python.exe -B backup.py --pg-bin 'C:\Program Files\PostgreSQL\17\bin' create
```

Use `create --output 'D:\Festy-private-backups'` to choose another destination.
Keep the destination private. There are two files to keep together:

- `database.dump`: the actual PostgreSQL custom-format archive.
- `manifest.json`: UTC creation time, PostgreSQL version, table counts, and the
  archive's SHA-256 checksum (a fingerprint used to detect file changes).

The archive includes stock, sales, cash postings, audit history, user password
hashes and login sessions. Treat it as confidential. Backups are excluded from
Git, but Git exclusions do not stop OneDrive or other synchronization services.
Store an encrypted copy away from this computer using your organization's
approved storage. The tool does not encrypt, upload, schedule, rotate, or delete
backups. It does not back up `.env`, PostgreSQL server roles, or application files;
keep configuration and required credentials separately in secure storage.

One repeatable-read snapshot is shared between the table counts and `pg_dump`.
This means staff can continue working while the backup reads one consistent
committed state. A failed command may leave a `.partial` file or incomplete
folder: that is not a completed backup. Only a successful command followed by
a restore check establishes a usable backup.

## Verify a restore safely

Verification is for a **trusted archive made by this project**, not a file from
an unknown source. A checksum detects corruption; it does not establish who
created the file. Restoring a PostgreSQL archive can execute its stored SQL.

The verification command connects only to the dedicated disposable test instance
at `127.0.0.1:55439`, using `inventory_test`. It cannot target the normal business
server. Start that instance first; a default application installation does not
automatically include a running test instance.

```powershell
.\.venv\Scripts\python.exe -B backup.py verify '..\backups\FAS-backup-REPLACE-WITH-ACTUAL-FOLDER'
```

It checks the archive fingerprint before opening a database connection, creates
a new random `inventory_restore_test_*` database, restores in one transaction,
compares all public application table counts, and checks that restored foreign
key/check constraints are validated. It removes only the temporary database it
created, including after a restore failure. It never uses `--clean`, never
replaces existing tables, and accepts no operator-supplied restore database name.

The check demonstrates that PostgreSQL can restore the archive with matching
table counts and validated constraints. It is not a full business acceptance
test or a row-by-row comparison with a changing live database. The automated
test commits a new branch after snapshot export to verify that both the counts
and archive exclude this newer row, then removes that test row. If the process is
forcibly stopped, temporary databases can remain; have a developer inspect them
before any manual cleanup.

## When recovery is actually needed

Do not restore over the working database. Stop business writes, preserve the
current database and select a known-good verified backup with the operator.
A developer should restore into a **new recovery database** on a compatible
PostgreSQL installation and review branch quantities, recent receipts, transfers,
cash entries and user permissions before changing the application's connection.
If the backup predates a schema migration, apply the reviewed later migrations
to that recovery database before using it with the current application code.
Recreate the required database role and access permissions separately: the
archive deliberately omits source ownership and grants. Revoke restored login
sessions before reopening access. Records entered after the backup will require
a deliberate recovery plan; they are not included automatically.

Actual production recovery, encryption and off-device storage policy
remain separate operator tasks. Local scheduling is described below. No live restore is performed by this tool.

## Installed daily task

The current Windows user now has FestyAgricServices-DailyBackup, scheduled at
02:00 WAT. A manual invocation through Task Scheduler completed with result 0;
its archive also passed a full isolated restore check. The status file is
backups/last-backup-status.json. The PC must be awake and this user signed in.
See [Deployment](DEPLOYMENT.md) for rerunning, changing the destination and
limitations. Encrypted off-device storage and retention remain owner decisions.
