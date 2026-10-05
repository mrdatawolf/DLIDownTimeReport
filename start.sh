#!/usr/bin/env bash
# Start from the project directory, even when invoked from elsewhere.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

version=$(tr -d '[:space:]' 2>/dev/null < VERSION.txt || true)
echo "Downtime Tracker version ${version:-unknown}"

python_command=''
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        python_command="$candidate"
        break
    fi
done
if [[ -z "$python_command" ]]; then
    echo 'Python 3.10 or newer is required. Install it and add it to PATH.' >&2
    exit 1
fi
if ! command -v pdftotext >/dev/null 2>&1; then
    echo 'pdftotext is required. Install Poppler (Ubuntu/Debian: sudo apt install poppler-utils).' >&2
    exit 1
fi

echo 'Starting Downtime Tracker...'
exec "$python_command" app.py "$@"
