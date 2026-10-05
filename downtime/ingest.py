"""Parse Porter Canter PDF reports, preserving source text and shift identity."""
import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, filename TEXT NOT NULL,
 kind TEXT NOT NULL, shift_date TEXT NOT NULL, shift TEXT NOT NULL,
 start_time TEXT NOT NULL, site TEXT NOT NULL, report_date TEXT NOT NULL,
 payload TEXT NOT NULL, raw_text TEXT NOT NULL,
 imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(kind, site, shift_date, shift, start_time)
);
'''

def connect(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def parse(text):
    identity = re.search(r'Canter\s+\w+\s+(\d{2}-[A-Za-z]{3}-\d{2})\s+(\d{4})\.mdb', text)
    shift = re.search(r'SHIFT\s+([A-Z])\b', text)
    printed = re.search(r'[A-Za-z]+-\d{2}-\d{4}', text)
    site = re.search(r'^\s*(.+? - CANTER)\s*$', text, re.M)
    if not all((identity, shift, printed, site)):
        raise ValueError('Missing Canter shift identity, site, or report date.')
    result = dict(shift_date=datetime.strptime(identity[1], '%d-%b-%y').date().isoformat(),
                  shift=shift[1], start_time=identity[2], site=site[1].strip(),
                  report_date=datetime.strptime(printed[0], '%B-%d-%Y').date().isoformat())
    if text.lstrip().startswith('Downtime Summary'):
        result['kind'] = 'downtime'
        rows, area, category = [], None, None
        for line in text.replace('\f', '\n').splitlines():
            if line.strip().startswith('Area:'):
                area = line.split(':', 1)[1].strip()
                category = None
            elif line.strip().startswith('Category:'):
                category = line.split(':', 1)[1].strip()
            else:
                match = re.match(r'^\s*(\S.*?)\s{2,}(\d+)\s+([\d.]+)\s+([\d.]+)%\s+([\d.]+)%\s*$', line)
                if match:
                    if area is None or category is None:
                        raise ValueError('Downtime row lacks area/category.')
                    rows.append(dict(area=area, category=category, cause=match[1], occurrences=int(match[2]),
                                     minutes=float(match[3]), downtime_percent=float(match[4]), shift_percent=float(match[5])))
        totals = {}
        for key, label in [('downtime_minutes', 'Downtime'), ('uptime_minutes', 'UpTime'), ('shift_minutes', 'Shift Time')]:
            match = re.search(r'Total\s+' + label + r':\s+[\d.]+\s+hrs\s*=\s*([\d.]+)\s+mins', text, re.I)
            if not match:
                raise ValueError('Missing ' + label + ' total.')
            totals[key] = float(match[1])
        if not rows or abs(sum(r['minutes'] for r in rows) - totals['downtime_minutes']) > 0.1:
            raise ValueError('Downtime rows do not reconcile with the report total.')
        if abs(totals['uptime_minutes'] + totals['downtime_minutes'] - totals['shift_minutes']) > 0.1:
            raise ValueError('Shift totals do not reconcile.')
        result['payload'] = dict(rows=rows, **totals)
    elif text.lstrip().startswith('Summary'):
        result['kind'] = 'production'
        metrics = {}
        # Layout extraction separates the report's left and right columns.
        for line in text.splitlines():
            for match in re.finditer(r'([A-Za-z][A-Za-z0-9/.*"-]*(?: [A-Za-z0-9/.*"-]+)*)\s{2,}(\$?[\d,]+(?:\.\d+)?[^\n]*?)(?=\s{5,}[A-Za-z]|$)', line):
                label, value = match[1].strip(), match[2].strip()
                metrics[label] = value
        required = ['Total Logs', 'Total Brd Footage', 'Total Board Value', 'Total Log Volume', 'Actual Brd Vol Recovery']
        numeric = {}
        for label in required:
            if label not in metrics:
                raise ValueError('Missing production metric: ' + label)
            numeric[label] = float(re.match(r'\$?([\d,.]+)', metrics[label])[1].replace(',', ''))
        result['payload'] = dict(metrics=metrics, numeric=numeric)
    else:
        raise ValueError('Unsupported report type.')
    return result


def ingest(db, path, filename=None):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = db.execute('SELECT id FROM documents WHERE sha256=?', (digest,)).fetchone()
    if existing:
        return dict(status='duplicate', id=existing['id'], filename=filename or path.name)
    proc = subprocess.run(['pdftotext', '-layout', str(path), '-'], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise ValueError('PDF text extraction failed. Supply a text-based PDF.')
    report = parse(proc.stdout)
    try:
        with db:
            cursor = db.execute('INSERT INTO documents(sha256,filename,kind,shift_date,shift,start_time,site,report_date,payload,raw_text) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (digest, filename or path.name, report['kind'], report['shift_date'], report['shift'], report['start_time'], report['site'], report['report_date'], json.dumps(report['payload']), proc.stdout))
    except sqlite3.IntegrityError as exc:
        raise ValueError('A different report already exists for this site, shift, and report type; replacement requires review.') from exc
    return dict(status='imported', id=cursor.lastrowid, filename=filename or path.name)
