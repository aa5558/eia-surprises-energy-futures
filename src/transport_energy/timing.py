"""Information timing: when does a release become usable, and which settlements bracket it?

The economic observation date (the Friday that ends the EIA reference week) is
NOT the date the number is known. Every function here works with tz-aware
*release timestamps* and *settlement timestamps*. The core rule is strict
inequality: a release at time ``R`` can only inform a trade at a settlement
time ``S`` with ``S > R``.
"""

from __future__ import annotations

import pandas as pd

DEFAULT_TZ = "America/New_York"
DEFAULT_SETTLE = "14:30"


def _require_tz(ts: pd.Timestamp | pd.DatetimeIndex, name: str) -> None:
    if getattr(ts, "tz", None) is None:
        raise ValueError(f"{name} must be timezone-aware; naive times hide timing errors")


def settlement_timestamps(
    trading_days: pd.DatetimeIndex, settle_time: str = DEFAULT_SETTLE, tz: str = DEFAULT_TZ
) -> pd.DatetimeIndex:
    """Map trading dates (naive, midnight) to their settlement instants in exchange time."""
    hours, minutes = (int(x) for x in settle_time.split(":"))
    days = pd.DatetimeIndex(trading_days).normalize()
    return (days + pd.Timedelta(hours=hours, minutes=minutes)).tz_localize(tz)


def first_settlement_after(
    release_ts: pd.Timestamp,
    trading_days: pd.DatetimeIndex,
    settle_time: str = DEFAULT_SETTLE,
    tz: str = DEFAULT_TZ,
) -> pd.Timestamp:
    """First trading date whose settlement is strictly after ``release_ts`` (NaT if none)."""
    _require_tz(release_ts, "release_ts")
    settles = settlement_timestamps(trading_days, settle_time, tz)
    i = settles.searchsorted(release_ts, side="right")
    return pd.Timestamp(trading_days[i]) if i < len(trading_days) else pd.NaT


def last_settlement_before(
    ts: pd.Timestamp,
    trading_days: pd.DatetimeIndex,
    settle_time: str = DEFAULT_SETTLE,
    tz: str = DEFAULT_TZ,
) -> pd.Timestamp:
    """Last trading date whose settlement is strictly before ``ts`` (NaT if none)."""
    _require_tz(ts, "ts")
    settles = settlement_timestamps(trading_days, settle_time, tz)
    i = settles.searchsorted(ts, side="left") - 1
    return pd.Timestamp(trading_days[i]) if i >= 0 else pd.NaT


def conservative_release_ts(
    reference_week_end: pd.Timestamp,
    days_after: int | None,
    assumed_by: str = "14:29",
    tz: str = DEFAULT_TZ,
) -> pd.Timestamp:
    """Latest assumed release time when no archived release date exists (pre-Aug 2011).

    Assumption A (docs/02_*): the report for reference week ``F`` was public by
    ``assumed_by`` on day ``F + days_after``. With ``days_after=7`` and ``"14:29"`` the first
    usable settlement is Friday ``F+7``. ``days_after=None`` means the assumption has not yet
    been validated against the 2011+ archive, and the function refuses.
    """
    if days_after is None:
        raise ValueError("release-window assumption not calibrated (validate it in Phase 3)")
    hours, minutes = (int(x) for x in assumed_by.split(":"))
    day = pd.Timestamp(reference_week_end).normalize() + pd.Timedelta(days=days_after)
    return (day + pd.Timedelta(hours=hours, minutes=minutes)).tz_localize(tz)


def build_event_table(
    releases: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    settle_time: str = DEFAULT_SETTLE,
    tz: str = DEFAULT_TZ,
) -> pd.DataFrame:
    """One row per release with the settlements that bracket it.

    Parameters
    ----------
    releases : columns ``reference_week_end`` and tz-aware ``release_ts``.

    Returns columns
    ---------------
    pre_date   : last settlement before the release (start of the announcement window).
    entry_date : first settlement after the release (end of the announcement window
                 and earliest executable entry with daily data).
    exit_date  : last settlement before the NEXT release, so a holding period never
                 contains the next announcement. NaT for the final release.
    """
    ev = releases.sort_values("release_ts").reset_index(drop=True).copy()
    _require_tz(pd.DatetimeIndex(ev["release_ts"]), "release_ts")
    ev["next_release_ts"] = ev["release_ts"].shift(-1)
    ev["pre_date"] = [
        last_settlement_before(r, trading_days, settle_time, tz) for r in ev["release_ts"]
    ]
    ev["entry_date"] = [
        first_settlement_after(r, trading_days, settle_time, tz) for r in ev["release_ts"]
    ]
    ev["exit_date"] = [
        pd.NaT if pd.isna(n) else last_settlement_before(n, trading_days, settle_time, tz)
        for n in ev["next_release_ts"]
    ]
    # A holding period must have positive length; otherwise mark it untradable.
    bad = ev["exit_date"].notna() & (ev["exit_date"] <= ev["entry_date"])
    ev.loc[bad, "exit_date"] = pd.NaT
    return ev


def align_asof(decision_ts: pd.Series, available: pd.DataFrame) -> pd.DataFrame:
    """For each decision time, attach the latest row with ``available_at < decision_ts``.

    ``available`` must have a tz-aware ``available_at`` column (the release time of
    each observation). The strict inequality means a value released at exactly the
    decision instant is NOT used.
    """
    left = pd.DataFrame({"decision_ts": pd.DatetimeIndex(decision_ts)})
    _require_tz(pd.DatetimeIndex(left["decision_ts"]), "decision_ts")
    _require_tz(pd.DatetimeIndex(available["available_at"]), "available_at")
    order = left["decision_ts"].argsort()
    merged = pd.merge_asof(
        left.iloc[order],
        available.sort_values("available_at"),
        left_on="decision_ts",
        right_on="available_at",
        direction="backward",
        allow_exact_matches=False,
    )
    merged.index = left.index[order]
    return merged.sort_index()
