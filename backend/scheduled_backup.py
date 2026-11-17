"""Scheduled local backup with an operator-readable result; never deletes archives."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import backup


def run(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    status_path = destination / 'last-backup-status.json'
    try:
        settings = backup.database_settings()
        folder = backup.create_backup(destination, settings)
        # Listing validates archive structure without needing the restore server.
        # Full restore checks remain a separate periodic operation.
        backup.run_postgres(backup.postgres_tool('pg_restore'), ['--list',str(folder/'database.dump')], settings)
        status = {'success':True,'archive':folder.name,'verification':'archive structure only; full restore check separately'}
    except Exception as error:
        status = {'success':False,'error_type':type(error).__name__}
    status['finished_at'] = datetime.now(ZoneInfo('Africa/Lagos')).isoformat()
    temporary = destination / 'last-backup-status.pending'
    temporary.write_text(json.dumps(status,indent=2)+'\n',encoding='utf-8')
    temporary.replace(status_path)
    return status


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=backup.ROOT/'backups')
    status=run(parser.parse_args().output)
    print(json.dumps(status))
    raise SystemExit(0 if status['success'] else 1)
