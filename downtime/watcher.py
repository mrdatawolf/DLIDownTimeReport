"""Persistent folder ingestion; stable files only, one bad PDF never stops a batch."""
import hashlib
import json
import time
from pathlib import Path
from downtime.ingest import connect, ingest

LEDGER = '''CREATE TABLE IF NOT EXISTS file_ingestion (
 path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
 mtime_ns INTEGER NOT NULL, status TEXT NOT NULL, document_id INTEGER,
 error TEXT, attempts INTEGER NOT NULL DEFAULT 1,
 checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);'''


def scan(db_path, folder, settle_seconds=10, retry_failed=False):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f'Report folder does not exist or is not a directory: {folder}')
    results = []
    db = connect(db_path)
    try:
        db.execute(LEDGER)
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.suffix.lower() != '.pdf':
                continue
            name = str(path.resolve())
            try:
                before = path.stat()
                if time.time() - before.st_mtime < settle_seconds:
                    continue
                previous = db.execute('SELECT * FROM file_ingestion WHERE path=?', (name,)).fetchone()
                if previous and previous['size'] == before.st_size and previous['mtime_ns'] == before.st_mtime_ns:
                    if previous['status'] != 'failed' or not retry_failed:
                        continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    continue
                # Avoid parsing unchanged failed content on every poll, even if renamed.
                failure = db.execute("SELECT error FROM file_ingestion WHERE sha256=? AND status='failed' LIMIT 1", (digest,)).fetchone()
                if failure and not retry_failed:
                    result = dict(status='failed', error=failure['error'])
                else:
                    try:
                        result = ingest(db, path)
                    except Exception as exc:
                        result = dict(status='failed', error=str(exc))
                # A write during extraction must be retried, not marked processed.
                final = path.stat()
                if (after.st_size, after.st_mtime_ns) != (final.st_size, final.st_mtime_ns):
                    continue
                with db:
                    db.execute('''INSERT INTO file_ingestion(path,sha256,size,mtime_ns,status,document_id,error)
                        VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                        sha256=excluded.sha256,size=excluded.size,mtime_ns=excluded.mtime_ns,
                        status=excluded.status,document_id=excluded.document_id,error=excluded.error,
                        attempts=file_ingestion.attempts+1,checked_at=CURRENT_TIMESTAMP''',
                        (name,digest,after.st_size,after.st_mtime_ns,result['status'],result.get('id'),result.get('error')))
                results.append(dict(path=name, **result))
            except OSError as exc:
                results.append(dict(path=name, status='unavailable', error=str(exc)))
    finally:
        db.close()
    return results


def watch(db_path, folder, interval, settle_seconds, stop):
    while not stop.wait(interval):
        try:
            for result in scan(db_path, folder, settle_seconds):
                print(json.dumps(result), flush=True)
        except Exception as exc:
            print(json.dumps(dict(status='scan_error', error=str(exc))), flush=True)
