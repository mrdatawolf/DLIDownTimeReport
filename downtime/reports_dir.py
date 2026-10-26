"""REPORTS_DIR availability: explain an unreachable SMB share and pause folder imports until it returns."""
import os
import re
import socket
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import PureWindowsPath

SMB_FILESYSTEMS = {'cifs', 'smb3', 'smbfs'}
UNC = re.compile(r'^[\\/]{2}(?:[^@\\/]*@)?([^\\/]+)[\\/]+([^\\/]+)')


def available(folder, timeout=10):
    """True if folder can be listed; a hung network mount counts as unavailable after timeout seconds."""
    result = []

    def probe():
        try:
            with os.scandir(folder):
                result.append(True)
        except OSError:
            result.append(False)

    # A dead hard-mounted share can block forever, so probe in a disposable thread.
    thread = threading.Thread(target=probe, daemon=True)
    thread.start()
    thread.join(timeout)
    return result == [True]


def _mount_entries():
    """(source, mount point, filesystem) for mounted and fstab-listed filesystems on Linux/macOS."""
    entries = []
    unescape = lambda value: re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), value)
    for table in ('/proc/mounts', '/etc/fstab'):
        try:
            with open(table) as file:
                for line in file:
                    fields = line.split()
                    if len(fields) >= 3 and not fields[0].startswith('#'):
                        entries.append((unescape(fields[0]), unescape(fields[1]), fields[2]))
        except OSError:
            continue
    if sys.platform == 'darwin':
        try:
            output = subprocess.run(['mount'], capture_output=True, text=True, timeout=5).stdout
            entries += re.findall(r'^(\S+) on (.+) \((\w+)', output, re.M)
        except (OSError, subprocess.TimeoutExpired):
            pass
    return entries


def _mapped_drive(path):
    """UNC target of a mapped Windows drive letter, including disconnected persistent mappings."""
    drive = PureWindowsPath(path).drive
    if len(drive) != 2:
        return None
    import ctypes
    buffer = ctypes.create_unicode_buffer(1024)
    size = ctypes.c_ulong(len(buffer))
    # 1201 is ERROR_CONNECTION_UNAVAIL: a remembered mapping that is not connected right now.
    if ctypes.windll.mpr.WNetGetConnectionW(drive, buffer, ctypes.byref(size)) not in (0, 1201):
        return None
    return buffer.value


def smb_share(folder):
    """(host, share) when folder is on an SMB share, otherwise None."""
    path = str(folder)
    gvfs = re.search(r'/gvfs/smb-share:server=([^,/]+),share=([^,/]+)', path)
    if gvfs:
        return gvfs[1], gvfs[2]
    source = path
    if not UNC.match(path):
        if sys.platform == 'win32':
            source = _mapped_drive(path) or ''
        else:
            mounts = [(src, point) for src, point, fs in _mount_entries() if fs in SMB_FILESYSTEMS
                      and (path == point or path.startswith(point.rstrip('/') + '/'))]
            source = max(mounts, key=lambda m: len(m[1]))[0] if mounts else ''
    match = UNC.match(source)
    return (match[1], match[2]) if match else None


def ping(host):
    """True/False for a ping reply, None when the ping command is missing."""
    options = {'win32': ['-n', '1', '-w', '2000'], 'darwin': ['-c', '1', '-t', '2']}.get(sys.platform, ['-c', '1', '-W', '2'])
    try:
        return subprocess.run(['ping', *options, host], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=5).returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except OSError:
        return None


def port_open(address, port=445, timeout=3):
    try:
        with socket.create_connection((address, port), timeout):
            return True
    except OSError:
        return False


def diagnose(folder):
    """Terminal/dashboard lines explaining why folder is unavailable."""
    lines = [f'Reports folder is not available: {folder}']
    share = smb_share(folder)
    if not share:
        lines.append('It is not on a recognized SMB share. Check that the path exists and this account can read it.')
        return lines
    host, name = share
    lines.append(f'It is on SMB share //{host}/{name}.')
    try:
        address = socket.gethostbyname(host)
    except OSError:
        lines.append(f"{host} does not resolve. Check the server name and this computer's network or VPN connection.")
        return lines
    replied, smb = ping(host), port_open(address)
    lines.append(f'Ping {host} ({address}): ' + {True: 'replied', False: 'no reply', None: 'ping command not found'}[replied])
    lines.append('SMB port 445: ' + ('open' if smb else 'not reachable'))
    if smb:
        lines.append('The server is up, so the share is likely disconnected or unmounted, renamed, '
                     'or this account lacks permission. Reconnect or remount the share.')
    elif replied:
        lines.append('The server is up but not accepting SMB connections. Check its file sharing service and firewall.')
    else:
        lines.append('The server is unreachable. Check that it is powered on and that this computer is on its network or VPN.')
    return lines


class FolderImports:
    """Folder imports are enabled only while the reports folder is reachable; recheck() turns them back on."""

    def __init__(self, folder):
        self.folder = folder
        self.enabled = None
        self.detail = []
        self.checked_at = None
        self._lock = threading.Lock()

    def recheck(self, diagnose_failure=True):
        """Return whether imports are enabled; diagnose_failure refreshes the share and ping details."""
        with self._lock:
            ok = available(self.folder)
            if ok:
                if self.enabled is False:
                    print(f'Reports folder is reachable again; folder imports resumed: {self.folder}', flush=True)
                self.detail = []
            else:
                if diagnose_failure or not self.detail:
                    self.detail = diagnose(self.folder)
                if self.enabled is not False:
                    print('\n'.join(['', *self.detail[:1], *('  ' + line for line in self.detail[1:]),
                                     'Folder imports are paused until it is reachable again.', '']), flush=True)
            self.enabled = ok
            self.checked_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            return ok

    def status(self):
        return dict(enabled=bool(self.enabled), detail=self.detail, checked_at=self.checked_at)
