"""Automated data-quality counts.

Counts only, never plots or return statistics, so they can run on all dates without
looking at the locked test period's outcomes (doc 02, integrity protocol item 2).
Every count is split into development (< test start) and test (>= test start).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from transport_energy.integrity import default_test_start


def _period(index: pd.DatetimeIndex, test_start: pd.Timestamp) -> np.ndarray:
    return np.where(index < test_start, "development", "test")


def weekly_quality(weekly: pd.DataFrame, test_start: pd.Timestamp | None = None) -> pd.DataFrame:
    """Per series and period: coverage, gaps in the Friday sequence, bad values."""
    start = pd.Timestamp(test_start or default_test_start())
    rows = []
    for name in weekly.columns:
        s = weekly[name].dropna()
        full = pd.date_range(s.index[0], s.index[-1], freq="W-FRI")
        missing = full.difference(s.index)
        for period in ("development", "test"):
            mask = _period(s.index, start) == period
            sp = s[mask]
            miss_p = missing[_period(missing, start) == period]
            rows.append({
                "series": name, "period": period, "n_obs": int(mask.sum()),
                "first": sp.index.min(), "last": sp.index.max(),
                "missing_fridays": len(miss_p),
                "non_friday_dates": int((sp.index.dayofweek != 4).sum()),
                "non_positive_values": int((sp <= 0).sum()),
                "duplicate_dates": int(sp.index.duplicated().sum()),
            })
    return pd.DataFrame(rows)


def futures_quality(
    prices: pd.DataFrame, business_days: pd.DatetimeIndex, test_start: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Per nearby series and period: coverage against the scheduled exchange calendar."""
    start = pd.Timestamp(test_start or default_test_start())
    rows = []
    for name in prices.columns:
        s = prices[name].dropna()
        cal = business_days[(business_days >= s.index[0]) & (business_days <= s.index[-1])]
        not_in_data = cal.difference(s.index)
        not_business = s.index.difference(business_days)
        for period in ("development", "test"):
            mask = _period(s.index, start) == period
            rows.append({
                "series": name, "period": period, "n_obs": int(mask.sum()),
                "first": s.index[mask].min(), "last": s.index[mask].max(),
                "business_days_missing": int((_period(not_in_data, start) == period).sum()),
                "dates_outside_business_calendar":
                    int((_period(not_business, start) == period).sum()),
                "non_positive_values": int((s[mask] <= 0).sum()),
            })
    return pd.DataFrame(rows)


def partial_rows(prices: pd.DataFrame) -> pd.DataFrame:
    """Dates where some but not all nearby columns have a settlement (dates only)."""
    has = prices.notna()
    part = has.any(axis=1) & ~has.all(axis=1)
    return has[part].astype(int)
