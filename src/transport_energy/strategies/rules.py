"""Turn signals into positions. Missing signals always mean "flat"."""

from __future__ import annotations

import numpy as np
import pandas as pd


def threshold_position(signal: pd.Series, threshold: float, size: float = 1.0) -> pd.Series:
    """+size if signal > threshold, -size if signal < -threshold, else 0 (including NaN)."""
    if threshold < 0:
        raise ValueError("threshold must be non-negative")
    s = signal.to_numpy(dtype=float)
    pos = np.where(np.isnan(s), 0.0, np.sign(s) * (np.abs(s) > threshold) * size)
    return pd.Series(pos, index=signal.index, name="position")


def events_to_daily_positions(
    events: pd.DataFrame, event_position: pd.Series, trading_days: pd.DatetimeIndex
) -> pd.Series:
    """Hold each event's position from its entry settlement up to (not past) its exit settlement.

    ``positions[d]`` is held from the close of ``d`` to the next close, so the position is
    set on ``entry_date <= d < exit_date`` and is zero again from ``exit_date``.
    Events without a valid entry or exit are skipped.
    """
    pos = pd.Series(0.0, index=trading_days, name="position")
    for i, ev in events.iterrows():
        if pd.isna(ev["entry_date"]) or pd.isna(ev["exit_date"]):
            continue
        window = (trading_days >= ev["entry_date"]) & (trading_days < ev["exit_date"])
        if (pos[window] != 0).any():
            raise ValueError(f"event {i} overlaps an earlier holding period")
        pos[window] = event_position.loc[i]
    return pos
