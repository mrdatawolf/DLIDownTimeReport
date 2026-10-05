# Downtime Tracker

A local starting point for ingesting Porter Canter production and downtime PDF reports and comparing shift performance. Python 3.10+ and Poppler's `pdftotext` must be installed (on Ubuntu: `sudo apt install poppler-utils`). No Python packages are required.

## Run

On Linux or macOS, run `./start.sh`. On Windows, run `start.bat` (or `.\start.bat` in PowerShell). The Windows launcher prefers PowerShell 7 when installed, otherwise uses Windows PowerShell, verifies version 5.1 or newer, and runs `start.ps1`. You can also run `.\start.ps1` directly if your execution policy permits it. The batch launcher bypasses execution policy for its child process only.

Both launchers check for Python 3.10+ and Poppler's `pdftotext` on PATH, start from the project directory, use the existing `.env` settings, and forward command-line arguments. For example, `./start.sh --port 8090` or `start.bat --port 8090`. On Windows, install Python with its launcher or add Python to PATH, and add Poppler's `bin` or `Library\bin` directory containing `pdftotext.exe` to PATH. On macOS, Poppler can be installed with `brew install poppler`. Stop the server with Ctrl+C.

To launch directly with Python:

```bash
python3 app.py
```

Open http://127.0.0.1:8087 with the supplied `.env`. The three samples import into `data/downtime.sqlite3`. Subsequent imports of identical files are skipped. You can also upload PDFs in the dashboard. To import without starting the server:

```bash
python3 app.py --import-dir Samples --import-only
```

Configure `.env` before starting:

```dotenv
REPORTS_DIR=/absolute/path/to/reports
DB_PATH=data/downtime.sqlite3
HOST=127.0.0.1
PORT=8087
SCAN_INTERVAL_SECONDS=30
FILE_SETTLE_SECONDS=10
```

`REPORTS_DIR` is scanned recursively at startup and every configured interval while the server runs, including `.PDF` files. Paths are relative to the project directory unless absolute; quote paths containing spaces. The folder must already exist. Files must be old enough for the settling delay and remain unchanged during processing. For large archive transfers, copy to a temporary extension and rename to `.pdf` when complete.

Use `HOST=127.0.0.1` for this computer, `HOST=0.0.0.0` to listen on all IPv4 interfaces, or an actual address assigned to this server, such as `192.168.1.50`. When listening on `0.0.0.0`, open the server's actual IP address in the browser. Changing `.env` requires restarting the app. The current app has no authentication, so binding to a network interface makes its reports and upload endpoint available to anyone who can reach that port.

Process environment settings override `.env`; command-line arguments override both. Available overrides include `--env-file PATH`, `--db PATH`, `--host IP`, `--port NUMBER`, `--import-dir PATH`, `--scan-interval SECONDS`, and `--settle-seconds SECONDS`. Stop with Ctrl+C. `.env` is ignored by Git; `.env.example` provides a reusable template.

## Processing tracking

SQLite's `file_ingestion` table records each discovered file's absolute path, SHA-256 hash, size, modification time, status, associated document, attempts, error, and check time. Unchanged tracked files are skipped across restarts. Renamed or copied documents are detected by content hash and marked `duplicate`, without counting their data twice. Changed files are checked again. Failed PDFs remain `failed` and do not stop other imports or get reparsed every scan. The dashboard's Folder ingestion section shows these records and errors and refreshes every 30 seconds; `GET /api/ingestion` exposes the same information. Records for files removed from the folder remain as processing history.

After fixing a parser or dependency issue, retry unchanged failed files with:

```bash
python3 app.py --import-only --retry-failed
```

`--import-only` performs one scan and exits; it does not keep watching. All imports and processing state survive restarts in `DB_PATH`. Keep that database when moving or expanding the archive. A file's processing status is separate from whether its report data was imported: `imported` and `duplicate` both mean the data is already present; `failed` means review is needed.

## Reports and data

The dashboard includes date and shift filters, availability, production metrics, downtime causes ranked by minutes, source text, and downtime CSV export. Shift performance has Raw data and Trends tabs. Trends shows one graph at a time: select Downtime, Availability %, Logs, or BF, with separate lines for each shift. Graph style offers Shift points, Weekly averages, Monthly averages, and a Weekly heatmap. Aggregates average reported values per shift; availability is weighted by shift duration. Select bars or cells to inspect their contributing shifts. A downtime pie chart shows the eight largest causes plus Other causes, with minutes and percentages, using the global page filters. Filter by an inclusive date range, minimum/maximum downtime, minimum/maximum availability, minimum logs, and minimum board feet. The global Page filters under the header combine date, shift, date range, and metric selections and apply to totals, both performance tabs, downtime causes, source reports, and CSV export. Missing metrics are excluded when filtering that metric. Select a graph point to inspect the shift and open its source reports. Reset all filters clears every page filter, including date and shift. Missing production reports display a dash. Availability is uptime divided by total shift minutes, using precise downtime report totals. Only shifts with downtime reports contribute to the combined availability metric.

Shift identity comes from the source `.mdb` reference, including site, date, shift, and start time. The printed report date is retained separately. Both B reports were printed October 2 but describe the October 1 shift. Reports store SHA-256 hashes, original filenames, import timestamps, extracted source text, and structured data in SQLite. The production parser retains the extracted metric labels and values and exposes numeric values for the primary dashboard metrics.

Downtime records are aggregate cause rows, not individual timestamped events. Area/category context carries across page breaks. Row durations and shift totals must reconcile within 0.1 minutes to allow displayed rounding. Unknown formats and scanned PDFs without extractable text are rejected. A different document for an already imported shift and report type is rejected for review rather than replacing records automatically.

The initial samples cover one day: shift A has 269.98 downtime minutes; shift B has 52.45 minutes and 4,139 logs / 413,504 board feet. There is no shift A production summary, so daily production totals cannot be inferred.

This server defaults to localhost. Shared deployment will need authentication and an agreed storage/deployment setup. Input is limited to 20 MB per PDF. Source PDFs remain in `Samples`; uploads retain their extracted text in the database, not the original PDF binary. Back up the SQLite file to retain imports.

## Verify

```bash
python3 -m unittest discover -s tests -v
```

The tests exercise real sample PDFs, totals, production metrics, page continuation, filtering, duplicate imports, conflicting reports, invalid totals, persistent folder tracking, renamed PDFs, failed-file retries, file settling, and environment configuration.

Useful endpoints: `GET /api/reports`, `GET /api/export.csv` (both accept `date`, `shift`, `from`, `to`, `min_downtime`, `max_downtime`, `min_availability`, `max_availability`, `min_logs`, and `min_board_feet` filters), `GET /api/source/{id}`, and `POST /api/import?filename=report.pdf` with a raw PDF body.
