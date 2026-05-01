"""Smoke tests for the pure (Tk-free) helpers in inventory_app.

Run with pytest:
    python -m pytest tests/

Or stand-alone:
    python tests/test_invento.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from inventory_app import (  # noqa: E402
    atomic_write,
    current_iso_week,
    fmt_money,
    fmt_num,
    format_iso_week,
    is_valid_number,
    next_iso_week,
    previous_iso_week,
    render_csv,
    render_report_lines,
    safe_float,
    write_pdf,
)


def test_safe_float_handles_garbage():
    assert safe_float("abc") == 0.0
    assert safe_float("") == 0.0
    assert safe_float("  ") == 0.0
    assert safe_float("3.14") == 3.14
    assert safe_float(None) == 0.0
    assert safe_float("-7") == -7.0


def test_is_valid_number():
    assert is_valid_number("")
    assert is_valid_number("0")
    assert is_valid_number("-3.14")
    assert not is_valid_number("abc")
    assert not is_valid_number("1.2.3")


def test_fmt_num_strips_trailing_zero():
    assert fmt_num(5.0) == "5"
    assert fmt_num(5.5) == "5.50"
    assert fmt_num(0) == "0"


def test_fmt_money():
    assert fmt_money(1234.5) == "$1,234.50"
    assert fmt_money(0) == "$0.00"


def test_iso_week_navigation_round_trip():
    w = current_iso_week()
    assert w == next_iso_week(previous_iso_week(w))
    assert previous_iso_week("2026-W17") == "2026-W16"
    assert next_iso_week("2026-W17") == "2026-W18"


def test_iso_week_handles_year_boundary():
    # ISO week 1 of some year should roll back to last week of previous year
    prev = previous_iso_week("2026-W01")
    assert prev.startswith("2025-W")


def test_format_iso_week_same_year_same_month():
    # ISO week 17 of 2026 = Mon Apr 20 – Sun Apr 26
    assert format_iso_week("2026-W17") == "Week 17 (Apr 20 \u2013 Apr 26, 2026)"


def test_format_iso_week_spans_months():
    # ISO week 18 of 2026 = Mon Apr 27 – Sun May 3
    assert format_iso_week("2026-W18") == "Week 18 (Apr 27 \u2013 May 3, 2026)"


def test_format_iso_week_spans_years():
    # ISO week 53 of 2026 = Mon Dec 28 2026 – Sun Jan 3 2027
    assert (
        format_iso_week("2026-W53")
        == "Week 53 (Dec 28, 2026 \u2013 Jan 3, 2027)"
    )


def test_format_iso_week_falls_back_for_garbage():
    assert format_iso_week("not-a-week") == "not-a-week"


def test_render_report_lines_includes_totals_and_revenue():
    rows = [
        {"item": "Widget", "price": "2", "last_week": "10",
         "days": ["1", "2", "3", "4", "5"]},
    ]
    lines = render_report_lines(rows, "2026-W17")
    assert any("TOTALS" in ln for ln in lines)
    assert any("Widget" in ln for ln in lines)
    # Revenue = sum(days)*price = 15*2 = 30
    assert any("Total Revenue:" in ln and "$30.00" in ln for ln in lines)
    assert any("Items:" in ln for ln in lines)


def test_render_csv_has_header_and_row():
    rows = [
        {"item": "A", "price": "1.5", "last_week": "10",
         "days": ["1", "2", "3", "4", "5"]},
    ]
    out = render_csv(rows, "2026-W17")
    # Week label is now the human-readable form. Embedded comma forces
    # CSV quoting around the value.
    assert '"Week 17 (Apr 20 \u2013 Apr 26, 2026)"' in out
    assert "Item,Unit Price" in out
    # remaining = 10 - 15 = -5; revenue = 15 * 1.5 = 22.5
    assert "A,1.5,10.0,1.0,2.0,3.0,4.0,5.0,15.0,22.5,-5.0" in out


def test_write_pdf_produces_valid_file():
    out = Path(tempfile.mkdtemp()) / "test.pdf"
    write_pdf(out, ["Hello (world)", "Second line", "Third \\ line"])
    data = out.read_bytes()
    assert data.startswith(b"%PDF-1.4")
    assert data.rstrip().endswith(b"%%EOF")
    assert b"/BaseFont /Courier" in data
    assert b"/Encoding /WinAnsiEncoding" in data


def test_write_pdf_paginates_long_input():
    lines = [f"line {i}" for i in range(200)]
    out = Path(tempfile.mkdtemp()) / "long.pdf"
    write_pdf(out, lines)
    data = out.read_bytes()
    # /Count N should be at least 2 for 200 lines at ~57 lines/page
    assert b"/Count 2" in data or b"/Count 3" in data or b"/Count 4" in data


def test_atomic_write_creates_backup_and_updates_content():
    d = Path(tempfile.mkdtemp())
    target = d / "data.json"
    target.write_text("{}", encoding="utf-8")
    atomic_write(target, '{"k":1}')
    assert (d / "data.json.bak").exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}


def test_atomic_write_no_backup_for_new_file():
    d = Path(tempfile.mkdtemp())
    target = d / "fresh.json"
    atomic_write(target, '{"k":2}')
    assert not (d / "fresh.json.bak").exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 2}


def _run_all() -> int:
    import types
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and isinstance(fn, types.FunctionType):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{failures} failure(s)")
    return failures


if __name__ == "__main__":
    sys.exit(_run_all())
