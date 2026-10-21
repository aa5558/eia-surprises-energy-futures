"""Archived copies of official pages via the Internet Archive (Wayback Machine).

Used only for *documentation* that the source no longer serves: past WPSR release
schedules and CME contract calendars. The manifest records both the archive URL that
was fetched and the original page it is a copy of.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import pandas as pd

from transport_energy.data.download import Fetcher

CDX = "https://web.archive.org/cdx/search/cdx"


def snapshots(fetcher: Fetcher, url: str, collapse: str = "digest") -> pd.DataFrame:
    """Successful captures of ``url`` (one per distinct content by default)."""
    q = urlencode({"url": url, "output": "json", "fl": "timestamp,original",
                   "filter": "statuscode:200", "collapse": collapse})
    rows = json.loads(fetcher.get_text(f"{CDX}?{q}") or "[]")
    if not rows:
        return pd.DataFrame(columns=["timestamp", "original", "captured"])
    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["captured"] = pd.to_datetime(df["timestamp"], format="%Y%m%d%H%M%S")
    return df


def raw_url(timestamp: str, original: str) -> str:
    """URL of the capture exactly as archived (``id_`` = no Wayback toolbar rewriting)."""
    return f"https://web.archive.org/web/{timestamp}id_/{original}"
