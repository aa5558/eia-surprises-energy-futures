import math

import numpy as np
import pandas as pd
import pytest

from transport_energy.config import load_config
from transport_energy.features.transforms import expanding_zscore, lag
from transport_energy.integrity import (
    LockedTestPeriodError,
    development_slice,
    guard_development,
    is_test_unlocked,
)
from transport_energy.strategies.rules import events_to_daily_positions, threshold_position

# ---------- lagging / causal transforms ----------

def test_lag_shifts_forward_and_refuses_negative():
    x = pd.Series([1.0, 2.0, 3.0])
    assert lag(x, 1).tolist()[1:] == [1.0, 2.0]
    with pytest.raises(ValueError, match="future"):
        lag(x, -1)


def test_expanding_zscore_hand_values():
    z = expanding_zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 10.0]), min_periods=2)
    assert z.iloc[:2].isna().all()
    assert z.iloc[2] == pytest.approx(1.5 / math.sqrt(0.5))
    assert z.iloc[3] == pytest.approx(2.0)
    assert z.iloc[4] == pytest.approx(7.5 / np.std([1, 2, 3, 4], ddof=1))


def test_expanding_zscore_ignores_future_values():
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 10.0])
    y = x.copy()
    y.iloc[4] = 1e6
    pd.testing.assert_series_equal(
        expanding_zscore(x, 2).iloc[:4], expanding_zscore(y, 2).iloc[:4]
    )


def test_expanding_zscore_with_missing_observation():
    z = expanding_zscore(pd.Series([1.0, np.nan, 3.0, 5.0]), min_periods=2)
    assert pd.isna(z.iloc[1]) and pd.isna(z.iloc[2])  # only one past value before index 2
    assert z.iloc[3] == pytest.approx((5 - 2) / np.std([1, 3], ddof=1))


# ---------- position rules ----------

def test_threshold_position_and_nan_is_flat():
    s = pd.Series([0.2, 1.5, -2.0, np.nan, -0.4])
    assert threshold_position(s, 1.0, size=2).tolist() == [0, 2, -2, 0, 0]


def test_events_to_daily_positions_window(make_calendar):
    days = make_calendar("2024-01-08", "2024-01-19")
    ev = pd.DataFrame({
        "entry_date": pd.to_datetime(["2024-01-10", "2024-01-17"]),
        "exit_date": pd.to_datetime(["2024-01-16", pd.NaT]),
    })
    pos = events_to_daily_positions(ev, pd.Series([1.0, -1.0]), days)
    held = pos[pos != 0].index
    assert held.min() == pd.Timestamp("2024-01-10")
    assert held.max() == pd.Timestamp("2024-01-15")  # flat from the exit settlement
    assert (pos.loc["2024-01-17":] == 0).all()        # no exit date -> no trade


# ---------- test-period lock ----------

def _series(start, end):
    idx = pd.date_range(start, end, freq="W-WED")
    return pd.Series(1.0, index=idx)


def test_guard_allows_development_data():
    s = _series("2010-01-01", "2016-12-28")
    assert guard_development(s, "2017-01-01", env={}, tags=[]) is s


def test_guard_blocks_test_period_data():
    with pytest.raises(LockedTestPeriodError):
        guard_development(_series("2016-06-01", "2017-03-01"), "2017-01-01", env={}, tags=[])


def test_guard_handles_tz_aware_index():
    s = _series("2016-06-01", "2017-03-01").tz_localize("America/New_York")
    with pytest.raises(LockedTestPeriodError):
        guard_development(s, "2017-01-01", env={}, tags=[])


def test_unlock_requires_existing_freeze_tag():
    env = {"TEQ_UNLOCK_TEST": "spec-freeze-v1"}
    assert not is_test_unlocked({}, tags=["spec-freeze-v1"])
    assert not is_test_unlocked(env, tags=[])                       # tag must exist
    assert not is_test_unlocked({"TEQ_UNLOCK_TEST": "v1"}, ["v1"])  # wrong prefix
    assert is_test_unlocked(env, tags=["spec-freeze-v1"])
    s = _series("2016-06-01", "2017-03-01")
    assert guard_development(s, "2017-01-01", env=env, tags=["spec-freeze-v1"]) is s


def test_development_slice():
    s = _series("2016-06-01", "2017-03-01")
    assert development_slice(s, "2017-01-01").index.max() < pd.Timestamp("2017-01-01")


def test_config_splits_are_ordered():
    sp = load_config("research")["splits"]
    assert (pd.Timestamp(sp["development_start"]) < pd.Timestamp(sp["precise_timing_start"])
            < pd.Timestamp(sp["development_end"]) < pd.Timestamp(sp["test_start"]))
