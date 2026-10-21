"""Generic transforms that are causal by construction (they only look backward)."""

from __future__ import annotations

import pandas as pd


def lag(x: pd.Series | pd.DataFrame, periods: int = 1) -> pd.Series | pd.DataFrame:
    """Shift observations forward in time. Negative lags would pull in future data, so refuse."""
    if periods < 0:
        raise ValueError("negative lag uses future observations")
    return x.shift(periods)


def expanding_zscore(x: pd.Series, min_periods: int) -> pd.Series:
    """z_t = (x_t - mean(x_<t)) / std(x_<t), using only observations strictly before t.

    Missing values are skipped when computing the statistics and stay missing in the output.
    """
    past = x.shift(1)
    mean = past.expanding(min_periods=min_periods).mean()
    std = past.expanding(min_periods=min_periods).std(ddof=1)
    return (x - mean) / std
