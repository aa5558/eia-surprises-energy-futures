"""Futures expiry calendars, nearby labelling and roll schedules.

EIA publishes "contract 1..4" settlements with no contract identity: contract 1
silently becomes a different contract after each expiry. To compute honest P&L
we reconstruct which contract each nearby refers to from exchange expiry rules,
then compute every price change *within a single contract*.

Expiry rules (to be re-verified against CME rulebooks and the data in Phase 3):

* CL (WTI): trading ends 3 business days before the 25th calendar day of the month
  before the contract month; if the 25th is not a business day, 3 business days
  before the last business day preceding the 25th.
* RB (RBOB): trading ends on the last business day of the month before the
  contract month.

"Business day" = a date in the supplied ``trading_days`` index, which is taken
from the price data itself, so exchange holidays need no separate library.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

MONTH_CODES = "FGHJKMNQUVXZ"


def contract_id(root: str, year: int, month: int) -> str:
    """E.g. ``contract_id("CL", 2020, 5) == "CLK2020"`` (4-digit year avoids ambiguity)."""
    return f"{root}{MONTH_CODES[month - 1]}{year}"


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _check_coverage(trading_days: pd.DatetimeIndex, date: pd.Timestamp) -> None:
    if not (trading_days[0] <= date <= trading_days[-1]):
        raise ValueError(f"{date.date()} is outside the trading-day calendar")


def cl_last_trade_date(year: int, month: int, trading_days: pd.DatetimeIndex) -> pd.Timestamp:
    py, pm = _previous_month(year, month)
    target = pd.Timestamp(py, pm, 25)
    _check_coverage(trading_days, target)
    i = trading_days.searchsorted(target, side="left")  # first trading day >= the 25th
    # If the 25th trades, count back 3 from it; otherwise 3 back from the last trading
    # day before the 25th, which is 4 positions back from i.
    steps = 3 if trading_days[i] == target else 4
    if i - steps < 0:
        raise ValueError(f"calendar starts too late to locate the expiry before {target.date()}")
    return pd.Timestamp(trading_days[i - steps])


def rb_last_trade_date(year: int, month: int, trading_days: pd.DatetimeIndex) -> pd.Timestamp:
    py, pm = _previous_month(year, month)
    month_end = pd.Timestamp(py, pm, 1) + pd.offsets.MonthEnd(0)
    _check_coverage(trading_days, month_end)
    i = trading_days.searchsorted(month_end, side="right") - 1
    return pd.Timestamp(trading_days[i])


EXPIRY_RULES: dict[str, Callable[[int, int, pd.DatetimeIndex], pd.Timestamp]] = {
    "cl": cl_last_trade_date,
    "rb": rb_last_trade_date,
}


def expiry_table(root: str, rule: str, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """All monthly contracts whose expiry can be computed inside the calendar."""
    fn = EXPIRY_RULES[rule]
    rows = []
    first, last = trading_days[0], trading_days[-1]
    for year in range(first.year, last.year + 2):
        for month in range(1, 13):
            try:
                expiry = fn(year, month, trading_days)
            except (ValueError, IndexError):
                continue
            rows.append((contract_id(root, year, month), year, month, expiry))
    table = pd.DataFrame(rows, columns=["contract", "year", "month", "expiry"])
    return table.sort_values("expiry").reset_index(drop=True)


def label_nearbys(
    trading_days: pd.DatetimeIndex, expiries: pd.DataFrame, depth: int = 3
) -> pd.DataFrame:
    """Contract id of nearby 1..depth on each date. Nearby 1 = first contract with expiry >= date.

    A contract still trades on its expiry date, so it remains nearby 1 that day.
    """
    exp = pd.DatetimeIndex(expiries["expiry"])
    first = exp.searchsorted(trading_days, side="left")
    out = {}
    for k in range(depth):
        pos = first + k
        out[k + 1] = [
            expiries["contract"].iat[p] if p < len(expiries) else None for p in pos
        ]
    return pd.DataFrame(out, index=trading_days)


def roll_schedule(
    trading_days: pd.DatetimeIndex, expiries: pd.DataFrame, business_days_before: int
) -> pd.Series:
    """Contract held at the close of each date.

    Contract k is held until its roll date, ``business_days_before`` trading days before
    its expiry. On the roll date the position is switched at settlement, so the
    held contract *from* that close onward is contract k+1.
    """
    if business_days_before < 1:
        raise ValueError("roll at least one business day before expiry")
    exp = pd.DatetimeIndex(expiries["expiry"])
    pos = trading_days.searchsorted(exp, side="left") - business_days_before
    # Expiry after the calendar: roll date unknown, treat as "not yet rolled".
    # Roll date before the calendar start: already rolled.
    roll_dates = pd.DatetimeIndex([
        pd.Timestamp.max if e > trading_days[-1]
        else pd.Timestamp.min if p < 0
        else trading_days[p]
        for p, e in zip(pos, exp, strict=True)
    ])
    contracts = expiries["contract"].to_numpy()
    idx = roll_dates.searchsorted(trading_days, side="right")
    held = [contracts[i] if i < len(contracts) else None for i in idx]
    return pd.Series(held, index=trading_days, name="held_contract")


def contract_price_panel(nearby_prices: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """Turn (date x nearby) prices into (date x contract) prices using nearby labels.

    Raises if two nearby columns claim different prices for the same contract-date.
    """
    long = (
        nearby_prices.stack(future_stack=True).rename("price").to_frame()
        .join(labels.stack(future_stack=True).rename("contract"))
        .dropna(subset=["price", "contract"])
        .reset_index(names=["date", "nearby"])
    )
    dup = long.duplicated(["date", "contract"], keep=False)
    if dup.any():
        spread = long[dup].groupby(["date", "contract"])["price"].agg(lambda s: s.max() - s.min())
        if (spread > 1e-9).any():
            raise ValueError("conflicting prices for the same contract and date")
    return long.drop_duplicates(["date", "contract"]).pivot(
        index="date", columns="contract", values="price"
    )
