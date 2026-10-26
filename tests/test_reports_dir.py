import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from downtime.reports_dir import FolderImports, available, diagnose, smb_share

MOUNTS = [('//fileserver/reports', '/mnt/reports', 'cifs'), ('//user@nas/archive', '/mnt/reports/archive', 'smb3'),
          ('/dev/sda1', '/', 'ext4')]

class ReportsDirTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_smb_share_detection(self):
        self.assertEqual(smb_share(r'\\fileserver\reports\DLI'), ('fileserver', 'reports'))
        self.assertEqual(smb_share('//fileserver/reports'), ('fileserver', 'reports'))
        self.assertEqual(smb_share('/run/user/1000/gvfs/smb-share:server=nas,share=dli/x'), ('nas', 'dli'))
        with patch('downtime.reports_dir.sys.platform', 'linux'), patch('downtime.reports_dir._mount_entries', return_value=MOUNTS):
            self.assertEqual(smb_share('/mnt/reports/DLI'), ('fileserver', 'reports'))
            self.assertEqual(smb_share('/mnt/reports/archive/2026'), ('nas', 'archive'))
            self.assertIsNone(smb_share('/mnt/reportsX'))
            self.assertIsNone(smb_share('/home/reports'))

    def test_diagnose_explains_share_state(self):
        self.assertIn('not on a recognized SMB share', diagnose(self.root / 'missing')[1])
        with patch('downtime.reports_dir.socket.gethostbyname', return_value='10.0.0.5'), \
             patch('downtime.reports_dir.ping', return_value=False), patch('downtime.reports_dir.port_open', return_value=False):
            lines = diagnose('//fileserver/reports')
        self.assertIn('Ping fileserver (10.0.0.5): no reply', lines)
        self.assertIn('unreachable', lines[-1])
        with patch('downtime.reports_dir.socket.gethostbyname', side_effect=OSError):
            self.assertIn('does not resolve', diagnose('//fileserver/reports')[-1])

    def test_recheck_pauses_and_resumes(self):
        folder = self.root / 'reports'
        imports = FolderImports(folder)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertFalse(imports.recheck())
            self.assertFalse(imports.recheck(diagnose_failure=False))
            self.assertEqual(output.getvalue().count('paused'), 1)
            self.assertFalse(imports.status()['enabled'])
            self.assertTrue(imports.status()['detail'])
            folder.mkdir()
            self.assertTrue(imports.recheck())
        self.assertIn('imports resumed', output.getvalue())
        self.assertEqual(imports.status()['detail'], [])

    def test_hung_folder_times_out(self):
        with patch('downtime.reports_dir.os.scandir', side_effect=lambda _: __import__('time').sleep(1)):
            self.assertFalse(available(self.root, timeout=0.05))
        self.assertTrue(available(self.root))
        (self.root / 'file').write_text('')
        self.assertFalse(available(self.root / 'file'))
