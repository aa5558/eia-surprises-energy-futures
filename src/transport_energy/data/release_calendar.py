"""Point-in-time WPSR release calendar.

Two separate sources, kept separate in the output:

1. **Release dates are observed.** The WPSR archive index lists every edition since
   August 2011 with its release date and the Friday that ends its data week.
2. **Release times are documented schedules, never observations.** EIA's schedule
   page (live, and archived copies back to 2002 in the Internet Archive) states a
   standard day/time and lists holiday exceptions with their own times. A scheduled
   time is used only when the page was in force for that period *and* the observed
   release date equals the scheduled date. Otherwise the time is unknown and the
   release is represented by the whole day, ``[D 00:00, D 23:59:59]`` ET.

Downstream code uses ``release_ts_earliest`` to close the window *before* a release
(announcement window, holding-period exit) and ``release_ts_latest`` to open the
window *after* it (earliest entry). With an unknown time that pushes entry to the
next day's settlement; with a documented time both bounds coincide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from transport_energy.data.html import text_tokens

TZ = "America/New_York"

TIME_DOCUMENTED = "scheduled_documented"
TIME_ASSUMED = "assumed_conservative"


# --------------------------------------------------------------------------- HTML helpers
class _TableCells(HTMLParser):
    """Collect table rows as lists of (text, href) cells, plus a marker at each <thead>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, str | None]] | str] = []
        self._row: list[tuple[str, str | None]] | None = None
        self._cell: list[str] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "thead":
            self.rows.append("THEAD")
        elif tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._href = [], None
        elif tag == "a" and self._cell is not None and a.get("href"):
            self._href = a["href"]

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append((" ".join("".join(self._cell).split()), self._href))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


# --------------------------------------------------------------------------- archive index
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)}
_FOLDER_RE = re.compile(r"/archive/(\d{4})/(\d{4})_(\d{2})_(\d{2})(_\w+)?/")


def parse_archive_index(html: str, base_url: str = "https://www.eia.gov") -> pd.DataFrame:
    """One row per WPSR edition listed on the archive index page.

    Columns: ``release_date`` (as displayed), ``data_ending`` (Friday ending the data
    week, as displayed), ``folder_date`` (date in the edition's folder name),
    ``folder_suffix`` (e.g. ``_data``) and ``edition_url``.
    """
    parser = _TableCells()
    parser.feed(html)
    rows = []
    month: int | None = None
    for row in parser.rows:
        if row == "THEAD":
            month = None
            continue
        if row and row[0][0] in MONTHS:
            month = MONTHS[row[0][0]]
        # cells after the month label come in (release link, data ending) pairs
        cells = row[1:]
        for j in range(0, len(cells) - 1, 2):
            (day_text, href), (end_text, _) = cells[j], cells[j + 1]
            if not href or "/archive/" not in href or month is None:
                continue
            m = _FOLDER_RE.search(href)
            if m is None or not day_text.isdigit():
                raise ValueError(f"unrecognised archive cell {day_text!r} -> {href!r}")
            year = int(m.group(1))
            release = pd.Timestamp(year, month, int(day_text))
            if "/" in end_text:
                em, ed = (int(x) for x in end_text.split("/"))
            else:
                em, ed = month, int(end_text)
            ey = year - 1 if em > month else year
            rows.append({
                "release_date": release,
                "data_ending": pd.Timestamp(ey, em, ed),
                "folder_date": pd.Timestamp(int(m.group(2)), int(m.group(3)), int(m.group(4))),
                "folder_suffix": m.group(5) or "",
                "edition_url": base_url + href if href.startswith("/") else href,
            })
    out = pd.DataFrame(rows)
    return out.sort_values(["release_date", "data_ending"]).reset_index(drop=True)


# --------------------------------------------------------------------------- schedule pages
_DATE_RE = re.compile(r"^([A-Z][a-z]+)\.? (\d{1,2}), (\d{4})$")
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?", re.IGNORECASE)
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_STANDARD_RE = re.compile(
    r"standard release time and day of the week will be at\s+(.+?)\s*(?:\(eastern time\)\s*)?"
    r"(?:eastern time\s*)?on\s+(\w+?)s?\b",
    re.IGNORECASE,
)


def parse_clock(text: str) -> str:
    """'10:30 a.m.' / '12:00 p.m.' / '5 p.m.' / 'noon' -> 'HH:MM' (24h)."""
    if text.strip().lower() == "noon":
        return "12:00"
    m = _TIME_RE.search(text)
    if not m:
        raise ValueError(f"unrecognised time {text!r}")
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if ampm == "p" and hour != 12:
        hour += 12
    if ampm == "a" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _parse_date(token: str) -> pd.Timestamp | None:
    m = _DATE_RE.match(token.strip())
    if not m or m.group(1)[:3] not in {k[:3] for k in MONTHS}:
        return None
    month = next(v for k, v in MONTHS.items() if k.startswith(m.group(1)[:3]))
    return pd.Timestamp(int(m.group(3)), month, int(m.group(2)))


@dataclass(frozen=True)
class SchedulePage:
    snapshot: pd.Timestamp              # when this copy of the page was captured
    source_url: str
    standard_weekday: str | None        # e.g. "Wednesday"
    standard_time: str | None           # "HH:MM"
    exceptions: pd.DataFrame            # data_ending, scheduled_date, weekday, time, holiday


def parse_schedule_page(html: str, snapshot: pd.Timestamp, source_url: str) -> SchedulePage:
    """Standard rule and holiday-exception rows from one copy of the WPSR schedule page."""
    tokens = text_tokens(html)
    text = " ".join(tokens)
    std = _STANDARD_RE.search(text)
    weekday = std_time = None
    if std:
        std_time = parse_clock(std.group(1))
        wd = std.group(2).capitalize()
        weekday = next((d for d in _WEEKDAYS if d.startswith(wd[:3])), None)
    rows = []
    for i in range(len(tokens) - 3):
        d1, d2 = _parse_date(tokens[i]), _parse_date(tokens[i + 1])
        if d1 is None or d2 is None or tokens[i + 2] not in _WEEKDAYS:
            continue
        try:
            clock = parse_clock(tokens[i + 3])
        except ValueError:
            continue
        holiday = tokens[i + 4] if i + 4 < len(tokens) else ""
        rows.append({"data_ending": d1, "scheduled_date": d2, "weekday": tokens[i + 2],
                     "time": clock, "holiday": holiday})
    exc = pd.DataFrame(rows, columns=["data_ending", "scheduled_date", "weekday", "time",
                                      "holiday"])
    if not exc.empty:
        bad = exc["scheduled_date"].dt.day_name() != exc["weekday"]
        if bad.any():
            raise ValueError(f"{source_url}: weekday does not match date in {exc[bad]}")
    return SchedulePage(pd.Timestamp(snapshot), source_url, weekday, std_time, exc)


def combine_schedules(pages: list[SchedulePage]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Merge schedule copies into (exceptions, coverage, conflicts).

    * exceptions: one row per data week; if copies disagree, the latest capture wins
      (a schedule can be revised before the release, never after it is published).
    * coverage: the *release dates* each copy documents — from its capture date or first
      listed release (whichever is earlier) to its last listed release — with the
      standard rule it states.
    * conflicts: data weeks whose scheduled date/time differ between copies.
    """
    frames, cover = [], []
    for p in pages:
        if p.exceptions.empty:
            continue
        e = p.exceptions.assign(snapshot=p.snapshot, source_url=p.source_url)
        frames.append(e)
        # A copy captured before its first listed exception also documents that no
        # exception applies between capture and that row; never extend past the last row.
        cover.append({
            "snapshot": p.snapshot, "source_url": p.source_url,
            "start": min(e["scheduled_date"].min(), p.snapshot.normalize()),
            "end": e["scheduled_date"].max(),
            "standard_weekday": p.standard_weekday, "standard_time": p.standard_time,
        })
    if not frames:
        empty = pd.DataFrame()
        return empty, empty, empty
    allx = pd.concat(frames, ignore_index=True)
    variants = allx.drop_duplicates(["data_ending", "scheduled_date", "time"])
    multi = variants.groupby("data_ending").size()
    conflicts = variants[variants["data_ending"].isin(multi[multi > 1].index)].sort_values(
        ["data_ending", "snapshot"])
    latest = allx.sort_values("snapshot").drop_duplicates("data_ending", keep="last")
    return (latest.sort_values("data_ending").reset_index(drop=True),
            pd.DataFrame(cover).sort_values("start").reset_index(drop=True),
            conflicts.reset_index(drop=True))


def scheduled_release(
    data_ending: pd.Timestamp, exceptions: pd.DataFrame, coverage: pd.DataFrame
) -> tuple[pd.Timestamp | None, str | None, str]:
    """Documented (date, 'HH:MM', basis) for one data week, or (None, None, reason)."""
    if not exceptions.empty:
        hit = exceptions[exceptions["data_ending"] == data_ending]
        if len(hit):
            r = hit.iloc[0]
            return r["scheduled_date"], r["time"], f"exception listed on {r['source_url']}"
    if coverage.empty:
        return None, None, "no schedule documentation"
    # standard rule: the standard release date must lie inside a page's coverage
    best = None
    for _, page in coverage[coverage["standard_time"].notna()].iterrows():
        target = _WEEKDAYS.index(page["standard_weekday"])
        offset = (target - data_ending.weekday()) % 7 or 7   # first such day after F
        date = data_ending + pd.Timedelta(days=offset)
        if page["start"] <= date <= page["end"] and (
                best is None or page["snapshot"] > best[0]["snapshot"]):
            best = (page, date)
    if best is None:
        return None, None, "no schedule page covers this period"
    page, date = best
    return date, page["standard_time"], f"standard rule on {page['source_url']}"


# --------------------------------------------------------------------------- calendar
def build_release_calendar(
    archive: pd.DataFrame, exceptions: pd.DataFrame, coverage: pd.DataFrame, tz: str = TZ
) -> pd.DataFrame:
    """Archive editions with documented-or-assumed release timestamps (tz-aware)."""
    out = archive.copy()
    sched = [scheduled_release(f, exceptions, coverage) for f in out["data_ending"]]
    out["scheduled_date"] = [s[0] for s in sched]
    out["scheduled_time"] = [s[1] for s in sched]
    out["schedule_basis"] = [s[2] for s in sched]
    matches = out["scheduled_date"].notna() & (out["scheduled_date"] == out["release_date"])
    out["date_source"] = "observed_archive"
    out["time_source"] = [TIME_DOCUMENTED if m else TIME_ASSUMED for m in matches]
    reasons = []
    for m, s in zip(matches, out["scheduled_date"], strict=True):
        if m:
            reasons.append("")
        elif s is None or pd.isna(s):
            reasons.append("time not documented")
        else:
            reasons.append("observed date differs from scheduled date")
    out["assumption_reason"] = reasons
    day = out["release_date"].dt.normalize()
    clock = pd.to_timedelta(out["scheduled_time"].where(matches).fillna("00:00") + ":00")
    earliest = (day + clock.where(matches, pd.Timedelta(0))).dt.tz_localize(tz)
    latest = (day + clock.where(matches, pd.Timedelta(hours=23, minutes=59, seconds=59)))
    out["release_ts_earliest"] = earliest
    out["release_ts_latest"] = latest.dt.tz_localize(tz)
    return out


def holiday_week_flags(data_ending: pd.Series) -> pd.Series:
    """True if a US federal holiday falls between Monday F+3 and Friday F+7 (doc 02 §1.2)."""
    f = pd.DatetimeIndex(data_ending)
    hol = USFederalHolidayCalendar().holidays(f.min() - pd.Timedelta(days=7),
                                              f.max() + pd.Timedelta(days=14))
    flags = [((hol >= d + pd.Timedelta(days=3)) & (hol <= d + pd.Timedelta(days=7))).any()
             for d in f]
    return pd.Series(flags, index=data_ending.index, name="holiday_week")


def check_release_window(
    calendar: pd.DataFrame, days_after: int = 7, assumed_by: str = "14:29", tz: str = TZ
) -> pd.DataFrame:
    """Test Assumption A on observed releases: public by ``F + days_after`` at ``assumed_by``.

    A release *violates* the assumption if its latest possible release time (which is
    the end of the day when the time is undocumented) is after the bound.
    """
    bound = (calendar["data_ending"].dt.normalize() + pd.Timedelta(days=days_after)
             + pd.to_timedelta(assumed_by + ":00")).dt.tz_localize(tz)
    out = calendar[["data_ending", "release_date", "time_source", "release_ts_latest"]].copy()
    out["bound"] = bound
    out["holiday_week"] = holiday_week_flags(calendar["data_ending"])
    out["violates"] = out["release_ts_latest"] > out["bound"]
    out["days_after_reference"] = (out["release_date"] - out["data_ending"]).dt.days
    return out
