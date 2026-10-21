"""First-release values from archived WPSR Table 1, and comparison with current history.

Each archived edition's ``csv/table1.csv`` shows the numbers as published that week:
the current data week and the prior week. Comparing the current-week column with
today's EIA history file answers: *is the history we use the same as what the market
saw?* If not, building surprises from history would use information that only
arrived later (revisions), a quiet form of look-ahead.

Units: Table 1 stocks are in million barrels (3 decimals = exact thousands), history
files in thousand barrels. Product supplied and production are kb/d in both.
"""

from __future__ import annotations

import csv
import io
import re

import pandas as pd

# (block, section, label) -> series name in configs/data.yaml; scale converts to history units
STOCK_ROWS = {
    "Commercial (Excluding SPR)": "crude_stocks_ex_spr",
    "Total Motor Gasoline": "gasoline_stocks",
    "Distillate Fuel Oil": "distillate_stocks",
}
BALANCE_ROWS = {
    ("Crude Oil Supply", "Domestic Production"): "crude_production",
    ("Products Supplied", "Total"): "total_product_supplied",
    ("Products Supplied", "Finished Motor Gasoline"): "gasoline_product_supplied",
}
STOCK_SCALE = 1000.0   # million barrels -> thousand barrels
_LINE_NO = re.compile(r"^\(\d+\)\s*")


def _num(text: str) -> float:
    t = text.replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return float("nan")


def _date(text: str) -> pd.Timestamp:
    return pd.to_datetime(text.strip(), format="%m/%d/%y")


def parse_table1(text: str) -> pd.DataFrame:
    """Long table: series, week, value, column ('current' | 'prior') from one edition."""
    rows = list(csv.reader(io.StringIO(text)))
    headers = [i for i, r in enumerate(rows) if r and r[0] == "STUB_1"]
    if len(headers) < 2:
        raise ValueError("Table 1 CSV: expected a stocks block and a balance block")
    out = []
    # block 1: stocks. Header: STUB_1, current, prior, ...
    h = rows[headers[0]]
    weeks = (_date(h[1]), _date(h[2]))
    seen: set[str] = set()
    for r in rows[headers[0] + 1: headers[1]]:
        label = r[0].strip() if r else ""
        name = STOCK_ROWS.get(label)
        if name and name not in seen:            # first occurrence = the national total
            seen.add(name)
            for col, wk, val in (("current", weeks[0], r[1]), ("prior", weeks[1], r[2])):
                out.append((name, wk, _num(val) * STOCK_SCALE, col))
    # block 2: supply/disposition. Header: STUB_1, STUB_2, current, prior, ...
    h = rows[headers[1]]
    weeks = (_date(h[2]), _date(h[3]))
    end = headers[2] if len(headers) > 2 else len(rows)
    for r in rows[headers[1] + 1: end]:
        if len(r) < 4:
            continue
        key = (r[0].strip(), _LINE_NO.sub("", r[1].strip()))
        name = BALANCE_ROWS.get(key)
        if name and name not in seen:
            seen.add(name)
            for col, wk, val in (("current", weeks[0], r[2]), ("prior", weeks[1], r[3])):
                out.append((name, wk, _num(val), col))
    missing = set(STOCK_ROWS.values()) | set(BALANCE_ROWS.values())
    missing -= seen
    if missing:
        raise ValueError(f"Table 1 CSV: rows not found for {sorted(missing)}")
    return pd.DataFrame(out, columns=["series", "week", "value", "column"])


def compare_with_history(
    first: pd.DataFrame, history: pd.DataFrame, tolerance: float = 0.5
) -> pd.DataFrame:
    """Join first-release values (``column == 'current'``) to the current history.

    ``history`` is wide (date x series, history units). Returns one row per
    (series, week) with ``first_release``, ``history``, ``diff`` and ``matches``.
    """
    cur = first[first["column"] == "current"].rename(columns={"value": "first_release"})
    hist = history.stack().rename("history").rename_axis(["week", "series"]).reset_index()
    out = cur.merge(hist, on=["series", "week"], how="left")
    out["diff"] = out["history"] - out["first_release"]
    out["matches"] = out["diff"].abs() <= tolerance
    return out.drop(columns="column")


def week_to_week_revisions(first: pd.DataFrame, tolerance: float = 0.5) -> pd.DataFrame:
    """Compare each edition's 'prior week' column with the previous edition's 'current'."""
    cur = first[first["column"] == "current"][["series", "week", "value"]]
    pri = first[first["column"] == "prior"][["series", "week", "value"]]
    m = cur.merge(pri, on=["series", "week"], suffixes=("_first", "_next_edition"))
    m["diff"] = m["value_next_edition"] - m["value_first"]
    m["matches"] = m["diff"].abs() <= tolerance
    return m
