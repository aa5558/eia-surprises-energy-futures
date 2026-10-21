"""Surprise models and event returns: causality and arithmetic on synthetic data."""

import numpy as np
import pandas as pd
import pytest

from transport_energy.features import events as fe
from transport_energy.features import surprises as su


def weekly_series(n=520, seed=1):
    idx = pd.date_range("2000-01-07", periods=n, freq="W-FRI")
    rng = np.random.default_rng(seed)
    season = 300 * np.sin(2 * np.pi * idx.dayofyear / 365.25)
    return pd.Series(8000 + season + rng.normal(0, 50, n), index=idx)


def test_five_year_mean_uses_same_week_prior_years():
    y = pd.Series(np.arange(300, dtype=float),
                  index=pd.date_range("2000-01-07", periods=300, freq="W-FRI"))
    f = su.forecast_five_year(y)
    t = 280
    assert f.iloc[t] == pytest.approx(np.mean([t - 52 * k for k in range(1, 6)]))
    assert f.iloc[:260].isna().all()


@pytest.mark.parametrize("model", su.MODELS)
def test_expectations_are_causal(model):
    y = weekly_series()
    base = su.expectations(y)[model]
    cut = 400
    y2 = y.copy()
    y2.iloc[cut:] += 1e4                      # rewrite the future
    alt = su.expectations(y2)[model]
    # forecasts up to and including week `cut` cannot see weeks >= cut
    pd.testing.assert_series_equal(base.iloc[: cut + 1], alt.iloc[: cut + 1])
    assert not np.allclose(base.iloc[cut + 1:].dropna(), alt.iloc[cut + 1:].dropna())


def test_seasonal_model_beats_naive_on_seasonal_data():
    y = weekly_series(n=700)
    f = su.expectations(y).iloc[400:]
    err = {m: np.sqrt(np.mean((y.iloc[400:] - f[m]) ** 2)) for m in su.MODELS}
    assert err["seasonal"] < 70 and err["seasonal"] < err["five_year"]


def test_holiday_dummy_marks_week_containing_holiday():
    fridays = pd.date_range("2015-11-20", periods=3, freq="W-FRI")
    d = su.holiday_dummies(fridays)
    # Thanksgiving 2015-11-26 lies in the week ending Friday 2015-11-27
    assert d.loc["2015-11-27", "Thanksgiving Day"] == 1.0
    assert d["Thanksgiving Day"].sum() == 1.0


def test_standardize_uses_past_only():
    s = pd.Series(np.r_[np.ones(60), 100.0], index=pd.RangeIndex(61)) * \
        np.r_[np.tile([1, -1], 30), 1]
    z = su.standardize(s, min_periods=52)
    assert z.iloc[-1] == pytest.approx(100.0 / s.iloc[:-1].std(ddof=1))


def test_non_friday_dates_rejected():
    s = pd.Series([1.0, 2.0], index=pd.DatetimeIndex(["2020-01-03", "2020-01-08"]))
    with pytest.raises(ValueError, match="non-Friday"):
        su.regular_weekly(s)


def _market(days, roll_days=2):
    """Two contracts: A (expires day 10) at 100 + t, B at 200 + 2t, C at 300."""
    t = np.arange(len(days), dtype=float)
    exp = pd.DataFrame({"contract": ["A", "B", "C", "D"],
                        "expiry": [days[10], days[-1] + pd.Timedelta(days=40),
                                   days[-1] + pd.Timedelta(days=70),
                                   days[-1] + pd.Timedelta(days=100)]})
    a, b, c, d = 100 + t, 200 + 2 * t, 300 + 0 * t, 400 + 0 * t
    after = np.arange(len(days)) > 10
    nearby = pd.DataFrame({"c1": np.where(after, b, a), "c2": np.where(after, c, b),
                           "c3": np.where(after, d, c)}, index=days)
    return fe.contract_daily(nearby, exp, roll_days), exp


def test_contract_daily_never_books_roll_gap():
    days = pd.bdate_range("2020-01-01", periods=30)
    daily, _ = _market(days)
    # held: A until its roll date (day 8), then B. Day-9 return is B's own move.
    assert daily["held"].iloc[7] == "A" and daily["held"].iloc[8] == "B"
    assert daily["ret"].iloc[8] == pytest.approx((100 + 8) / (100 + 7) - 1)    # A's move
    assert daily["ret"].iloc[9] == pytest.approx((200 + 18) / (200 + 16) - 1)  # B's move
    assert (daily["ret"].iloc[1:].abs() < 0.02).all()                            # no 2x jump
    # spread A-B changes by -1 per day while A is held
    assert daily["dspread"].iloc[5] == pytest.approx(-1.0)


def test_window_return_compounds_and_propagates_nan():
    days = pd.bdate_range("2020-01-01", periods=30)
    daily, _ = _market(days)
    calc = fe.WindowCalc(daily)
    r = calc.ret(days[12], days[15])
    assert r == pytest.approx((200 + 30) / (200 + 24) - 1)
    daily.iloc[14, daily.columns.get_loc("ret")] = np.nan
    assert np.isnan(fe.WindowCalc(daily).ret(days[12], days[15]))
    assert np.isnan(calc.ret(days[15], days[12]))


def test_conservative_windows_and_holiday_exclusion():
    days = pd.bdate_range("2004-06-01", "2004-08-31")
    fridays = pd.DatetimeIndex(["2004-06-04", "2004-07-02", "2004-07-09"])
    w = fe.conservative_windows(fridays, days).set_index("week")
    # July 4th 2004 was a Sunday, observed Mon 5 July = F+3 for F = 2 July
    assert pd.Timestamp("2004-07-02") not in w.index
    row = w.loc["2004-06-04"]
    assert row["pre_date"] == pd.Timestamp("2004-06-04")
    assert row["entry_date"] == pd.Timestamp("2004-06-11")   # Friday F+7 settlement
    assert row["exit_date"] == pd.Timestamp("2004-06-15")    # Tuesday F+11
