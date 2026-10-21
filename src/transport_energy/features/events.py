"""Event windows and contract-aware returns around WPSR releases.

Returns are always computed *within the contract actually held* (see
``backtesting.contracts.roll_schedule``): the daily return on date d is
``P_h(d) / P_h(d-1) - 1`` with ``h`` the contract held at the close of d-1, so a roll
never books the gap between two contracts. A window return compounds these.

Two timing regimes (doc 02 §1.2):

* **precise** (editions in the WPSR archive, Aug 2011 on): windows from the release
  calendar's earliest/latest release times via ``timing.build_event_table``.
* **conservative** (any year; the only option before Aug 2011): announcement window
  from the settlement on reference Friday F to the first settlement after F+7 14:29;
  drift window from there to the last settlement before Wednesday F+12. Weeks with a
  federal holiday between Monday F+3 and Friday F+7 are excluded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from transport_energy.backtesting.contracts import (
    contract_price_panel,
    label_nearbys,
    roll_schedule,
)
from transport_energy.data.release_calendar import holiday_week_flags
from transport_energy.timing import (
    DEFAULT_TZ,
    build_event_table,
    conservative_release_ts,
    first_settlement_after,
    last_settlement_before,
)


def contract_daily(
    nearby: pd.DataFrame, expiries: pd.DataFrame, roll_days: int
) -> pd.DataFrame:
    """Daily held-contract panel from EIA-style nearby settlements.

    ``nearby`` has columns ``c1, c2, c3``; ``expiries`` columns ``contract, expiry``.
    Output columns: ``held`` (contract held from this close), ``next`` (the following
    contract), ``p_held``/``p_next`` (their settlements today), ``ret`` (return earned
    today by the position held since yesterday's close), ``dspread`` (today's change in
    P_held - P_next for yesterday's pair, $/unit).
    """
    px = nearby[["c1", "c2", "c3"]].dropna(how="all")
    days = px.index
    exp = expiries.sort_values("expiry").reset_index(drop=True)
    labels = label_nearbys(days, exp, depth=3)
    panel = contract_price_panel(px.set_axis([1, 2, 3], axis=1), labels)
    held = roll_schedule(days, exp, roll_days)
    order = {c: i for i, c in enumerate(exp["contract"])}
    nxt = held.map(lambda c: exp["contract"].iat[order[c] + 1]
                   if c in order and order[c] + 1 < len(exp) else None)

    def price(contracts: pd.Series, on: pd.DatetimeIndex) -> np.ndarray:
        cols = panel.columns.get_indexer(contracts)
        rows = panel.index.get_indexer(on)
        vals = panel.to_numpy(dtype=float)
        return np.where((cols >= 0) & (rows >= 0), vals[rows, np.maximum(cols, 0)], np.nan)

    h_prev, n_prev = held.shift(1), nxt.shift(1)
    today = days
    yday = days.to_series().shift(1)
    p_h_today = price(h_prev, today)
    p_h_yday = price(h_prev, pd.DatetimeIndex(yday.fillna(days[0])))
    p_n_today = price(n_prev, today)
    p_n_yday = price(n_prev, pd.DatetimeIndex(yday.fillna(days[0])))
    ret = p_h_today / p_h_yday - 1.0
    ret[0] = np.nan
    dspread = (p_h_today - p_n_today) - (p_h_yday - p_n_yday)
    dspread[0] = np.nan
    return pd.DataFrame({
        "held": held, "next": nxt,
        "p_held": price(held, today), "p_next": price(nxt, today),
        "ret": ret, "dspread": dspread,
    }, index=days)


class WindowCalc:
    """O(1) window sums of daily returns via cumulative sums (NaN-aware)."""

    def __init__(self, daily: pd.DataFrame):
        self.days = daily.index
        r = daily["ret"].to_numpy(dtype=float)
        self._logc = np.concatenate([[0.0], np.cumsum(np.nan_to_num(np.log1p(r)))])
        self._nanc = np.concatenate([[0], np.cumsum(np.isnan(r))])
        s = daily["dspread"].to_numpy(dtype=float)
        self._sc = np.concatenate([[0.0], np.cumsum(np.nan_to_num(s))])
        self._snan = np.concatenate([[0], np.cumsum(np.isnan(s))])
        self.daily = daily

    def _pos(self, d: pd.Timestamp) -> int:
        i = self.days.get_indexer([d])[0]
        return -1 if pd.isna(d) else i

    def ret(self, a: pd.Timestamp, b: pd.Timestamp) -> float:
        """Compounded held-contract return from the close of a to the close of b."""
        i, j = self._pos(a), self._pos(b)
        if i < 0 or j < 0 or j <= i or self._nanc[j + 1] - self._nanc[i + 1] > 0:
            return float("nan")
        return float(np.expm1(self._logc[j + 1] - self._logc[i + 1]))

    def spread_change(self, a: pd.Timestamp, b: pd.Timestamp) -> float:
        i, j = self._pos(a), self._pos(b)
        if i < 0 or j < 0 or j <= i or self._snan[j + 1] - self._snan[i + 1] > 0:
            return float("nan")
        return float(self._sc[j + 1] - self._sc[i + 1])

    def controls(self, d: pd.Timestamp) -> dict[str, float]:
        """Price-only information known at the close of d (model 1 regressors)."""
        j = self._pos(d)
        nan = float("nan")
        if j < 21:
            return {"mom1": nan, "mom4": nan, "rv": nan, "carry": nan}
        r = self.daily["ret"].to_numpy(dtype=float)[j - 19: j + 1]
        row = self.daily.iloc[j]
        carry = (row["p_held"] - row["p_next"]) / row["p_held"] if row["p_held"] > 0 else nan
        return {
            "mom1": self.ret(self.days[j - 5], d),
            "mom4": self.ret(self.days[j - 20], d),
            "rv": float(np.std(r, ddof=1) * np.sqrt(252)) if not np.isnan(r).any() else nan,
            "carry": float(carry),
        }


def precise_windows(calendar: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """Announcement/drift windows from observed release dates (archive editions)."""
    ev = build_event_table(calendar.assign(reference_week_end=calendar["data_ending"]),
                           trading_days)
    out = ev[["data_ending", "pre_date", "entry_date", "exit_date", "time_source"]].copy()
    out["timing"] = "precise"
    return out.rename(columns={"data_ending": "week"})


def conservative_windows(
    fridays: pd.DatetimeIndex, trading_days: pd.DatetimeIndex, tz: str = DEFAULT_TZ
) -> pd.DataFrame:
    """U2/U4 windows that need only Assumption A (validated in Phase 3)."""
    rows = []
    holiday = holiday_week_flags(pd.Series(fridays)).to_numpy()
    for f, hol in zip(fridays, holiday, strict=True):
        f_close = pd.Timestamp(f).normalize() + pd.Timedelta(hours=14, minutes=31)
        pre = last_settlement_before(f_close.tz_localize(tz), trading_days)
        entry = first_settlement_after(conservative_release_ts(f, 7, "14:29", tz), trading_days)
        nxt_release_earliest = (pd.Timestamp(f).normalize() + pd.Timedelta(days=12)).tz_localize(tz)
        exit_ = last_settlement_before(nxt_release_earliest, trading_days)
        if not (pd.isna(entry) or pd.isna(exit_)) and exit_ <= entry:
            exit_ = pd.NaT
        rows.append({"week": pd.Timestamp(f), "pre_date": pre, "entry_date": entry,
                     "exit_date": exit_, "time_source": "assumption_a",
                     "timing": "conservative", "excluded_holiday_week": bool(hol)})
    out = pd.DataFrame(rows)
    return out[~out["excluded_holiday_week"]].drop(columns="excluded_holiday_week")


def attach_returns(windows: pd.DataFrame, calc: WindowCalc, prefix: str) -> pd.DataFrame:
    """Announcement and drift returns, spread changes, and controls for one market."""
    out = windows.copy()
    out[f"{prefix}_ann"] = [calc.ret(a, b) for a, b in zip(out["pre_date"], out["entry_date"],
                                                           strict=True)]
    out[f"{prefix}_drift"] = [calc.ret(a, b) for a, b in zip(out["entry_date"],
                                                             out["exit_date"], strict=True)]
    out[f"{prefix}_spread_ann"] = [calc.spread_change(a, b) for a, b in
                                   zip(out["pre_date"], out["entry_date"], strict=True)]
    out[f"{prefix}_spread_drift"] = [calc.spread_change(a, b) for a, b in
                                     zip(out["entry_date"], out["exit_date"], strict=True)]
    pre_ctrl = pd.DataFrame([calc.controls(d) for d in out["pre_date"]], index=out.index)
    ent_ctrl = pd.DataFrame([calc.controls(d) for d in out["entry_date"]], index=out.index)
    out = out.join(pre_ctrl.add_prefix(f"{prefix}_pre_")).join(
        ent_ctrl.add_prefix(f"{prefix}_entry_"))
    return out
