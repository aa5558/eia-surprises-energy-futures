import math

import pandas as pd
import pytest

from transport_energy.evaluation import metrics as m

R = pd.Series([0.01, -0.02, 0.03, 0.00])  # mean 0.005, sample var 4.333e-4


def test_sharpe_weekly_matches_hand_calculation():
    # (0.005 / sqrt(1.3e-3 / 3))^2 * 52 = 3  ->  Sharpe = sqrt(3)
    assert m.sharpe_ratio(R, periods_per_year=52) == pytest.approx(math.sqrt(3))


def test_annualization_depends_on_frequency():
    weekly = m.sharpe_ratio(R, periods_per_year=52)
    daily = m.sharpe_ratio(R, periods_per_year=252)
    assert daily / weekly == pytest.approx(math.sqrt(252 / 52))


def test_periods_per_year_is_required_and_positive():
    with pytest.raises(TypeError):
        m.sharpe_ratio(R)  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        m.sharpe_ratio(R, periods_per_year=0)


def test_sortino_uses_downside_deviation():
    # downside deviation = sqrt(mean([0, 0.02^2, 0, 0])) = 0.01 -> 0.5 * sqrt(52) = sqrt(13)
    assert m.sortino_ratio(R, periods_per_year=52) == pytest.approx(math.sqrt(13))


def test_annualized_mean_and_vol():
    assert m.annualized_mean(R, periods_per_year=52) == pytest.approx(0.26)
    assert m.annualized_volatility(R, periods_per_year=52) == pytest.approx(
        math.sqrt(1.3e-3 / 3 * 52)
    )


def test_zero_volatility_gives_nan_not_inf():
    assert math.isnan(m.sharpe_ratio(pd.Series([0.01, 0.01, 0.01]), periods_per_year=52))


def test_max_drawdown_on_fixed_capital_equity():
    eq = m.equity_curve(R)  # 1.01, 0.99, 1.02, 1.02
    assert eq.tolist() == pytest.approx([1.01, 0.99, 1.02, 1.02])
    assert m.max_drawdown(eq) == pytest.approx(0.99 / 1.01 - 1)


def test_pnl_to_returns_requires_positive_capital():
    assert m.pnl_to_returns(pd.Series([1000.0]), 1e6).iloc[0] == pytest.approx(0.001)
    with pytest.raises(ValueError):
        m.pnl_to_returns(pd.Series([1.0]), 0)


def test_trade_statistics():
    s = m.trade_statistics(pd.Series([100.0, -50.0, 200.0, -25.0, 0.0]))
    assert s["n_trades"] == 5
    assert s["win_rate"] == pytest.approx(0.4)
    assert s["avg_gain"] == pytest.approx(150.0)
    assert s["avg_loss"] == pytest.approx(-37.5)
    assert s["profit_factor"] == pytest.approx(4.0)


def test_trade_statistics_edge_cases():
    assert m.trade_statistics(pd.Series([], dtype=float))["n_trades"] == 0
    assert m.trade_statistics(pd.Series([10.0, 5.0]))["profit_factor"] == math.inf
