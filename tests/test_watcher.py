import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from downtime.config import load_env, resolve_path
from downtime.ingest import connect
from downtime.watcher import scan

SAMPLE = Path(__file__).resolve().parents[1] / 'Samples' / 'DLI DT 10-1-26A.pdf'
if not SAMPLE.exists():
    SAMPLE = SAMPLE.parent / 'DLI Reports' / SAMPLE.name

class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'reports'
        self.folder.mkdir()
        self.db = self.root / 'data.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_rename_and_skipped_subfolders(self):
        sub = self.folder / 'archive'
        sub.mkdir()
        shutil.copyfile(SAMPLE, sub / 'ignored.pdf')
        target = self.folder / 'report.PDF'
        shutil.copyfile(SAMPLE, target)
        self.assertEqual(scan(self.db, self.folder, 0)[0]['status'], 'imported')
        with patch('downtime.watcher.ingest', side_effect=AssertionError('Reparsed unchanged file')):
            self.assertEqual(scan(self.db, self.folder, 0), [])
        target.rename(self.folder / 'renamed.pdf')
        self.assertEqual(scan(self.db, self.folder, 0)[0]['status'], 'duplicate')
        db = connect(self.db)
        self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0], 1)
        db.close()

    def test_progress_and_heartbeat(self):
        (self.folder / 'empty').mkdir()
        (self.folder / 'notes.txt').write_text('not a report')
        shutil.copyfile(SAMPLE, self.folder / 'report.pdf')
        shown, beats = [], []
        results = scan(self.db, self.folder, 0, progress=shown.append, heartbeat=beats.append, beat_seconds=0)
        self.assertEqual(shown, results)
        self.assertEqual(results[0]['path'], str((self.folder / 'report.pdf').resolve()))
        self.assertEqual(beats, [0])

    def test_failure_continues_and_can_retry_or_change(self):
        bad = self.folder / 'a-bad.pdf'
        bad.write_bytes(b'broken')
        shutil.copyfile(SAMPLE, self.folder / 'b-good.pdf')
        results = scan(self.db, self.folder, 0)
        self.assertEqual([r['status'] for r in results], ['failed', 'imported'])
        self.assertEqual(scan(self.db, self.folder, 0), [])
        self.assertEqual(scan(self.db, self.folder, 0, retry_failed=True)[0]['status'], 'failed')
        shutil.copyfile(SAMPLE, bad)
        self.assertEqual(scan(self.db, self.folder, 0)[0]['status'], 'duplicate')

    def test_settling_and_missing_folder(self):
        target = self.folder / 'new.pdf'
        shutil.copyfile(SAMPLE, target)
        self.assertEqual(scan(self.db, self.folder, 60), [])
        os.utime(target, (time.time()-120, time.time()-120))
        self.assertEqual(scan(self.db, self.folder, 60)[0]['status'], 'imported')
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            scan(self.db, self.root / 'missing')

    def test_env_precedence_and_paths(self):
        env = self.root / '.env'
        env.write_text('REPORTS_DIR="folder with spaces"\nHOST=0.0.0.0 # comment\nPORT=8087\n')
        with patch.dict(os.environ, {'PORT':'9090'}, clear=True):
            settings = load_env(env)
        self.assertEqual(settings['PORT'], '9090')
        self.assertEqual(settings['HOST'], '0.0.0.0')
        self.assertEqual(resolve_path(self.root, settings['REPORTS_DIR']), self.root / 'folder with spaces')
        env.write_text('REPORTS_DIR=C:\\Reports\\Daily\\\nDB_PATH="C:\\My Data\\db.sqlite3"\n')
        with patch.dict(os.environ, {}, clear=True):
            settings = load_env(env)
        self.assertEqual(settings['REPORTS_DIR'], 'C:\\Reports\\Daily\\')
        self.assertEqual(settings['DB_PATH'], 'C:\\My Data\\db.sqlite3')
        env.write_text('invalid line')
        with self.assertRaises(ValueError):
            load_env(env)
