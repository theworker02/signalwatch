"""Operator CLI for offline system diagnostics and controlled source polling."""
import argparse
import asyncio
import json
import sqlite3
import hashlib
from datetime import datetime, timezone
import os
import sys
from pathlib import Path


def local_diagnostics():
    from .app import DATA, DB, INBOX, POLL_ENABLED, CALLISTO_AUTO, FEEDS
    sources=DB.get_sources()
    return {'data_directory':str(DATA), 'local_inbox':str(INBOX),
            'database_exists':Path(DB.path).is_file(),
            'background_monitor_enabled':POLL_ENABLED,
            'callisto_auto_enabled':CALLISTO_AUTO,
            'configured_public_feeds':len(FEEDS)+(1 if CALLISTO_AUTO else 0),
            'source_health':[{k:v for k,v in s.items() if k in
                ('name','status','last_success','last_error')} for s in sources],
            'note':'Local diagnostics do not establish a working external telescope feed.'}


def main():
    ap=argparse.ArgumentParser(prog='python -m signalwatch.cli',
        description='Operate the local Magnexis SIGNALWATCH observatory')
    command=ap.add_subparsers(dest='command',required=True)
    command.add_parser('doctor',help='check local configuration, without contacting external services')
    command.add_parser('scan',help='scan a local inbox once')
    command.add_parser('poll',help='poll eligible public sources once, respecting backoff')
    alerts=command.add_parser('alerts',help='show current flagged unreviewed events')
    alerts.add_argument('--min-score',type=int,default=60)
    backup=command.add_parser('backup',help='create a consistent SQLite evidence backup')
    backup.add_argument('--output',help='destination SQLite path (must not exist)')
    args=ap.parse_args()
    if args.command=='doctor':result=local_diagnostics()
    elif args.command=='scan':
        from .app import scan_radio_once
        result=asyncio.run(scan_radio_once())
    elif args.command=='poll':
        from .app import poll_once
        result=asyncio.run(poll_once())
    elif args.command=='backup':
        from .app import DB, DATA
        path=Path(args.output).expanduser().resolve() if args.output else (
            DATA/'backups'/f"signalwatch-{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}.sqlite3")
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():ap.error('destination exists; select a new filename (will not overwrite)')
        with sqlite3.connect(DB.path) as src, sqlite3.connect(path) as dst:
            src.backup(dst)
            integrity=dst.execute('PRAGMA integrity_check').fetchone()[0]
        if integrity!='ok':
            path.unlink(missing_ok=True)
            raise RuntimeError('SQLite backup failed integrity check')
        result={'path':str(path),'bytes':path.stat().st_size,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'sqlite_integrity':'ok'}
    else:
        from .app import DB
        if not 0<=args.min_score<=100:ap.error('--min-score must be between 0 and 100')
        result=DB.alerts(min_score=args.min_score)
    print(json.dumps(result,indent=2,ensure_ascii=False,default=str))
    return 0


if __name__=='__main__':sys.exit(main())
