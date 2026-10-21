import numpy as np
import pandas as pd
import pytest

from transport_energy.backtesting.costs import CostModel
from transport_energy.backtesting.pnl import contracts_traded, futures_pnl
from transport_energy.config import load_config

DAYS = pd.date_range("2015-03-02", periods=4, freq="B")


# ---------- transaction costs ----------

@pytest.mark.parametrize(
    ("root", "scenario", "expected"),
    [("CL", "base", 12.5), ("RB", "base", 6.7), ("CL", "stress", 45.0), ("RB", "optimistic", 3.6)],
)
def test_cost_per_contract_side_from_config(root, scenario, expected):
    cm = CostModel.from_config(load_config("research"), root, scenario)
    assert cm.per_contract_side == pytest.approx(expected)


def test_cost_scales_with_absolute_contracts():
    cm = CostModel(ticks=1, tick_size=0.01, multiplier=1000, commission_usd=2.5)
    assert cm.cost(-3) == pytest.approx(37.5)


# ---------- P&L ----------

def test_single_contract_long_pnl():
    prices = pd.DataFrame({"A": [50.0, 51.0, 49.5, 52.0]}, index=DAYS)
    pos = pd.Series([1.0, 1.0, 1.0, 0.0], index=DAYS)
    held = pd.Series(["A"] * 4, index=DAYS)
    out = futures_pnl(pos, held, prices, multiplier=1000)
    assert out["gross_pnl"].tolist() == pytest.approx([0, 1000, -1500, 2500])
    assert out["contracts_traded"].tolist() == [1, 0, 0, 1]


def test_short_position_sign():
    prices = pd.DataFrame({"A": [50.0, 51.0]}, index=DAYS[:2])
    out = futures_pnl(
        pd.Series([-2.0, -2.0], index=DAYS[:2]), pd.Series(["A", "A"], index=DAYS[:2]),
        prices, multiplier=1000,
    )
    assert out["gross_pnl"].iloc[1] == pytest.approx(-2000)


def test_roll_does_not_create_artificial_return():
    # A expires; we roll into B at the close of day 2. B trades at a 6-dollar premium.
    prices = pd.DataFrame(
        {"A": [50.0, 51.0, 52.0, np.nan], "B": [55.0, 56.0, 58.0, 57.0]}, index=DAYS
    )
    held = pd.Series(["A", "A", "B", "B"], index=DAYS)
    pos = pd.Series([1.0] * 4, index=DAYS)
    out = futures_pnl(pos, held, prices, multiplier=1000, cost_per_contract_side=12.5)
    assert out["gross_pnl"].tolist() == pytest.approx([0, 1000, 1000, -1000])
    # A naively spliced "nearby" series 50, 51, 58, 57 would book +7000 instead of +1000.
    assert out["gross_pnl"].sum() == pytest.approx(1000)
    assert out["contracts_traded"].tolist() == [1, 0, 2, 0]  # roll = close A + open B
    assert out["costs"].sum() == pytest.approx(3 * 12.5)
    assert out["net_pnl"].sum() == pytest.approx(1000 - 37.5)


def test_negative_prices_are_handled_in_dollars():
    days = DAYS[:3]
    prices = pd.DataFrame({"A": [10.0, -37.63, 5.0]}, index=days)
    out = futures_pnl(
        pd.Series([1.0, 1.0, 1.0], index=days), pd.Series(["A"] * 3, index=days),
        prices, multiplier=1000,
    )
    assert out["gross_pnl"].tolist() == pytest.approx([0, -47630, 42630])


def test_missing_price_for_open_position_raises():
    prices = pd.DataFrame({"A": [50.0, np.nan, 52.0, 53.0]}, index=DAYS)
    with pytest.raises(ValueError, match="missing settlement"):
        futures_pnl(pd.Series([1.0] * 4, index=DAYS), pd.Series(["A"] * 4, index=DAYS),
                    prices, multiplier=1000)


def test_missing_price_while_flat_is_fine():
    prices = pd.DataFrame({"A": [50.0, np.nan, 52.0, 53.0]}, index=DAYS)
    out = futures_pnl(pd.Series([0.0, 0.0, 1.0, 1.0], index=DAYS),
                      pd.Series(["A"] * 4, index=DAYS), prices, multiplier=1000)
    assert out["gross_pnl"].tolist() == pytest.approx([0, 0, 0, 1000])


def test_nan_positions_rejected():
    prices = pd.DataFrame({"A": [50.0] * 4}, index=DAYS)
    with pytest.raises(ValueError, match="NaN"):
        futures_pnl(pd.Series([1.0, np.nan, 1.0, 1.0], index=DAYS),
                    pd.Series(["A"] * 4, index=DAYS), prices, multiplier=1000)


def test_turnover_counts_flips_and_rolls():
    pos = pd.Series([1.0, -1.0, -1.0, 0.0], index=DAYS)
    held = pd.Series(["A", "A", "B", "B"], index=DAYS)
    # open 1; flip long->short = 2; roll short A->short B = 2; close = 1
    assert contracts_traded(pos, held).tolist() == [1, 2, 2, 1]
