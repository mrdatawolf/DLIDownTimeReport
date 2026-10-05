import tempfile
import unittest
from pathlib import Path
from downtime.ingest import connect, ingest, parse
from downtime.reports import report

SAMPLES = Path(__file__).resolve().parents[1] / 'Samples'
if not (SAMPLES / 'DLI 10-1-26B.pdf').exists():
    SAMPLES = SAMPLES / 'DLI Reports'

class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = connect(Path(self.temp.name) / 'test.sqlite3')
        for path in [SAMPLES / name for name in ('DLI 10-1-26B.pdf', 'DLI DT 10-1-26A.pdf', 'DLI DT 10-1-26B.pdf')]:
            ingest(self.db, path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_sample_totals_and_dates(self):
        data = report(self.db)
        self.assertEqual(data['dates'], ['2026-10-01'])
        self.assertEqual(len(data['shifts']), 2)
        a, b = data['shifts']
        self.assertEqual(a['downtime']['downtime_minutes'], 269.98)
        self.assertEqual(b['downtime']['downtime_minutes'], 52.45)
        self.assertIsNone(a['production'])
        self.assertEqual(b['production']['numeric']['Total Logs'], 4139)
        self.assertEqual(b['production']['numeric']['Total Brd Footage'], 413504)
        self.assertEqual(b['production']['numeric']['Total Board Value'], 201286.90)
        self.assertAlmostEqual(data['totals']['downtime_minutes'], 322.43)
        self.assertAlmostEqual(data['totals']['availability_percent'], 70.14537037)

    def test_page_continuation_and_filter(self):
        data = report(self.db, '2026-10-01', 'B')
        landing = [r for r in data['causes'] if r['cause']=='LANDING TABLE' and r['area']=='DLI Sort']
        self.assertEqual(landing[0]['minutes'], 3.32)
        self.assertEqual(len(data['shifts']), 1)
        self.assertEqual(len(data['shifts'][0]['downtime']['rows']), 17)

    def test_page_filters_share_shifts_totals_causes_and_sources(self):
        expected = report(self.db, shift='B')
        for filters in ({'max_downtime': '100'}, {'min_logs': '4000'},
                        {'min_board_feet': '400000'}, {'min_availability': '80'}):
            with self.subTest(filters=filters):
                data = report(self.db, filters=filters)
                self.assertEqual(data['shifts'], expected['shifts'])
                self.assertEqual(data['totals'], expected['totals'])
                self.assertEqual(data['causes'], expected['causes'])
                self.assertEqual(data['match_total'], 2)
        empty = report(self.db, filters={'from': '2026-10-02'})
        self.assertEqual(empty['shifts'], [])
        self.assertEqual(empty['causes'], [])
        self.assertEqual(empty['totals']['downtime_minutes'], 0)
        self.assertIsNone(empty['totals']['availability_percent'])
        self.assertEqual(len(report(self.db, filters={'from': '2026-10-01', 'to': '2026-10-01'})['shifts']), 2)
        self.assertEqual(len(report(self.db)['shifts']), 2)

    def test_duplicates_and_conflicts(self):
        path = SAMPLES / 'DLI DT 10-1-26A.pdf'
        self.assertEqual(ingest(self.db, path)['status'], 'duplicate')
        altered = Path(self.temp.name) / 'altered.pdf'
        altered.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            ingest(self.db, altered)
        self.assertEqual(len(report(self.db)['documents']), 3)

    def test_bad_totals_are_rejected(self):
        raw = self.db.execute("SELECT raw_text FROM documents WHERE kind='downtime' AND shift='A'").fetchone()[0]
        with self.assertRaisesRegex(ValueError, 'reconcile'):
            parse(raw.replace('269.98', '999.98'))
        with self.assertRaises(ValueError):
            parse('Unsupported document')

if __name__ == '__main__':
    unittest.main()
