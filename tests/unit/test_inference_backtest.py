"""Inference helpers and the event backtester on synthetic data with known answers."""

import numpy as np
import pandas as pd
import pytest

from transport_energy.backtesting import event_backtest as eb
from transport_energy.evaluation import inference as inf


def test_ols_hac_recovers_slope():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=2000))
    y = 0.5 * x + pd.Series(rng.normal(size=2000))
    res = inf.ols_hac(y, x.to_frame("x"))
    assert res.params["x"] == pytest.approx(0.5, abs=0.05)
    assert res.pvalues["x"] < 1e-10 and res.lags >= 1


def test_nw_lags_cover_overlap():
    assert inf.nw_lags(500, horizon=4) >= 3


def test_adjust_pvalues():
    out = inf.adjust_pvalues(pd.Series([0.01, 0.04, 0.03, np.nan]))
    assert out["p_holm"].iloc[0] == pytest.approx(0.03)
    assert out["p_bh"].iloc[1] == pytest.approx(0.04)
    assert np.isnan(out["p_holm"].iloc[3])


def test_oos_r2_and_clark_west():
    rng = np.random.default_rng(1)
    x = rng.normal(size=3000)
    y = 0.3 * x + rng.normal(size=3000)
    assert inf.oos_r2(y, 0.3 * x, np.zeros_like(y)) > 0.05
    cw = inf.clark_west(y, np.zeros_like(y), 0.3 * x)
    assert cw["p_one_sided"] < 1e-6
    noise = inf.clark_west(y, np.zeros_like(y), rng.normal(scale=0.01, size=3000))
    assert noise["p_one_sided"] > 0.01


def test_diebold_mariano_sign():
    rng = np.random.default_rng(2)
    e_big, e_small = rng.normal(scale=2, size=2000), rng.normal(scale=1, size=2000)
    assert inf.diebold_mariano(e_big, e_small)["dm_t"] > 5


def test_stationary_bootstrap_indices_valid():
    rng = np.random.default_rng(3)
    idx = inf.stationary_bootstrap_indices(100, 10, rng)
    assert idx.min() >= 0 and idx.max() < 100
    # mostly consecutive: about 1 restart per 10 steps
    assert np.mean(np.diff(idx) == 1) > 0.8


def test_bootstrap_sharpe_ci_contains_truth():
    rng = np.random.default_rng(4)
    r = rng.normal(0.1 / 52, 0.1 / np.sqrt(52), size=1500)
    ci = inf.bootstrap_sharpe_ci(r, 52, reps=500)
    assert ci["ci_low"] < 1.0 < ci["ci_high"]


def test_deflated_sharpe_penalizes_trials():
    rng = np.random.default_rng(5)
    r = rng.normal(0.002, 0.02, size=500)
    one = inf.deflated_sharpe(r, n_trials=1, var_trials=0.0)
    many = inf.deflated_sharpe(r, n_trials=100, var_trials=0.05 ** 2)
    assert many["dsr"] < one["dsr"]


def test_spa_rejects_only_with_real_edge():
    rng = np.random.default_rng(6)
    null = pd.DataFrame(rng.normal(0, 1, size=(500, 5)))
    assert inf.spa_test(null, reps=500)["p_consistent"] > 0.05
    edge = null.copy()
    edge[2] += 0.4
    res = inf.spa_test(edge, reps=500)
    assert res["p_consistent"] < 0.01 and res["best"] == "2"


def _toy():
    days = pd.bdate_range("2020-01-01", periods=40)
    t = np.arange(40, dtype=float)
    p = 50 + 0.5 * t                               # one contract, rising 0.5/day
    daily = pd.DataFrame({"held": "A", "next": "B", "p_held": p, "p_next": p + 1,
                          "ret": np.r_[np.nan, p[1:] / p[:-1] - 1], "dspread": 0.0},
                         index=days)
    panel = pd.DataFrame({"A": p}, index=days)
    events = pd.DataFrame({"entry_date": [days[25], days[30]],
                           "exit_date": [days[28], days[34]]})
    return days, daily, panel, events


def test_threshold_sizing_and_cap():
    _, daily, _, events = _toy()
    q = eb.size_positions(pd.Series([0.4, -2.0]), pd.Series([3.2, 3.2]), "threshold", k=1.0)
    assert list(q) == [0.0, -3.0]
    q = eb.size_positions(pd.Series([5.0, -0.5]), pd.Series([3.0, 3.0]), "vol_scaled",
                          direction=-1)
    assert list(q) == [-6.0, 2.0]
    capped = eb.cap_notional(pd.Series([100.0, -100.0]), events, daily, 1000,
                             eb.SizingConfig(capital=1e6))
    assert capped.abs().max() == np.floor(2e6 / (daily["p_held"].iloc[25] * 1000))


def test_run_backtest_pnl_and_costs():
    days, daily, panel, events = _toy()
    res = eb.run_backtest(events, pd.Series([2.0, -1.0]), daily, panel, 1000.0,
                          cost_per_side=10.0, capital=1e6)
    # event 1: long 2 for 3 days of +0.5 -> 2 * 1.5 * 1000 = 3000 gross, 4 sides of cost
    assert res.trades["net_pnl"].iloc[0] == pytest.approx(3000 - 40)
    # event 2: short 1 for 4 days -> -2000 gross, 2 sides of cost
    assert res.trades["net_pnl"].iloc[1] == pytest.approx(-2000 - 20)
    assert res.weekly["net_pnl"].sum() == pytest.approx(3000 - 40 - 2000 - 20)
    s = eb.summarize(res, 1e6)
    assert s["trades"] == 2 and s["gross_sharpe"] > s["net_sharpe"] - 1e-9


def test_vol_units_targets_dollar_risk():
    _, daily, _, events = _toy()
    cfg = eb.SizingConfig(capital=1e6, vol_lookback=10)
    n = eb.vol_units(events, daily, 1000.0, cfg)
    vol = daily["ret"].rolling(10, min_periods=5).std().iloc[25]
    expect = cfg.weekly_dollar_vol / (vol * np.sqrt(3) * daily["p_held"].iloc[25] * 1000)
    assert n.iloc[0] == pytest.approx(expect)
