"""Invento — a lightweight desktop inventory manager.

Single-file Tkinter app. Tracks per-item inventory, daily sales, and
revenue across multiple ISO weeks. Saves to JSON with atomic writes
and automatic backup. Exports to TXT, CSV, and PDF (no third-party
dependencies).
"""

from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple


BG = "#000000"
FG = "#FFFFFF"
ACCENT = "#1E1E1E"
BORDER = "#2A2A2A"
HOVER = "#2C2C2C"
ERROR_FG = "#FF6B6B"
WARN_FG = "#FFB454"
INFO_FG = "#5DA9FF"
MUTED = "#888888"

FONT_REGULAR = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 14, "bold")

APP_DIR = Path(__file__).resolve().parent
DEFAULT_SAVE_FILE = APP_DIR / "inventory_data.json"
SETTINGS_FILE = Path.home() / ".invento" / "settings.json"
LOGO_FILE = APP_DIR / "assets" / "logo.png"
SPLASH_BG = "#138A7E"  # teal that matches the logo background
SPLASH_DURATION_MS = 3000

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]

# Default headings for the 12 columns of the inventory grid. Indices are
# fixed so they map cleanly onto each row's widgets list:
#   0:Product ID  1:Unit Price  2:Last Week
#   3..7:Mon..Fri  8:Total Sales  9:Revenue  10:Remaining  11:Actions
DEFAULT_COLUMN_TITLES: List[str] = [
    "Product ID", "Unit Price", "Last Week",
    "Mon", "Tue", "Wed", "Thu", "Fri",
    "Total Sales", "Revenue", "Remaining", "Actions",
]
DEFAULT_COLUMN_WEIGHTS: List[int] = [3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]


# ---------------------------------------------------------------------------
# Pure helpers (no Tk dependency — easy to unit test)
# ---------------------------------------------------------------------------


def safe_float(val) -> float:
    try:
        return float(str(val).strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def is_valid_number(val: str) -> bool:
    s = (val or "").strip()
    if not s:
        return True
    try:
        float(s)
        return True
    except ValueError:
        return False


def fmt_num(n: float) -> str:
    return str(int(n)) if n == int(n) else f"{n:.2f}"


def fmt_money(n: float) -> str:
    return f"${n:,.2f}"


def current_iso_week() -> str:
    y, w, _ = _dt.date.today().isocalendar()
    return f"{y}-W{w:02d}"


def _parse_iso_week(week: str) -> Tuple[int, int]:
    y_str, w_str = week.split("-W")
    return int(y_str), int(w_str)


def previous_iso_week(week: str) -> str:
    y, w = _parse_iso_week(week)
    monday = _dt.date.fromisocalendar(y, w, 1) - _dt.timedelta(days=7)
    py, pw, _ = monday.isocalendar()
    return f"{py}-W{pw:02d}"


def next_iso_week(week: str) -> str:
    y, w = _parse_iso_week(week)
    monday = _dt.date.fromisocalendar(y, w, 1) + _dt.timedelta(days=7)
    ny, nw, _ = monday.isocalendar()
    return f"{ny}-W{nw:02d}"


def format_iso_week(week: str) -> str:
    """Render an ISO week id as a human-readable label.

    'YYYY-WNN' -> 'Week NN (Mon D – Mon D, YYYY)'
    Falls back to the raw input if it can't be parsed.
    """
    try:
        y, w = _parse_iso_week(week)
        start = _dt.date.fromisocalendar(y, w, 1)
        end = start + _dt.timedelta(days=6)
    except (ValueError, AttributeError):
        return week

    def md(d: _dt.date) -> str:
        return f"{d.strftime('%b')} {d.day}"

    if start.year == end.year:
        return f"Week {w} ({md(start)} \u2013 {md(end)}, {start.year})"
    return (
        f"Week {w} ({md(start)}, {start.year} \u2013 "
        f"{md(end)}, {end.year})"
    )


def render_report_lines(rows_data: List[dict], week: str) -> List[str]:
    """Aligned monospace report shared by the TXT and PDF exporters."""
    widths = [22, 8, 9, 5, 5, 5, 5, 5, 9, 10, 9]
    headers = [
        "Item", "Price", "LastWeek",
        "Mon", "Tue", "Wed", "Thu", "Fri",
        "Total", "Revenue", "Remain",
    ]

    def fmt_row(cells: List) -> str:
        parts = []
        for i, c in enumerate(cells):
            w = widths[i]
            s = ("" if c is None else str(c))[:w]
            parts.append(s.ljust(w) if i == 0 else s.rjust(w))
        return " ".join(parts)

    sep = "-" * (sum(widths) + len(widths) - 1)
    timestamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: List[str] = []
    lines.append("Invento - Inventory Report")
    lines.append(f"Week: {format_iso_week(week)}")
    lines.append(f"Generated: {timestamp}")
    lines.append("")
    lines.append(fmt_row(headers))
    lines.append(sep)

    grand_units = 0.0
    grand_revenue = 0.0
    day_totals = [0.0] * len(WEEKDAYS)
    for r in rows_data:
        price = safe_float(r.get("price", 0))
        last_week = safe_float(r.get("last_week", 0))
        days = [safe_float(x) for x in r.get("days", [])][: len(WEEKDAYS)]
        days += [0.0] * (len(WEEKDAYS) - len(days))
        for i, v in enumerate(days):
            day_totals[i] += v
        total = sum(days)
        revenue = total * price
        remaining = last_week - total
        grand_units += total
        grand_revenue += revenue
        lines.append(fmt_row([
            r.get("item", ""),
            fmt_num(price),
            fmt_num(last_week),
            *[fmt_num(v) for v in days],
            fmt_num(total),
            f"{revenue:.2f}",
            fmt_num(remaining),
        ]))

    lines.append(sep)
    lines.append(fmt_row([
        "TOTALS", "", "",
        *[fmt_num(t) for t in day_totals],
        fmt_num(grand_units),
        f"{grand_revenue:.2f}",
        "",
    ]))
    lines.append("")
    lines.append(f"Total Units Sold: {fmt_num(grand_units)}")
    lines.append(f"Total Revenue:    {fmt_money(grand_revenue)}")
    lines.append(f"Items:            {len(rows_data)}")
    return lines


def render_csv(rows_data: List[dict], week: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Week", format_iso_week(week)])
    w.writerow([])
    w.writerow([
        "Item", "Unit Price", "Last Week's Inventory",
        *WEEKDAYS, "Total Sales", "Revenue", "Remaining",
    ])
    for r in rows_data:
        price = safe_float(r.get("price", 0))
        last_week = safe_float(r.get("last_week", 0))
        days = [safe_float(x) for x in r.get("days", [])][: len(WEEKDAYS)]
        days += [0.0] * (len(WEEKDAYS) - len(days))
        total = sum(days)
        w.writerow([
            r.get("item", ""),
            price, last_week,
            *days,
            total,
            total * price,
            last_week - total,
        ])
    return buf.getvalue()


def write_pdf(path, lines: List[str]) -> None:
    """Minimal PDF 1.4 writer using built-in Courier + WinAnsiEncoding."""
    page_w, page_h = 612, 792
    margin_x, margin_top, margin_bottom = 40, 60, 50
    font_size = 9
    line_height = 12
    usable_h = page_h - margin_top - margin_bottom
    lines_per_page = max(1, int(usable_h // line_height))

    pages = [
        lines[i:i + lines_per_page] for i in range(0, len(lines), lines_per_page)
    ] or [[""]]

    def escape(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def to_winansi(s: str) -> bytes:
        return s.encode("cp1252", "replace")

    content_streams: List[bytes] = []
    for page_lines in pages:
        parts: List[bytes] = [
            b"BT",
            f"/F1 {font_size} Tf".encode("ascii"),
            f"{line_height} TL".encode("ascii"),
            f"{margin_x} {page_h - margin_top} Td".encode("ascii"),
        ]
        for idx, ln in enumerate(page_lines):
            if idx > 0:
                parts.append(b"T*")
            parts.append(b"(" + to_winansi(escape(ln)) + b") Tj")
        parts.append(b"ET")
        content_streams.append(b"\n".join(parts))

    n_pages = len(pages)
    page_obj_start = 4
    content_obj_start = page_obj_start + n_pages
    kids = " ".join(f"{page_obj_start + i} 0 R" for i in range(n_pages))

    objs: List[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {n_pages} /Kids [{kids}] >>".encode("ascii"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
        b"/Encoding /WinAnsiEncoding >>",
    ]
    for i in range(n_pages):
        objs.append((
            f"<< /Type /Page /Parent 2 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/MediaBox [0 0 {page_w} {page_h}] "
            f"/Contents {content_obj_start + i} 0 R >>"
        ).encode("ascii"))
    for cs in content_streams:
        objs.append(
            f"<< /Length {len(cs)} >>\nstream\n".encode("ascii")
            + cs
            + b"\nendstream"
        )

    out = bytearray()
    out += b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets: List[int] = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii")
        out += obj
        out += b"\nendobj\n"

    xref_offset = len(out)
    n_objs = len(objs) + 1
    out += f"xref\n0 {n_objs}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {n_objs} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")

    Path(path).write_bytes(bytes(out))


def atomic_write(path: Path, content: str, *, backup: bool = True) -> None:
    """Write text atomically: tmp -> os.replace, with optional .bak rotation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError:
            pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Settings (window geometry, last opened path)
# ---------------------------------------------------------------------------


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(data: dict) -> None:
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# UI: one row in the inventory grid
# ---------------------------------------------------------------------------


class InventoryRow:
    """One row in the inventory grid (widgets + values)."""

    def __init__(
        self,
        parent: tk.Widget,
        row_index: int,
        on_change: Callable[[], None],
        on_delete: Callable[["InventoryRow"], None],
        on_move: Callable[["InventoryRow", int], None],
    ):
        self.parent = parent
        self.row_index = row_index
        self.on_change = on_change
        self.on_delete = on_delete
        self.on_move = on_move

        self.item_var = tk.StringVar()
        self.price_var = tk.StringVar(value="0")
        self.last_week_var = tk.StringVar(value="0")
        self.day_vars: List[tk.StringVar] = [
            tk.StringVar(value="0") for _ in WEEKDAYS
        ]
        self.total_var = tk.StringVar(value="0")
        self.revenue_var = tk.StringVar(value="$0.00")
        self.remaining_var = tk.StringVar(value="0")

        self.widgets: List[tk.Widget] = []
        self.entries: List[tk.Entry] = []
        self._visible = True
        self._build()

    def _build(self) -> None:
        col = 0
        item_entry = self._make_entry(self.item_var, anchor="w")
        self._place(item_entry, col); col += 1

        price_entry = self._make_entry(self.price_var, anchor="e", numeric=True)
        self._place(price_entry, col); col += 1

        last_entry = self._make_entry(self.last_week_var, anchor="e", numeric=True)
        self._place(last_entry, col); col += 1

        for var in self.day_vars:
            day_entry = self._make_entry(var, anchor="e", numeric=True)
            self._place(day_entry, col); col += 1

        for var in (self.total_var, self.revenue_var, self.remaining_var):
            lbl = tk.Label(
                self.parent, textvariable=var, bg=ACCENT, fg=FG,
                font=FONT_BOLD, anchor="e", padx=6, pady=6,
                relief="flat", borderwidth=0,
            )
            lbl.grid(row=self.row_index, column=col, sticky="nsew", padx=1, pady=1)
            self.widgets.append(lbl)
            col += 1

        actions = tk.Frame(self.parent, bg=BG)
        actions.grid(row=self.row_index, column=col, sticky="nsew", padx=1, pady=1)
        self.widgets.append(actions)

        for txt, cmd in [
            ("\u25B2", lambda: self.on_move(self, -1)),
            ("\u25BC", lambda: self.on_move(self, +1)),
            ("\u2715", lambda: self.on_delete(self)),
        ]:
            b = tk.Button(
                actions, text=txt, bg=BG, fg=FG,
                activebackground=HOVER, activeforeground=FG,
                relief="flat", borderwidth=0, font=FONT_BOLD,
                cursor="hand2", width=2, command=cmd,
            )
            b.pack(side="left", expand=True, fill="x")

        for var in (self.price_var, self.last_week_var, *self.day_vars):
            var.trace_add("write", lambda *_: self._recalculate())
        # Item name changes don't affect totals, but should still mark dirty.
        self.item_var.trace_add("write", lambda *_: self.on_change())

    def _place(self, entry: tk.Entry, col: int) -> None:
        entry.grid(row=self.row_index, column=col, sticky="nsew", padx=1, pady=1)
        self.widgets.append(entry)
        self.entries.append(entry)

    def _make_entry(
        self, var: tk.StringVar, anchor: str = "center", numeric: bool = False
    ) -> tk.Entry:
        justify_map = {"w": "left", "e": "right", "center": "center"}
        entry = tk.Entry(
            self.parent, textvariable=var,
            bg=BG, fg=FG, insertbackground=FG,
            relief="flat", borderwidth=0,
            justify=justify_map.get(anchor, "left"),
            font=FONT_REGULAR,
        )
        entry.bind("<FocusIn>", lambda _e: entry.configure(bg=ACCENT))
        entry.bind("<FocusOut>", lambda _e: entry.configure(bg=BG))
        if numeric:
            def _validate(*_):
                entry.configure(fg=FG if is_valid_number(var.get()) else ERROR_FG)
            var.trace_add("write", _validate)
        return entry

    def _recalculate(self) -> None:
        days = [safe_float(v.get()) for v in self.day_vars]
        total = sum(days)
        price = safe_float(self.price_var.get())
        last_week = safe_float(self.last_week_var.get())
        self.total_var.set(fmt_num(total))
        self.revenue_var.set(fmt_money(total * price))
        self.remaining_var.set(fmt_num(last_week - total))
        self.on_change()

    def to_dict(self) -> dict:
        return {
            "item": self.item_var.get(),
            "price": self.price_var.get(),
            "last_week": self.last_week_var.get(),
            "days": [v.get() for v in self.day_vars],
        }

    def from_dict(self, data: dict) -> None:
        self.item_var.set(data.get("item", ""))
        self.price_var.set(data.get("price", "0"))
        self.last_week_var.set(data.get("last_week", "0"))
        days = data.get("days", [])
        for i, var in enumerate(self.day_vars):
            var.set(days[i] if i < len(days) else "0")
        self._recalculate()

    def matches(self, query: str) -> bool:
        if not query:
            return True
        return query.lower() in self.item_var.get().lower()

    def set_visible(self, visible: bool) -> None:
        if visible == self._visible:
            return
        self._visible = visible
        for w in self.widgets:
            try:
                if visible:
                    w.grid()
                else:
                    w.grid_remove()
            except tk.TclError:
                pass

    def destroy(self) -> None:
        for w in self.widgets:
            w.destroy()
        self.widgets.clear()
        self.entries.clear()


# ---------------------------------------------------------------------------
# Themed modal dialogs (replace tkinter.messagebox to keep the dark theme)
# ---------------------------------------------------------------------------


class ThemedDialog(tk.Toplevel):
    """Frameless modal dialog styled to match the Invento dark theme."""

    KIND_GLYPHS: Dict[str, Tuple[str, str]] = {
        "info":     ("\u24D8", INFO_FG),   # ⓘ
        "warning":  ("\u26A0", WARN_FG),   # ⚠
        "error":    ("\u2715", ERROR_FG),  # ✕
        "question": ("?",      INFO_FG),
    }

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        message: str,
        *,
        kind: str = "info",
        buttons: Tuple[Tuple[str, Any], ...] = (("OK", True),),
        default_index: int = 0,
        cancel_value: Any = None,
    ):
        super().__init__(parent)
        self.result: Any = cancel_value
        self._cancel_value = cancel_value

        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=BORDER)
        try:
            self.transient(parent.winfo_toplevel())
        except tk.TclError:
            pass

        outer = tk.Frame(self, bg=BORDER)
        outer.pack(fill="both", expand=True, padx=1, pady=1)

        titlebar = tk.Frame(outer, bg=ACCENT, height=32)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)
        tk.Label(
            titlebar, text=title, bg=ACCENT, fg=FG, font=FONT_BOLD,
            padx=14, anchor="w",
        ).pack(side="left", fill="y")
        close_btn = tk.Button(
            titlebar, text="\u2715", bg=ACCENT, fg=MUTED,
            activebackground=HOVER, activeforeground=FG,
            relief="flat", borderwidth=0, font=FONT_BOLD,
            padx=12, cursor="hand2",
            command=self._cancel,
        )
        close_btn.pack(side="right", fill="y")

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)

        glyph, glyph_color = self.KIND_GLYPHS.get(kind, self.KIND_GLYPHS["info"])
        tk.Label(
            body, text=glyph, bg=BG, fg=glyph_color,
            font=("Segoe UI", 22, "bold"),
            padx=18, pady=18,
        ).pack(side="left", anchor="n")
        tk.Label(
            body, text=message, bg=BG, fg=FG, font=FONT_REGULAR,
            justify="left", anchor="w", wraplength=380,
            padx=4, pady=22,
        ).pack(side="left", fill="both", expand=True, padx=(0, 18))

        btn_bar = tk.Frame(outer, bg=BG)
        btn_bar.pack(fill="x", side="bottom")
        sep = tk.Frame(btn_bar, bg=BORDER, height=1)
        sep.pack(fill="x", side="top")

        btn_inner = tk.Frame(btn_bar, bg=BG)
        btn_inner.pack(side="right", padx=14, pady=12)

        button_widgets: List[tk.Button] = []
        for i, (label, value) in enumerate(buttons):
            is_default = (i == default_index)
            b = tk.Button(
                btn_inner, text=label,
                bg="#FFFFFF" if is_default else ACCENT,
                fg="#000000" if is_default else FG,
                activebackground="#DDDDDD" if is_default else HOVER,
                activeforeground="#000000" if is_default else FG,
                relief="flat", borderwidth=0, font=FONT_BOLD,
                padx=18, pady=6, cursor="hand2",
                command=lambda v=value: self._finish(v),
            )
            b.pack(side="left", padx=(8, 0))
            button_widgets.append(b)

        self.bind("<Escape>", lambda _e: self._cancel())
        if button_widgets:
            default_btn = button_widgets[default_index]
            self.bind("<Return>", lambda _e: default_btn.invoke())

        self.update_idletasks()
        w = max(self.winfo_reqwidth(), 360)
        h = self.winfo_reqheight()
        try:
            top = parent.winfo_toplevel()
            px, py = top.winfo_rootx(), top.winfo_rooty()
            pw, ph = top.winfo_width(), top.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 3
        except tk.TclError:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

        self.deiconify()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        if button_widgets:
            button_widgets[default_index].focus_set()
        self.wait_window()

    def _finish(self, value: Any) -> None:
        self.result = value
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def _cancel(self) -> None:
        self._finish(self._cancel_value)


def themed_info(parent: tk.Misc, title: str, message: str) -> None:
    ThemedDialog(parent, title, message, kind="info")


def themed_warning(parent: tk.Misc, title: str, message: str) -> None:
    ThemedDialog(parent, title, message, kind="warning")


def themed_error(parent: tk.Misc, title: str, message: str) -> None:
    ThemedDialog(parent, title, message, kind="error")


def themed_yesno(parent: tk.Misc, title: str, message: str) -> bool:
    d = ThemedDialog(
        parent, title, message, kind="question",
        buttons=(("Yes", True), ("No", False)),
        default_index=0,
        cancel_value=False,
    )
    return bool(d.result)


def themed_yesnocancel(
    parent: tk.Misc, title: str, message: str,
) -> Optional[bool]:
    d = ThemedDialog(
        parent, title, message, kind="question",
        buttons=(("Yes", True), ("No", False), ("Cancel", None)),
        default_index=0,
        cancel_value=None,
    )
    return d.result


def themed_prompt(
    parent: tk.Misc,
    title: str,
    message: str,
    initial: str = "",
) -> Optional[str]:
    """Modal text-input dialog styled to match the rest of the app.

    Returns the entered string, or None if the user cancelled (Esc, the
    Cancel button, or the title-bar close button).
    """
    dlg = tk.Toplevel(parent)
    dlg.withdraw()
    dlg.overrideredirect(True)
    dlg.configure(bg=BORDER)
    try:
        dlg.transient(parent.winfo_toplevel())
    except tk.TclError:
        pass

    var = tk.StringVar(value=initial)
    state = {"result": None}  # type: Dict[str, Optional[str]]

    outer = tk.Frame(dlg, bg=BORDER)
    outer.pack(fill="both", expand=True, padx=1, pady=1)

    titlebar = tk.Frame(outer, bg=ACCENT, height=32)
    titlebar.pack(fill="x", side="top")
    titlebar.pack_propagate(False)
    tk.Label(
        titlebar, text=title, bg=ACCENT, fg=FG, font=FONT_BOLD,
        padx=14, anchor="w",
    ).pack(side="left", fill="y")

    def _cancel() -> None:
        state["result"] = None
        try:
            dlg.grab_release()
        except tk.TclError:
            pass
        dlg.destroy()

    def _accept() -> None:
        state["result"] = var.get()
        try:
            dlg.grab_release()
        except tk.TclError:
            pass
        dlg.destroy()

    tk.Button(
        titlebar, text="\u2715", bg=ACCENT, fg=MUTED,
        activebackground=HOVER, activeforeground=FG,
        relief="flat", borderwidth=0, font=FONT_BOLD,
        padx=12, cursor="hand2", command=_cancel,
    ).pack(side="right", fill="y")

    body = tk.Frame(outer, bg=BG)
    body.pack(fill="both", expand=True)

    tk.Label(
        body, text=message, bg=BG, fg=FG, font=FONT_REGULAR,
        justify="left", anchor="w", wraplength=380, padx=18,
    ).pack(fill="x", pady=(20, 8))

    entry = tk.Entry(
        body, textvariable=var, bg=ACCENT, fg=FG,
        insertbackground=FG, relief="flat", borderwidth=0,
        font=FONT_REGULAR,
    )
    entry.pack(fill="x", padx=18, pady=(0, 16), ipady=6)

    btn_bar = tk.Frame(outer, bg=BG)
    btn_bar.pack(fill="x", side="bottom")
    sep = tk.Frame(btn_bar, bg=BORDER, height=1)
    sep.pack(fill="x", side="top")
    btn_inner = tk.Frame(btn_bar, bg=BG)
    btn_inner.pack(side="right", padx=14, pady=12)

    ok_btn = tk.Button(
        btn_inner, text="OK", bg="#FFFFFF", fg="#000000",
        activebackground="#DDDDDD", activeforeground="#000000",
        relief="flat", borderwidth=0, font=FONT_BOLD,
        padx=18, pady=6, cursor="hand2", command=_accept,
    )
    cancel_btn = tk.Button(
        btn_inner, text="Cancel", bg=ACCENT, fg=FG,
        activebackground=HOVER, activeforeground=FG,
        relief="flat", borderwidth=0, font=FONT_BOLD,
        padx=18, pady=6, cursor="hand2", command=_cancel,
    )
    ok_btn.pack(side="left", padx=(8, 0))
    cancel_btn.pack(side="left", padx=(8, 0))

    dlg.bind("<Escape>", lambda _e: _cancel())
    dlg.bind("<Return>", lambda _e: _accept())

    dlg.update_idletasks()
    w = max(dlg.winfo_reqwidth(), 380)
    h = dlg.winfo_reqheight()
    try:
        top = parent.winfo_toplevel()
        px, py = top.winfo_rootx(), top.winfo_rooty()
        pw, ph = top.winfo_width(), top.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 3
    except tk.TclError:
        x = (dlg.winfo_screenwidth() - w) // 2
        y = (dlg.winfo_screenheight() - h) // 3
    dlg.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

    dlg.deiconify()
    dlg.lift()
    # An `overrideredirect` Toplevel doesn't automatically become the
    # foreground window on Windows. Without `focus_force` the dialog is
    # visible and grab_set redirects mouse events, but keystrokes still
    # go to whatever window had OS focus before, so the user can't type
    # into the Entry. Forcing focus here fixes that.
    try:
        dlg.attributes("-topmost", True)
    except tk.TclError:
        pass
    try:
        dlg.grab_set()
    except tk.TclError:
        pass
    dlg.focus_force()
    entry.focus_set()
    entry.select_range(0, "end")
    entry.icursor("end")
    dlg.wait_window()
    return state["result"]


# ---------------------------------------------------------------------------
# RoundedButton — Canvas-based pill / rounded-rect button (Tk has no native one)
# ---------------------------------------------------------------------------


class RoundedButton(tk.Canvas):
    """A flat, rounded button with hover and press states.

    Composed of four corner ovals plus two filling rectangles so the edges
    stay crisp at any size (no smooth-polygon bulging).
    """

    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], None],
        *,
        width: int = 220,
        height: int = 42,
        radius: Optional[int] = None,
        bg: str = BG,
        fill: str = "#FFFFFF",
        hover_fill: str = "#EAEAEA",
        active_fill: str = "#CFCFCF",
        text_color: str = "#000000",
        font: Tuple = FONT_BOLD,
    ):
        super().__init__(
            parent, width=width, height=height,
            bg=bg, highlightthickness=0, borderwidth=0,
        )
        self._command = command
        self._fill = fill
        self._hover_fill = hover_fill
        self._active_fill = active_fill
        # NB: avoid `self._w` / `self._h` — `_w` is Tkinter's reserved
        # widget pathname attribute; overwriting it breaks every Tk call
        # the canvas makes (e.g. create_oval -> "invalid command name").
        self._cw = width
        self._ch = height
        self._radius = min(radius if radius is not None else height // 2,
                           min(width, height) // 2)
        self._pressed = False

        self._draw(fill)
        self.create_text(
            width // 2, height // 2,
            text=text, fill=text_color, font=font,
        )

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.configure(cursor="hand2")

    def _draw(self, color: str) -> None:
        r = self._radius
        w, h = self._cw, self._ch
        opts = dict(fill=color, outline="", tags="shape")
        # Four corner arcs (drawn as ovals; the rectangles cover the
        # inner halves so only the outer quarters are visible).
        self.create_oval(0, 0, 2 * r, 2 * r, **opts)
        self.create_oval(w - 2 * r, 0, w, 2 * r, **opts)
        self.create_oval(0, h - 2 * r, 2 * r, h, **opts)
        self.create_oval(w - 2 * r, h - 2 * r, w, h, **opts)
        # Two rectangles forming a plus sign that fills the body.
        self.create_rectangle(r, 0, w - r, h, **opts)
        self.create_rectangle(0, r, w, h - r, **opts)

    def _set_fill(self, color: str) -> None:
        self.itemconfig("shape", fill=color)

    def _on_enter(self, _e) -> None:
        self._set_fill(self._active_fill if self._pressed else self._hover_fill)

    def _on_leave(self, _e) -> None:
        if not self._pressed:
            self._set_fill(self._fill)

    def _on_press(self, _e) -> None:
        self._pressed = True
        self._set_fill(self._active_fill)

    def _on_release(self, e) -> None:
        was_pressed = self._pressed
        self._pressed = False
        over = 0 <= e.x < self._cw and 0 <= e.y < self._ch
        self._set_fill(self._hover_fill if over else self._fill)
        if was_pressed and over:
            self._command()


def make_dark_rounded(
    parent: tk.Widget,
    text: str,
    command: Callable[[], None],
    *,
    width: int,
    height: int,
    radius: Optional[int] = None,
    font: Tuple = FONT_BOLD,
) -> RoundedButton:
    """Convenience wrapper for a dark, theme-coloured RoundedButton."""
    return RoundedButton(
        parent, text=text, command=command,
        width=width, height=height, radius=radius,
        bg=BG, fill=ACCENT, hover_fill=HOVER,
        active_fill=BORDER, text_color=FG, font=font,
    )


# ---------------------------------------------------------------------------
# Native title bar theming (Windows DWM)
# ---------------------------------------------------------------------------


def apply_dark_titlebar(window: tk.Misc) -> None:
    """Make the OS title bar dark on Windows 10/11. No-op elsewhere.

    Uses the DWM `DwmSetWindowAttribute` API. Tries the modern attribute
    id (20, Windows 10 20H1+) first and falls back to the older one (19).
    Silently does nothing on macOS / Linux or if DWM is unavailable.
    """
    try:
        import ctypes
    except ImportError:
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            return
        for attr in (20, 19):
            value = ctypes.c_int(1)
            res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value),
            )
            if res == 0:
                return
    except (OSError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class InventoryApp:
    COLUMN_COUNT = 12

    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()

        self.root.title("Invento")
        self.root.configure(bg=BG)
        self.root.geometry(self.settings.get("geometry", "1280x680"))
        self.root.minsize(1000, 520)

        self.rows: List[InventoryRow] = []
        self.weeks: Dict[str, List[dict]] = {}
        self.current_week: str = current_iso_week()
        self.current_path: Path = Path(
            self.settings.get("last_path", str(DEFAULT_SAVE_FILE))
        )

        self._dirty = False
        self._suppress_dirty = False
        self._menu_open = False
        self._search_var = tk.StringVar()
        self.menu_popup: Optional[tk.Toplevel] = None
        self.submenu_popup: Optional[tk.Toplevel] = None
        self.column_menu_popup: Optional[tk.Toplevel] = None
        self.week_var = tk.StringVar(value=format_iso_week(self.current_week))

        # Column customisation (right-click on a header to Rename or
        # Delete). Persisted across runs in settings.json.
        saved_titles = self.settings.get("column_titles")
        if (isinstance(saved_titles, list)
                and len(saved_titles) == len(DEFAULT_COLUMN_TITLES)):
            self.column_titles: List[str] = [str(t) for t in saved_titles]
        else:
            self.column_titles = list(DEFAULT_COLUMN_TITLES)
        saved_hidden = self.settings.get("hidden_columns") or []
        self.hidden_columns: set = {
            int(i) for i in saved_hidden
            if isinstance(i, int) and 0 <= i < InventoryApp.COLUMN_COUNT
        }
        # Filled in by _build_table -> _build_header.
        self._header_frame: Optional[tk.Frame] = None
        self._header_labels: List[tk.Label] = []

        self._build_topbar()
        self._build_table()
        self._build_statusbar()

        self._load_from_disk(self.current_path, silent=True)
        if not self.weeks:
            self.weeks[self.current_week] = []
            self._suppress_dirty = True
            for _ in range(3):
                self.add_row()
            self._on_any_change()
            self._suppress_dirty = False
            self._mark_dirty(False)

        self._search_var.trace_add("write", lambda *_: self._apply_filter())
        self._install_shortcuts()
        self.root.bind("<Button-1>", self._maybe_close_menu, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_title()

    # ----- Top bar -----

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, bg=BG, height=56)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        # Menu sits on the far left now that the brand text lives in the
        # OS title bar. Pack it first so side="left" puts it at the edge,
        # then the right-aligned controls (search, week nav) pack after.
        self.menu_btn = make_dark_rounded(
            bar, text="Menu  \u25BE",
            command=self._toggle_menu,
            width=120, height=36, radius=18,
        )
        self.menu_btn.pack(side="left", padx=18, pady=10)

        nav = tk.Frame(bar, bg=BG)
        nav.pack(side="right", padx=10)
        make_dark_rounded(
            nav, text="\u25C0",
            command=lambda: self._switch_week(previous_iso_week(self.current_week)),
            width=32, height=32, radius=16,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=(0, 4))
        tk.Label(
            nav, textvariable=self.week_var, bg=BG, fg=FG,
            font=FONT_BOLD, padx=10, width=34, anchor="center",
        ).pack(side="left")
        make_dark_rounded(
            nav, text="\u25B6",
            command=lambda: self._switch_week(next_iso_week(self.current_week)),
            width=32, height=32, radius=16,
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=(4, 0))

        search_frame = tk.Frame(bar, bg=BG)
        search_frame.pack(side="right", padx=10)
        tk.Label(
            search_frame, text="Search:", bg=BG, fg=MUTED, font=FONT_REGULAR,
        ).pack(side="left")
        self.search_entry = tk.Entry(
            search_frame, textvariable=self._search_var, bg=ACCENT, fg=FG,
            insertbackground=FG, relief="flat", borderwidth=0,
            font=FONT_REGULAR, width=18,
        )
        self.search_entry.pack(side="left", padx=(6, 0), ipady=3)

        sep = tk.Frame(self.root, bg=BORDER, height=1)
        sep.pack(fill="x", side="top")

    # ----- Menu popup -----

    def _toggle_menu(self) -> None:
        if self._menu_open:
            self._close_menu()
        else:
            self._open_menu()

    def _open_menu(self) -> None:
        items: List[Tuple[str, Optional[Callable[[], None]], bool]] = [
            ("New Item   (Ctrl+N)", self.add_row, False),
            ("Save   (Ctrl+S)", self.save_to_disk, False),
            ("Save As…   (Ctrl+Shift+S)", self.save_as, False),
            ("Load   (Ctrl+O)", self.load_from_file, False),
            ("Export As", None, True),
            ("Clear All", self.clear_all, False),
        ]
        if self.hidden_columns:
            items.append(
                ("Restore Columns", self._restore_columns, False)
            )
        items.extend([
            ("About", self.show_about, False),
            ("Exit", self._on_close, False),
        ])

        item_h = 34
        height = len(items) * item_h + 2
        width = max(self.menu_btn.winfo_width(), 240)
        # Menu button now lives on the left edge of the top bar, so the
        # popup is left-aligned to the button. If that would run off the
        # right edge of the screen we shift it back into view.
        x = self.menu_btn.winfo_rootx()
        screen_w = self.root.winfo_screenwidth()
        if x + width > screen_w:
            x = max(0, screen_w - width - 4)
        y = self.menu_btn.winfo_rooty() + self.menu_btn.winfo_height() + 4

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.configure(bg=BORDER)
        popup.geometry(f"{width}x{height}+{x}+{y}")

        inner = tk.Frame(popup, bg=ACCENT)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        for label, cmd, has_submenu in items:
            if has_submenu:
                btn = self._menu_item(
                    inner, label, lambda: None, submenu=True,
                )
                btn.configure(
                    command=lambda b=btn: self._toggle_export_submenu(b)
                )
            else:
                self._menu_item(inner, label, cmd or (lambda: None))

        self.menu_popup = popup
        self._menu_open = True

    def _menu_item(
        self,
        parent: tk.Widget,
        label: str,
        command: Callable[[], None],
        *,
        submenu: bool = False,
    ) -> tk.Button:
        if submenu:
            text = f"{label}\u2003\u25B8"
            cb = command
        else:
            text = label
            cb = lambda: (self._close_menu(), command())
        btn = tk.Button(
            parent, text=text, bg=ACCENT, fg=FG,
            activebackground=HOVER, activeforeground=FG,
            relief="flat", borderwidth=0, anchor="w",
            padx=14, pady=8, font=FONT_REGULAR, cursor="hand2",
            command=cb,
        )
        btn.pack(fill="x")
        return btn

    def _toggle_export_submenu(self, parent_btn: tk.Button) -> None:
        if self.submenu_popup is not None:
            self._close_submenu()
            return
        self._open_export_submenu(parent_btn)

    def _open_export_submenu(self, parent_btn: tk.Button) -> None:
        if self.menu_popup is None:
            return

        items = [
            ("Text File (.txt)", self.export_as_txt),
            ("CSV Spreadsheet (.csv)", self.export_as_csv),
            ("PDF Document (.pdf)", self.export_as_pdf),
        ]
        item_h = 34
        height = len(items) * item_h + 2
        width = 220

        # Menu now opens at the left edge of the top bar, so the export
        # submenu prefers to cascade out to the right of the main menu.
        # Fall back to the left side if there isn't room on the right.
        menu_x = self.menu_popup.winfo_rootx()
        menu_w = self.menu_popup.winfo_width()
        screen_w = self.root.winfo_screenwidth()
        x = menu_x + menu_w + 4
        if x + width > screen_w:
            x = max(0, menu_x - width - 4)
        y = parent_btn.winfo_rooty()

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.configure(bg=BORDER)
        popup.geometry(f"{width}x{height}+{x}+{y}")

        inner = tk.Frame(popup, bg=ACCENT)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        for label, cmd in items:
            self._menu_item(inner, label, cmd)

        self.submenu_popup = popup

    def _close_submenu(self) -> None:
        if self.submenu_popup is not None:
            self.submenu_popup.destroy()
            self.submenu_popup = None

    def _close_menu(self) -> None:
        self._close_submenu()
        if self.menu_popup is not None:
            self.menu_popup.destroy()
            self.menu_popup = None
        self._menu_open = False

    def _maybe_close_menu(self, event) -> None:
        # Dismiss the column right-click popup on any click outside it.
        if self.column_menu_popup is not None:
            try:
                if not str(event.widget).startswith(
                    str(self.column_menu_popup)
                ):
                    self._close_column_menu()
            except tk.TclError:
                self._close_column_menu()

        if not self._menu_open or self.menu_popup is None:
            return
        w = event.widget
        if w is self.menu_btn:
            return
        try:
            popup_path = str(self.menu_popup)
            if str(w).startswith(popup_path):
                return
            if (
                self.submenu_popup is not None
                and str(w).startswith(str(self.submenu_popup))
            ):
                return
        except tk.TclError:
            pass
        self._close_menu()

    # ----- Table -----

    def _build_table(self) -> None:
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=18, pady=(14, 8))

        # Footer is packed first with side="bottom" so it stays pinned at
        # the bottom of the table area regardless of how the row list
        # scrolls. Putting it in `container` (not the scrollable canvas)
        # is what makes it sticky.
        footer = tk.Frame(container, bg=BG)
        footer.pack(side="bottom", fill="x", pady=(12, 2))

        self.add_row_btn = RoundedButton(
            footer, text="+  Add New Item",
            command=self.add_row,
            width=210, height=40,
        )
        self.add_row_btn.pack(side="left")

        self.canvas = tk.Canvas(
            container, bg=BG, highlightthickness=0, borderwidth=0
        )
        self.vsb = ttk.Scrollbar(
            container, orient="vertical", command=self.canvas.yview,
        )

        def _autohide_yscroll(first: str, last: str) -> None:
            # Tk passes the visible fraction as strings. When the entire
            # content is visible (0.0 .. 1.0) there's nothing to scroll,
            # so the scrollbar is taken out of the layout. The canvas
            # then expands into the freed horizontal space.
            try:
                f, l = float(first), float(last)
            except ValueError:
                f, l = 0.0, 1.0
            if f <= 0.0 and l >= 1.0:
                if self.vsb.winfo_ismapped():
                    self.vsb.pack_forget()
            else:
                if not self.vsb.winfo_ismapped():
                    self.vsb.pack(side="right", fill="y")
            self.vsb.set(first, last)

        self.canvas.configure(yscrollcommand=_autohide_yscroll)

        self.canvas.pack(side="left", fill="both", expand=True)
        # vsb is packed lazily by `_autohide_yscroll` only when needed.

        self.table_frame = tk.Frame(self.canvas, bg=BG)
        self.table_window = self.canvas.create_window(
            (0, 0), window=self.table_frame, anchor="nw"
        )

        self.canvas.bind(
            "<Enter>",
            lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel),
        )
        self.canvas.bind(
            "<Leave>",
            lambda _e: self.canvas.unbind_all("<MouseWheel>"),
        )
        self.table_frame.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfig(self.table_window, width=e.width),
        )

        self._build_header()
        self.rows_frame = tk.Frame(self.table_frame, bg=BORDER)
        self.rows_frame.pack(fill="both", expand=True)
        self._configure_columns(self.rows_frame)

    def _on_mousewheel(self, e) -> None:
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _configure_columns(self, frame: tk.Widget) -> None:
        # Product ID gets more weight than the numeric / action columns.
        # Hidden columns get weight=0 + uniform="" so they collapse fully.
        for col, w in enumerate(DEFAULT_COLUMN_WEIGHTS):
            if col in self.hidden_columns:
                frame.grid_columnconfigure(
                    col, weight=0, minsize=0, uniform="",
                )
            else:
                frame.grid_columnconfigure(
                    col, weight=w, uniform="col",
                )

    def _build_header(self) -> None:
        header = tk.Frame(self.table_frame, bg=BORDER)
        header.pack(fill="x")
        self._header_frame = header
        self._header_labels = []
        self._configure_columns(header)

        for col, title in enumerate(self.column_titles):
            # First column (Product ID) is left-anchored with a bit more
            # padding; the action column uses MUTED to de-emphasise it.
            is_first = (col == 0)
            is_actions = (col == InventoryApp.COLUMN_COUNT - 1)
            lbl = tk.Label(
                header,
                text=title,
                bg=ACCENT,
                fg=MUTED if is_actions else FG,
                font=FONT_BOLD,
                padx=10 if is_first else 6,
                pady=10,
                anchor="w" if is_first else "center",
                cursor="hand2",
            )
            lbl.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
            # Right-click opens the per-column action menu.
            lbl.bind(
                "<Button-3>",
                lambda e, c=col: self._show_column_menu(c, e),
            )
            self._header_labels.append(lbl)

        # If columns were hidden via persisted settings, apply that now.
        if self.hidden_columns:
            self._apply_column_visibility()

    # ----- Column right-click menu -----

    def _show_column_menu(self, col: int, event) -> None:
        """Open the Rename / Delete popup at the cursor."""
        self._close_column_menu()

        items: List[Tuple[str, Callable[[], None]]] = [
            ("Rename\u2026", lambda: self._rename_column(col)),
            ("Delete (Hide)", lambda: self._delete_column(col)),
        ]
        if self.hidden_columns:
            items.append(
                ("Restore All Columns", self._restore_columns)
            )

        item_h = 32
        width = 200
        height = len(items) * item_h + 2

        # Anchor at the cursor; clamp to the screen so menus opened near
        # the right or bottom edge stay fully visible.
        x = event.x_root
        y = event.y_root
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if x + width > screen_w:
            x = screen_w - width - 4
        if y + height > screen_h:
            y = screen_h - height - 4

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.configure(bg=BORDER)
        popup.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

        inner = tk.Frame(popup, bg=ACCENT)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        for label, cmd in items:
            btn = tk.Button(
                inner, text=label, bg=ACCENT, fg=FG,
                activebackground=HOVER, activeforeground=FG,
                relief="flat", borderwidth=0, anchor="w",
                padx=14, pady=6, font=FONT_REGULAR, cursor="hand2",
                command=lambda c=cmd: (self._close_column_menu(), c()),
            )
            btn.pack(fill="x")

        self.column_menu_popup = popup

    def _close_column_menu(self) -> None:
        if self.column_menu_popup is not None:
            try:
                self.column_menu_popup.destroy()
            except tk.TclError:
                pass
            self.column_menu_popup = None

    def _rename_column(self, col: int) -> None:
        if not (0 <= col < len(self.column_titles)):
            return
        new_name = themed_prompt(
            self.root,
            "Rename Column",
            f"Rename '{self.column_titles[col]}' to:",
            initial=self.column_titles[col],
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name == self.column_titles[col]:
            return
        self.column_titles[col] = new_name
        if 0 <= col < len(self._header_labels):
            self._header_labels[col].configure(text=new_name)
        self._save_column_settings()
        self._set_status(f"Renamed column to '{new_name}'.")

    def _delete_column(self, col: int) -> None:
        if not (0 <= col < InventoryApp.COLUMN_COUNT):
            return
        # Refuse to hide every column at once — the table would become
        # an empty rectangle with no way to reach the right-click menu.
        if len(self.hidden_columns) + 1 >= InventoryApp.COLUMN_COUNT:
            themed_warning(
                self.root,
                "Hide Column",
                "At least one column must remain visible.",
            )
            return
        self.hidden_columns.add(col)
        self._apply_column_visibility()
        self._save_column_settings()
        self._set_status(
            f"Hid column '{self.column_titles[col]}'. "
            f"Restore via Menu \u2192 Restore Columns."
        )

    def _restore_columns(self) -> None:
        if not self.hidden_columns:
            return
        self.hidden_columns.clear()
        self._apply_column_visibility()
        self._save_column_settings()
        self._set_status("Restored all hidden columns.")

    def _apply_column_visibility(self) -> None:
        """Hide / show grid cells in every column according to state."""
        # Reapply column weights for header + rows so that hidden columns
        # actually collapse to zero width.
        if self._header_frame is not None:
            self._configure_columns(self._header_frame)
        if hasattr(self, "rows_frame"):
            self._configure_columns(self.rows_frame)

        # Header
        for col, lbl in enumerate(self._header_labels):
            if col in self.hidden_columns:
                lbl.grid_remove()
            else:
                lbl.grid()

        # Every cell of every row
        for row in self.rows:
            for col, widget in enumerate(row.widgets):
                if col in self.hidden_columns:
                    widget.grid_remove()
                elif row._visible:
                    widget.grid()

    def _save_column_settings(self) -> None:
        self.settings["column_titles"] = list(self.column_titles)
        self.settings["hidden_columns"] = sorted(self.hidden_columns)
        save_settings(self.settings)

    # ----- Status bar -----

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self.root, bg=BG, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        sep = tk.Frame(bar, bg=BORDER, height=1)
        sep.pack(fill="x", side="top")

        self.status_var = tk.StringVar(value="Ready.")
        tk.Label(
            bar, textvariable=self.status_var, bg=BG, fg=MUTED,
            font=FONT_REGULAR, anchor="w", padx=18,
        ).pack(side="left", fill="both", expand=True)

        self.dirty_var = tk.StringVar(value="")
        tk.Label(
            bar, textvariable=self.dirty_var, bg=BG, fg=ERROR_FG,
            font=FONT_BOLD, padx=10,
        ).pack(side="right")

        self.grand_total_var = tk.StringVar(value="Units: 0   Revenue: $0.00")
        tk.Label(
            bar, textvariable=self.grand_total_var, bg=BG, fg=FG,
            font=FONT_BOLD, anchor="e", padx=18,
        ).pack(side="right")

    # ----- Row management -----

    def add_row(self) -> None:
        idx = len(self.rows)
        row = InventoryRow(
            self.rows_frame, row_index=idx,
            on_change=self._on_any_change,
            on_delete=self.delete_row,
            on_move=self.move_row,
        )
        self.rows.append(row)
        # Hide cells in any column the user has previously hidden, so
        # the newly added row matches the rest of the table.
        if self.hidden_columns:
            for col in self.hidden_columns:
                if col < len(row.widgets):
                    row.widgets[col].grid_remove()
        if not self._suppress_dirty:
            self._mark_dirty()
            self._set_status(f"Added row. Total rows: {len(self.rows)}")
            # Reveal the new row (it lives at the bottom of the table)
            # once Tk has finished laying it out.
            self.root.after_idle(lambda: self.canvas.yview_moveto(1.0))
        self._on_any_change()
        self._apply_filter()

    def delete_row(self, row: InventoryRow) -> None:
        if row not in self.rows:
            return
        row.destroy()
        self.rows.remove(row)
        self._reflow()
        self._mark_dirty()
        self._on_any_change()
        self._set_status(f"Row removed. Total rows: {len(self.rows)}")
        self._apply_filter()

    def move_row(self, row: InventoryRow, delta: int) -> None:
        i = self.rows.index(row)
        j = i + delta
        if j < 0 or j >= len(self.rows):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self._reflow()
        self._mark_dirty()

    def _reflow(self) -> None:
        for i, row in enumerate(self.rows):
            for w in row.widgets:
                info = w.grid_info()
                if info:
                    w.grid_configure(row=i)
            row.row_index = i

    def clear_all(self) -> None:
        if not self.rows:
            return
        if not themed_yesno(
            self.root,
            "Clear All",
            "Remove every row in the current week? This cannot be undone.",
        ):
            return
        for row in list(self.rows):
            row.destroy()
        self.rows.clear()
        self._mark_dirty()
        self._on_any_change()
        self._set_status("Cleared all rows.")

    def _on_any_change(self) -> None:
        units = 0.0
        revenue = 0.0
        for row in self.rows:
            days = [safe_float(v.get()) for v in row.day_vars]
            t = sum(days)
            units += t
            revenue += t * safe_float(row.price_var.get())
        self.grand_total_var.set(
            f"Units: {fmt_num(units)}   Revenue: {fmt_money(revenue)}"
        )
        if not self._suppress_dirty:
            self._mark_dirty()

    def _apply_filter(self) -> None:
        q = self._search_var.get().strip()
        for row in self.rows:
            row.set_visible(row.matches(q))
        # set_visible re-grids every widget in the row, which would
        # un-hide cells belonging to any hidden column. Reapply state.
        if self.hidden_columns:
            self._apply_column_visibility()

    # ----- Dirty state / title -----

    def _mark_dirty(self, dirty: bool = True) -> None:
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self.dirty_var.set("\u25CF Unsaved changes" if dirty else "")
        self._update_title()

    def _update_title(self) -> None:
        # Only the brand name is shown in the OS title bar by user
        # request. The dirty state, current file name, and current week
        # remain visible in the status bar at the bottom of the window.
        self.root.title("Invento")

    # ----- Week switching -----

    def _switch_week(self, new_week: str) -> None:
        if new_week == self.current_week:
            return
        # Snapshot current week's rows into the in-memory model
        self.weeks[self.current_week] = [r.to_dict() for r in self.rows]

        self._suppress_dirty = True
        for row in list(self.rows):
            row.destroy()
        self.rows.clear()

        self.current_week = new_week
        self.week_var.set(format_iso_week(new_week))
        for row_data in self.weeks.get(new_week, []):
            self.add_row()
            self.rows[-1].from_dict(row_data)
        if not self.rows:
            for _ in range(3):
                self.add_row()
        self._on_any_change()
        self._suppress_dirty = False

        self._mark_dirty(False)
        self._update_title()
        self._apply_filter()
        self._set_status(f"Switched to {format_iso_week(new_week)}")

    # ----- Save / Load -----

    def save_to_disk(self) -> None:
        self._write_json(self.current_path)

    def save_as(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile=self.current_path.name,
        )
        if not path:
            return
        self.current_path = Path(path)
        self._write_json(self.current_path)

    def _write_json(self, path: Path) -> None:
        path = Path(path)
        self.weeks[self.current_week] = [r.to_dict() for r in self.rows]
        data = {
            "version": 2,
            "current_week": self.current_week,
            "weeks": self.weeks,
        }
        try:
            atomic_write(path, json.dumps(data, indent=2))
        except OSError as e:
            themed_error(self.root, "Save failed", str(e))
            return
        self._mark_dirty(False)
        self._update_title()
        self._set_status(f"Saved to {path.name}")
        self.settings["last_path"] = str(self.current_path)
        save_settings(self.settings)

    def load_from_file(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not path:
            return
        self.current_path = Path(path)
        self._load_from_disk(self.current_path)

    def _load_from_disk(self, path: Path, silent: bool = False) -> None:
        path = Path(path)
        if not path.exists():
            if not silent:
                themed_warning(self.root, "Load", f"No file found at:\n{path}")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            if not silent:
                themed_error(self.root, "Load failed", str(e))
            return

        if isinstance(data, dict) and "weeks" in data:
            self.weeks = {k: list(v) for k, v in data.get("weeks", {}).items()}
            self.current_week = data.get("current_week") or current_iso_week()
        else:
            # Legacy v1: {"rows": [...]}
            week = current_iso_week()
            self.weeks = {week: list(data.get("rows", []))}
            self.current_week = week

        if self.current_week not in self.weeks:
            self.weeks[self.current_week] = []

        self._suppress_dirty = True
        for row in list(self.rows):
            row.destroy()
        self.rows.clear()
        for row_data in self.weeks[self.current_week]:
            self.add_row()
            self.rows[-1].from_dict(row_data)
        self._on_any_change()
        self._suppress_dirty = False

        self.week_var.set(format_iso_week(self.current_week))
        self._mark_dirty(False)
        self._update_title()
        if not silent:
            self._set_status(f"Loaded from {path.name}")

    # ----- Exports -----

    def _current_rows_data(self) -> List[dict]:
        return [r.to_dict() for r in self.rows]

    def export_as_txt(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All files", "*.*")],
            initialfile=f"invento_{self.current_week}.txt",
        )
        if not path:
            return
        lines = render_report_lines(self._current_rows_data(), self.current_week)
        try:
            Path(path).write_text("\n".join(lines), encoding="utf-8")
        except OSError as e:
            themed_error(self.root, "Export failed", str(e))
            return
        self._set_status(f"Exported TXT to {Path(path).name}")

    def export_as_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
            initialfile=f"invento_{self.current_week}.csv",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                render_csv(self._current_rows_data(), self.current_week),
                encoding="utf-8", newline="",
            )
        except OSError as e:
            themed_error(self.root, "Export failed", str(e))
            return
        self._set_status(f"Exported CSV to {Path(path).name}")

    def export_as_pdf(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
            initialfile=f"invento_{self.current_week}.pdf",
        )
        if not path:
            return
        try:
            write_pdf(
                path,
                render_report_lines(self._current_rows_data(), self.current_week),
            )
        except OSError as e:
            themed_error(self.root, "Export failed", str(e))
            return
        self._set_status(f"Exported PDF to {Path(path).name}")

    # ----- Shortcuts -----

    def _install_shortcuts(self) -> None:
        binds = [
            ("<Control-s>", lambda _e: self.save_to_disk()),
            ("<Control-S>", lambda _e: self.save_to_disk()),
            ("<Control-Shift-S>", lambda _e: self.save_as()),
            ("<Control-Shift-s>", lambda _e: self.save_as()),
            ("<Control-o>", lambda _e: self.load_from_file()),
            ("<Control-O>", lambda _e: self.load_from_file()),
            ("<Control-n>", lambda _e: self.add_row()),
            ("<Control-N>", lambda _e: self.add_row()),
            ("<Control-f>", lambda _e: self._focus_search()),
            ("<Control-F>", lambda _e: self._focus_search()),
        ]
        for seq, cb in binds:
            self.root.bind_all(seq, cb)

    def _focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    # ----- Close handling -----

    def _confirm_discard(self) -> bool:
        ans = themed_yesnocancel(
            self.root,
            "Unsaved changes",
            "You have unsaved changes. Save them first?",
        )
        if ans is None:
            return False
        if ans:
            self.save_to_disk()
            return not self._dirty
        return True

    def _on_close(self) -> None:
        if self._dirty and not self._confirm_discard():
            return
        try:
            self.settings["geometry"] = self.root.winfo_geometry()
            self.settings["last_path"] = str(self.current_path)
            save_settings(self.settings)
        except tk.TclError:
            pass
        self.root.destroy()

    def show_about(self) -> None:
        themed_info(
            self.root,
            "About Invento",
            "Invento — Inventory Manager\n\n"
            "Track weekly inventory, sales and revenue across multiple ISO weeks.\n"
            "Data is saved locally as JSON (atomic write + .bak rotation).\n"
            "Reports export to TXT, CSV, or PDF.\n\n"
            "Shortcuts: Ctrl+S Save · Ctrl+Shift+S Save As · Ctrl+O Load\n"
            "           Ctrl+N New Item · Ctrl+F Search",
        )

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)


def _show_splash(root: tk.Tk) -> Optional[tk.Toplevel]:
    """Display a frameless logo splash and return the Toplevel.

    Returns None if the logo can't be loaded (so the app starts normally
    without holding the user up).
    """
    if not LOGO_FILE.exists():
        return None
    try:
        logo = tk.PhotoImage(file=str(LOGO_FILE))
    except tk.TclError:
        return None

    # The source PNG is large (~1024 px wide). Halve it for a sensible
    # splash size; PhotoImage.subsample only takes integer factors.
    if logo.width() > 720:
        logo = logo.subsample(2, 2)

    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg=SPLASH_BG)

    img_w, img_h = logo.width(), logo.height()
    pad = 24
    w, h = img_w + pad * 2, img_h + pad * 2

    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2 - 40
    splash.geometry(f"{w}x{h}+{x}+{max(y, 0)}")

    label = tk.Label(splash, image=logo, bg=SPLASH_BG, borderwidth=0)
    # Keep a reference on the widget so the PhotoImage isn't GC'd early.
    label.image = logo  # type: ignore[attr-defined]
    label.pack(padx=pad, pady=pad)

    splash.lift()
    try:
        splash.attributes("-topmost", True)
    except tk.TclError:
        pass
    splash.update_idletasks()
    return splash


def main() -> None:
    root = tk.Tk()
    apply_dark_titlebar(root)

    # Replace the default Tk feather icon with a fully transparent one so
    # the title bar is visually blank. A 16x16 empty PhotoImage is filled
    # with transparent pixels by default. We hold a reference on the root
    # so it isn't garbage-collected.
    try:
        blank_icon = tk.PhotoImage(width=16, height=16)
        root.iconphoto(True, blank_icon)
        root._invento_blank_icon = blank_icon  # type: ignore[attr-defined]
    except tk.TclError:
        pass

    try:
        root.tk.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Vertical.TScrollbar",
        background=ACCENT,
        troughcolor=BG,
        bordercolor=BG,
        arrowcolor=FG,
    )

    # Hide the main window while the splash is up, then build the app
    # in the background so it's ready to appear the moment the splash
    # is dismissed.
    root.withdraw()
    splash = _show_splash(root)

    InventoryApp(root)

    def _reveal() -> None:
        if splash is not None:
            try:
                splash.destroy()
            except tk.TclError:
                pass
        root.deiconify()
        root.lift()
        root.focus_force()

    if splash is not None:
        root.after(SPLASH_DURATION_MS, _reveal)
    else:
        _reveal()

    root.mainloop()


if __name__ == "__main__":
    main()
