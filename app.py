#!/usr/bin/env python3
"""Local, dependency-free ingestion and reporting server."""
import argparse
import csv
import io
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
import tempfile
import ipaddress
import socket
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from downtime.ingest import connect, ingest
from downtime.reports import report
from downtime.config import load_env, resolve_path
from downtime.watcher import LEDGER, scan, watch

ROOT = Path(__file__).resolve().parent
ACCESS_LOG = ROOT / 'logs' / 'access.log'
access_log = logging.getLogger('downtime.access')

def server_urls(host, port):
    """Browser URLs for the bound address; 0.0.0.0 lists this computer's IPv4 addresses."""
    if host != '0.0.0.0':
        return [f'http://{host}:{port}']
    addresses = set()
    try:
        addresses.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    try:
        # Connecting a UDP socket sends nothing; it only selects the primary outbound address.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('192.0.2.1', 80))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    network = sorted((a for a in addresses if not a.startswith('127.')), key=ipaddress.ip_address)
    return [f'http://127.0.0.1:{port}'] + [f'http://{a}:{port}' for a in network]


class Handler(BaseHTTPRequestHandler):
    # Requests go to the access log file; errors also print to the terminal.
    def log_message(self, format, *args):
        access_log.info('%s - %s', self.address_string(), format % args)

    def log_error(self, format, *args):
        self.log_message(format, *args)
        print(f'{self.address_string()} - {format % args}', file=sys.stderr, flush=True)

    def send(self, body, content_type='application/json', status=200):
        if not isinstance(body, bytes):
            body = body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        with connect(self.server.db_path) as db:
            if url.path in ('/api/reports', '/api/export.csv'):
                try:
                    data = report(db, query.get('date', [''])[0], query.get('shift', [''])[0],
                                  {key: values[0] for key, values in query.items() if key in
                                   ('from', 'to', 'min_downtime', 'max_downtime', 'min_availability', 'max_availability', 'min_logs', 'min_board_feet')})
                except ValueError:
                    return self.send(json.dumps(dict(error='Invalid report filters.')), status=400)
                if url.path.endswith('.csv'):
                    stream = io.StringIO()
                    writer = csv.writer(stream)
                    writer.writerow(['site', 'date', 'shift', 'area', 'category', 'cause', 'occurrences', 'minutes'])
                    for s in data['shifts']:
                        for r in (s['downtime'] or {}).get('rows', []):
                            values = [s['site'], s['date'], s['shift'], r['area'], r['category'], r['cause'], r['occurrences'], r['minutes']]
                            writer.writerow(["'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for v in values])
                    self.send(stream.getvalue(), 'text/csv; charset=utf-8')
                else:
                    self.send(json.dumps(data))
            elif url.path == '/api/ingestion':
                db.execute(LEDGER)
                rows = [dict(r) for r in db.execute('SELECT * FROM file_ingestion ORDER BY checked_at DESC, path')]
                self.send(json.dumps(dict(folder=str(self.server.report_dir), files=rows)))
            elif url.path.startswith('/api/source/'):
                try:
                    row = db.execute('SELECT raw_text FROM documents WHERE id=?', (int(url.path.rsplit('/', 1)[1]),)).fetchone()
                except ValueError:
                    row = None
                self.send(row['raw_text'] if row else 'Source not found', 'text/plain; charset=utf-8', 200 if row else 404)
            elif url.path in ('/', '/app.js', '/style.css'):
                name = {'/':'index.html', '/app.js':'app.js', '/style.css':'style.css'}[url.path]
                mime = {'/':'text/html', '/app.js':'text/javascript', '/style.css':'text/css'}[url.path]
                self.send((ROOT / 'static' / name).read_bytes(), mime + '; charset=utf-8')
            else:
                self.send('Not found', 'text/plain', 404)

    def do_POST(self):
        if urlparse(self.path).path != '/api/import':
            return self.send('{}', status=404)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 20 * 1024 * 1024:
                raise ValueError('PDF must be between 1 byte and 20 MB.')
            body = self.rfile.read(size)
            if not body.startswith(b'%PDF-'):
                raise ValueError('Upload a PDF file.')
            filename = Path(parse_qs(urlparse(self.path).query).get('filename', ['upload.pdf'])[0]).name
            with tempfile.NamedTemporaryFile(suffix='.pdf') as file:
                file.write(body)
                file.flush()
                with connect(self.server.db_path) as db:
                    result = ingest(db, file.name, filename)
            self.send(json.dumps(result))
        except (ValueError, TimeoutError) as exc:
            self.send(json.dumps(dict(error=str(exc))), status=400)
        except Exception as exc:
            self.log_error('%s', exc)
            self.send(json.dumps(dict(error='Import failed; see server log.')), status=500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--db')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--import-dir', type=Path)
    parser.add_argument('--scan-interval', type=float)
    parser.add_argument('--settle-seconds', type=float)
    parser.add_argument('--import-only', action='store_true')
    parser.add_argument('--retry-failed', action='store_true', help='Retry unchanged failed files during the initial scan')
    args = parser.parse_args()
    try:
        settings = load_env(args.env_file)
        args.db = str(resolve_path(ROOT, args.db or settings.get('DB_PATH', 'data/downtime.sqlite3')))
        args.host = args.host or settings.get('HOST', '127.0.0.1')
        address = ipaddress.ip_address(args.host)
        if address.version != 4:
            raise ValueError('HOST must be a valid IPv4 address.')
        args.port = args.port if args.port is not None else int(settings.get('PORT', '8080'))
        interval = args.scan_interval if args.scan_interval is not None else float(settings.get('SCAN_INTERVAL_SECONDS', '30'))
        settle = args.settle_seconds if args.settle_seconds is not None else float(settings.get('FILE_SETTLE_SECONDS', '10'))
        if not 1 <= args.port <= 65535 or not 1 <= interval < float('inf') or not 0 <= settle < float('inf'):
            raise ValueError('PORT must be 1–65535; scan interval at least 1 second; settle seconds nonnegative and finite.')
        folder = resolve_path(ROOT, str(args.import_dir or settings.get('REPORTS_DIR', 'Samples')))
        if not folder.is_dir():
            raise ValueError(f'Report folder does not exist: {folder}')
    except ValueError as exc:
        parser.error(str(exc))
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    after = 'the app exits' if args.import_only else 'the server starts'
    print(f'Scanning {folder} for new or changed PDF reports. Large folders can take a while; '
          f'{after} when this finishes.', flush=True)
    started = time.monotonic()
    processed = 0

    def show(result):
        nonlocal processed
        processed += 1
        path = Path(result['path'])
        name = path.relative_to(folder.resolve()) if path.is_relative_to(folder.resolve()) else path
        error = f" - {result['error']}" if result.get('error') else ''
        print(f"  [{processed}] {result['status']:<11} {name}{error}", flush=True)

    def still_scanning(pdfs):
        print(f'  ...still scanning: {pdfs} PDFs checked so far', flush=True)

    results = scan(args.db, folder, settle, args.retry_failed, progress=show, heartbeat=still_scanning)
    counts = Counter(result['status'] for result in results)
    summary = ', '.join(f'{count} {status}' for status, count in sorted(counts.items())) or 'no new or changed files'
    print(f'Initial scan finished in {time.monotonic() - started:.1f}s: {summary}.', flush=True)
    if args.import_only:
        return 1 if any(r['status'] in ('failed', 'unavailable') for r in results) else 0
    ACCESS_LOG.parent.mkdir(exist_ok=True)
    log_file = RotatingFileHandler(ACCESS_LOG, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    log_file.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    access_log.addHandler(log_file)
    access_log.setLevel(logging.INFO)
    access_log.propagate = False
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.db_path = args.db
    server.report_dir = folder
    stop = threading.Event()
    worker = threading.Thread(target=watch, args=(args.db, folder, interval, settle, stop), daemon=True)
    worker.start()
    scope = ' (all IPv4 interfaces)' if args.host == '0.0.0.0' else ''
    urls = server_urls(args.host, args.port)
    print(f'\nDowntime Tracker is up, listening on {args.host}:{args.port}{scope}', flush=True)
    for label, url in zip(['Open:'] + [''] * len(urls), urls):
        print(f'  {label:<6}{url}', flush=True)
    print(f'  Watching {folder} every {interval:g}s', flush=True)
    print(f'  Request log: {ACCESS_LOG}', flush=True)
    print('  Press Ctrl+C to stop.\n', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join(timeout=35)
        server.server_close()
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
