"""EIA keyless bulk Excel files (``hist_xls``): download and parse.

Layout (verified 2026-10-21): sheet ``Data 1``; row 1 holds ``Sourcekey``, row 2 the
column titles, then one row per observation with an Excel serial date and a value.
Weekly series are dated by the Friday that ends the reference week; that is the
*economic* date, not the date the number became public (see ``release_calendar``).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import xlrd

from transport_energy.config import load_config
from transport_energy.data.download import Fetcher

EXCEL_EPOCH = pd.Timestamp("1899-12-30")   # Excel 1900 date system as written by EIA


def parse_hist_xls(path: Path | str, expected_key: str | None = None) -> pd.Series:
    """Return the series in an EIA ``hist_xls`` workbook, indexed by date.

    Raises if the workbook does not have the expected layout, so that a silent
    format change at the source cannot shift or mislabel data.
    """
    book = xlrd.open_workbook(str(path))
    if "Data 1" not in book.sheet_names():
        raise ValueError(f"{path}: no 'Data 1' sheet (got {book.sheet_names()})")
    sheet = book.sheet_by_name("Data 1")
    if sheet.cell_value(1, 0) != "Sourcekey":
        raise ValueError(f"{path}: unexpected header layout")
    key = str(sheet.cell_value(1, 1))
    if expected_key is not None and key != expected_key:
        raise ValueError(f"{path}: source key {key!r}, expected {expected_key!r}")
    dates, values = [], []
    for r in range(3, sheet.nrows):
        d, v = sheet.cell_value(r, 0), sheet.cell_value(r, 1)
        if d == "":
            continue
        dates.append(EXCEL_EPOCH + pd.Timedelta(days=float(d)))
        values.append(float(v) if v != "" else float("nan"))
    s = pd.Series(values, index=pd.DatetimeIndex(dates, name="date"), name=key, dtype=float)
    if not s.index.is_monotonic_increasing or s.index.has_duplicates:
        raise ValueError(f"{path}: dates not strictly increasing")
    return s


def series_url(series_id: str, cfg: dict | None = None) -> str:
    cfg = cfg or load_config("data")
    return cfg["eia"]["bulk_xls_url"].format(series=series_id)


def download_group(group: str, fetcher: Fetcher, cfg: dict | None = None) -> dict[str, Path]:
    """Download every series in ``data.yaml -> eia -> <group>``; returns name -> path."""
    cfg = cfg or load_config("data")
    out = {}
    for name, spec in cfg["eia"][group].items():
        out[name] = fetcher.fetch(series_url(spec["id"], cfg), f"eia/{group}/{spec['id']}.xls")
    return out


def source_key(series_id: str) -> str:
    """EIA file stems carry a frequency suffix (``WGFUPUS2w``); the sheet key does not."""
    return series_id[:-1] if series_id[-1] in "wdma" else series_id


def load_group(group: str, raw_root: Path, cfg: dict | None = None) -> pd.DataFrame:
    """All series of a group as one DataFrame (outer-joined on date), columns = config names."""
    cfg = cfg or load_config("data")
    cols = {}
    for name, spec in cfg["eia"][group].items():
        path = Path(raw_root) / "eia" / group / f"{spec['id']}.xls"
        cols[name] = parse_hist_xls(path, expected_key=source_key(spec["id"]))
    return pd.DataFrame(cols)
