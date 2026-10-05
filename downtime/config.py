"""Small .env reader: process environment overrides file settings."""
import os
import shlex
from pathlib import Path


def load_env(path):
    values = {}
    if Path(path).exists():
        for number, line in enumerate(Path(path).read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, sep, value = line.partition('=')
            if not sep or not key.strip().isidentifier():
                raise ValueError(f'{path}:{number}: expected KEY=value')
            # Backslashes stay literal so Windows paths like C:\Reports\ work.
            lexer = shlex.shlex(value, posix=True)
            lexer.whitespace_split = True
            lexer.escape = ''
            values[key.strip()] = ' '.join(lexer)
    return {**values, **os.environ}


def resolve_path(root, value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path
