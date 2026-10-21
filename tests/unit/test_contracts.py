import pandas as pd
import pytest

from transport_energy.backtesting.contracts import (
    cl_last_trade_date,
    contract_id,
    contract_price_panel,
    expiry_table,
    label_nearbys,
    rb_last_trade_date,
    roll_schedule,
)


def test_contract_id():
    assert contract_id("CL", 2020, 5) == "CLK2020"
    assert contract_id("RB", 2021, 12) == "RBZ2021"


def test_cl_may_2020_expiry(make_calendar):
    # 25 Apr 2020 was a Saturday -> 3 trading days before Fri 24 Apr = Tue 21 Apr.
    # (The -$37.63 settlement on 20 Apr 2020 was the day before this contract expired.)
    days = make_calendar("2020-01-01", "2020-12-31", holidays=["2020-04-10"])
    assert cl_last_trade_date(2020, 5, days) == pd.Timestamp("2020-04-21")


def test_cl_rule_when_25th_is_a_trading_day(make_calendar):
    days = make_calendar("2021-01-01", "2021-12-31")
    # 25 Jun 2021 is a Friday -> three trading days earlier is Tue 22 Jun.
    assert cl_last_trade_date(2021, 7, days) == pd.Timestamp("2021-06-22")


def test_cl_rule_skips_holidays(make_calendar):
    days = make_calendar("2021-01-01", "2021-12-31", holidays=["2021-06-23"])
    assert cl_last_trade_date(2021, 7, days) == pd.Timestamp("2021-06-21")


def test_cl_january_contract_uses_previous_december(make_calendar):
    days = make_calendar("2020-06-01", "2021-06-30")
    assert cl_last_trade_date(2021, 1, days).month == 12


def test_rb_last_business_day_of_prior_month(make_calendar):
    days = make_calendar("2021-01-01", "2021-12-31")
    assert rb_last_trade_date(2021, 11, days) == pd.Timestamp("2021-10-29")  # 31 Oct = Sunday
    holiday = make_calendar("2021-01-01", "2021-12-31", holidays=["2021-10-29"])
    assert rb_last_trade_date(2021, 11, holiday) == pd.Timestamp("2021-10-28")


def test_outside_calendar_raises(make_calendar):
    days = make_calendar("2021-03-01", "2021-12-31")
    with pytest.raises(ValueError):
        cl_last_trade_date(2021, 2, days)


def test_expiry_table_is_monthly_and_sorted(make_calendar):
    days = make_calendar("2020-01-01", "2020-12-31")
    tab = expiry_table("CL", "cl", days)
    assert tab["expiry"].is_monotonic_increasing
    assert len(tab) == 12  # contracts Feb 2020 ... Jan 2021 expire inside 2020
    assert tab["contract"].iloc[0] == "CLG2020"


def _toy_expiries():
    return pd.DataFrame(
        {"contract": ["X1", "X2", "X3"],
         "expiry": pd.to_datetime(["2015-01-07", "2015-01-14", "2015-01-21"])}
    )


def test_nearby_labels_switch_the_day_after_expiry(make_calendar):
    days = make_calendar("2015-01-05", "2015-01-16")
    lab = label_nearbys(days, _toy_expiries(), depth=2)
    assert lab.loc["2015-01-07", 1] == "X1"  # still trades on expiry day
    assert lab.loc["2015-01-08", 1] == "X2"
    assert lab.loc["2015-01-08", 2] == "X3"


def test_roll_schedule_rolls_n_days_before_expiry(make_calendar):
    days = make_calendar("2015-01-05", "2015-01-16")
    held = roll_schedule(days, _toy_expiries(), business_days_before=2)
    # X1 expires Wed 7 Jan -> roll at the close of Mon 5 Jan.
    assert held.loc["2015-01-05"] == "X2"
    # X2 expires Wed 14 Jan -> hold X2 through Fri 9 Jan, roll at close of Mon 12 Jan.
    assert held.loc["2015-01-09"] == "X2"
    assert held.loc["2015-01-12"] == "X3"
    with pytest.raises(ValueError):
        roll_schedule(days, _toy_expiries(), business_days_before=0)


def test_price_panel_reconstructs_contract_prices(make_calendar):
    days = make_calendar("2015-01-05", "2015-01-09")
    lab = label_nearbys(days, _toy_expiries(), depth=2)
    true = pd.DataFrame(
        # X1 has expired by 8 Jan; X3 only becomes nearby 2 on 8 Jan.
        {"X1": [50, 51, 52, None, None], "X2": [53, 54, 55, 56, 57],
         "X3": [None, None, None, 61, 62]},
        index=days, dtype=float,
    )
    nearby = pd.DataFrame(
        {k: [true.at[d, lab.at[d, k]] for d in days] for k in (1, 2)}, index=days
    )
    panel = contract_price_panel(nearby, lab)
    pd.testing.assert_frame_equal(
        panel.reindex(columns=true.columns), true, check_names=False, check_freq=False
    )


def test_price_panel_detects_conflicts(make_calendar):
    days = make_calendar("2015-01-05", "2015-01-06")
    labels = pd.DataFrame({1: ["X1", "X1"], 2: ["X1", "X2"]}, index=days)
    nearby = pd.DataFrame({1: [50.0, 51.0], 2: [99.0, 52.0]}, index=days)
    with pytest.raises(ValueError, match="conflicting"):
        contract_price_panel(nearby, labels)
