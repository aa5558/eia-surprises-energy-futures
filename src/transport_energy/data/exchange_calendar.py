"""Exchange-documented contract expiries and the scheduled business-day calendar.

Expiry dates come from two documented sources, never from price behaviour:

1. **CME-published last-trade dates.** CME's product-calendar pages list every listed
   contract with its first/last trade date. Archived copies (Internet Archive, one
   per year from late 2009) document expiries for contracts listed at capture time.
2. **The rulebook rule** (NYMEX Rulebook ch. 200 for CL, ch. 191 for RB, archived
   2015 and 2024/2026 copies; same text in the EIA series definitions) applied to a
   *scheduled* business-day calendar, for contracts the CME pages do not cover.

Why a separate calendar: the rule counts *exchange business days*. EIA's price files
omit some days the exchange was open (abbreviated sessions such as the day after
Thanksgiving, plus isolated data gaps), so counting EIA price dates can shift an
expiry. And ch. 200 says an unscheduled closure after listing does not move the
originally listed expiry, so such closures still count as business days.
"""

from __future__ import annotations

import re

import pandas as pd
from pandas.tseries.holiday import GoodFriday, USFederalHolidayCalendar

from transport_energy.backtesting.contracts import MONTH_CODES, contract_id
from transport_energy.data.html import text_tokens

_MONTH_ABBR = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
    start=1)}
_LABEL_RE = re.compile(r"^([A-Z]{3}) (\d{4})$")
_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def parse_cme_calendar(html: str, root: str) -> pd.DataFrame:
    """Rows (contract, year, month, last_trade) from a CME product-calendar page.

    The page lists, per contract: month label (``FEB 2012``), product code
    (``CLG12``), first trade, last trade, ... The code is checked against the label so a
    misaligned table raises instead of silently mis-dating a contract.
    """
    tokens = text_tokens(html)
    code_re = re.compile(rf"^{root}([{MONTH_CODES}])(\d{{2}})$")
    rows = []
    for i in range(len(tokens) - 3):
        lab = _LABEL_RE.match(tokens[i])
        code = code_re.match(tokens[i + 1])
        if not (lab and code and lab.group(1) in _MONTH_ABBR):
            continue
        year, month = int(lab.group(2)), _MONTH_ABBR[lab.group(1)]
        if MONTH_CODES[month - 1] != code.group(1) or year % 100 != int(code.group(2)):
            raise ValueError(f"label {tokens[i]!r} does not match code {tokens[i + 1]!r}")
        d = _DATE_RE.match(tokens[i + 3])
        if d is None:
            continue
        last = pd.Timestamp(int(d.group(3)), int(d.group(1)), int(d.group(2)))
        rows.append((contract_id(root, year, month), year, month, last))
    return pd.DataFrame(rows, columns=["contract", "year", "month", "last_trade"])


def combine_cme_calendars(frames: list[tuple[pd.Timestamp, pd.DataFrame]]) -> tuple[
        pd.DataFrame, pd.DataFrame]:
    """Merge yearly page copies into (expiries, conflicts).

    For each contract the copy captured closest *before* its expiry wins (the last
    schedule the market saw); disagreements between copies are returned for review.
    """
    tagged = [df.assign(snapshot=ts) for ts, df in frames if not df.empty]
    if not tagged:
        return pd.DataFrame(), pd.DataFrame()
    allc = pd.concat(tagged, ignore_index=True)
    variants = allc.drop_duplicates(["contract", "last_trade"])
    n = variants.groupby("contract").size()
    conflicts = allc[allc["contract"].isin(n[n > 1].index)].sort_values(["contract", "snapshot"])
    before = allc[allc["snapshot"] <= allc["last_trade"] + pd.Timedelta(days=1)]
    pick = pd.concat([
        before.sort_values("snapshot").drop_duplicates("contract", keep="last"),
        allc.sort_values("snapshot").drop_duplicates("contract", keep="first"),
    ]).drop_duplicates("contract", keep="first")
    out = pick.sort_values("last_trade").reset_index(drop=True)
    return out, conflicts.reset_index(drop=True)


def exchange_holidays(
    start: pd.Timestamp, end: pd.Timestamp, price_dates: pd.DatetimeIndex
) -> pd.DatetimeIndex:
    """Scheduled exchange holidays: federal holidays and Good Fridays with no settlement.

    A federal holiday or Good Friday counts as an exchange holiday only if no
    settlement exists that day (NYMEX trades on e.g. Columbus and Veterans Day). Any
    other missing weekday (abbreviated sessions, data gaps, unscheduled closures) stays
    a business day.
    """
    fed = USFederalHolidayCalendar().holidays(start, end)
    gf = GoodFriday.dates(start, end)
    candidates = fed.union(pd.DatetimeIndex(gf))
    return candidates.difference(pd.DatetimeIndex(price_dates).normalize())


def scheduled_business_days(
    start: pd.Timestamp, end: pd.Timestamp, price_dates: pd.DatetimeIndex
) -> pd.DatetimeIndex:
    """Weekdays minus scheduled exchange holidays (see :func:`exchange_holidays`)."""
    days = pd.bdate_range(start, end)
    return days.difference(exchange_holidays(start, end, price_dates))
