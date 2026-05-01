# Invento — Desktop Inventory Manager

A minimal black-and-white desktop app for tracking weekly inventory, sales, and revenue. Single-file Python + Tkinter, no third-party dependencies.

## Features

- **Black theme, white text** — easy-on-the-eyes dark UI.
- **Per-item columns**: Item · Unit Price · Last Week's Inventory · Mon–Fri sales · Total Sales · Revenue · Remaining.
- **Multi-week history** — navigate between ISO weeks (`◀ 2026-W17 ▶`) at the top. Each week is stored independently in the same JSON file.
- **Live calculations** — totals, revenue, and remaining stock recalculate on every keystroke.
- **Search / filter** rows by item name (also via `Ctrl+F`).
- **Reorder rows** with the ▲ ▼ buttons; delete with `✕` (confirmed).
- **Inline validation** — non-numeric input turns red instead of silently becoming `0`.
- **Unsaved-changes guard** — closing, loading, or switching weeks prompts you to save first; the title bar shows a `•` and the status bar shows `● Unsaved changes`.
- **Atomic save + backup** — writes go to `*.tmp` and are renamed in place, with a `.bak` rotation for the previous version.
- **Window state remembered** — geometry and last-opened file are persisted to `~/.invento/settings.json`.
- **Exports**: TXT (aligned plain text), CSV (Excel-friendly), and PDF (built using only the Python standard library; no `reportlab` required).
- **Backwards compatible** — loads old single-week JSON files written by Invento v1.

## Requirements

- **Python ≥ 3.10** (Tkinter ships with the standard installer on Windows and macOS).
- No third-party packages required to run the app.
- Optional: `pytest` to run the test suite, `pyinstaller` to build a `.exe`.

## Running

From this folder:

```powershell
python inventory_app.py
```

On first launch, three empty rows are created. Start typing.

## Keyboard shortcuts

| Shortcut       | Action                       |
| -------------- | ---------------------------- |
| `Ctrl+S`       | Save                         |
| `Ctrl+Shift+S` | Save As…                     |
| `Ctrl+O`       | Load                         |
| `Ctrl+N`       | New row                      |
| `Ctrl+F`       | Focus the search box         |
| `Tab`          | Move to the next entry cell  |
| `Mouse wheel`  | Scroll the table             |

## Data file

Default save location: `inventory_data.json` next to `inventory_app.py`. The file format is:

```json
{
  "version": 2,
  "current_week": "2026-W17",
  "weeks": {
    "2026-W17": [
      {"item": "Widget", "price": "2.50",
       "last_week": "10", "days": ["1", "2", "3", "4", "5"]}
    ]
  }
}
```

A `.bak` of the previous save is kept alongside it.

## Exports

From the **Menu ▾**:

- **Export as TXT…** — aligned monospace report (good for printing or email).
- **Export as CSV…** — opens cleanly in Excel / Google Sheets.
- **Export as PDF…** — single-page (or auto-paginated) report using built-in Courier with `WinAnsiEncoding` (so Latin-1 characters such as `é`, `£`, `°` render correctly; characters outside cp1252 are replaced with `?`).

## Tests

```powershell
python -m pytest tests/
```

Or without pytest:

```powershell
python tests\test_invento.py
```

The tests cover the pure helpers (validation, formatting, ISO-week math, CSV/TXT/PDF rendering, atomic write).

## Building a Windows `.exe`

```powershell
python -m pip install pyinstaller
pyinstaller --onefile --noconsole --name Invento inventory_app.py
```

The standalone executable lands in `dist\Invento.exe`. Pair with a custom icon via `--icon path\to\icon.ico`.

## Project layout

```
App/
├── inventory_app.py       # the whole app (UI + pure helpers)
├── inventory_data.json    # default save file (created on first save)
├── README.md
├── requirements.txt
└── tests/
    └── test_invento.py
```

The codebase is intentionally a single file for easy distribution. The pure helpers (`safe_float`, `is_valid_number`, `fmt_num`, `fmt_money`, `current_iso_week`, `previous_iso_week`, `next_iso_week`, `render_report_lines`, `render_csv`, `write_pdf`, `atomic_write`) live at the top of `inventory_app.py` and have no Tk dependency, so they're trivial to import and test in isolation.

Future work: split into a `invento/` package (`app.py`, `row.py`, `theme.py`, `io/`) once the file grows past ~1000 lines.
