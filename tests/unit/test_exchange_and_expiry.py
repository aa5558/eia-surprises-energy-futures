"""Exchange calendar, documented expiries and the settlement diagnostic. Synthetic data."""

import numpy as np
import pandas as pd
import pytest

from transport_energy.backtesting.contracts import label_nearbys
from transport_energy.data import exchange_calendar as xc
from transport_energy.data import expiry_check as ec

CME_HTML = """<table>
<tr><td>FEB 2012</td><td>CLG12</td><td>11/20/2006</td><td>01/20/2012</td><td>01/20/2012</td></tr>
<tr><td>MAR 2012</td><td>CLH12</td><td>11/20/2006</td><td>02/21/2012</td><td>02/21/2012</td></tr>
<tr><td>Some Other Text</td><td>RBH12</td><td>x</td><td>01/01/2012</td></tr>
</table>"""


def test_parse_cme_calendar():
    t = xc.parse_cme_calendar(CME_HTML, "CL")
    assert list(t["contract"]) == ["CLG2012", "CLH2012"]
    assert t["last_trade"].iloc[1] == pd.Timestamp("2012-02-21")


def test_cme_label_code_mismatch_raises():
    with pytest.raises(ValueError, match="does not match"):
        xc.parse_cme_calendar(CME_HTML.replace("CLH12", "CLJ12"), "CL")


def test_combine_cme_prefers_latest_capture_before_expiry():
    a = xc.parse_cme_calendar(CME_HTML, "CL")
    b = a.copy()
    b.loc[b["contract"] == "CLH2012", "last_trade"] = pd.Timestamp("2012-02-17")
    out, conflicts = xc.combine_cme_calendars([(pd.Timestamp("2011-01-01"), a),
                                               (pd.Timestamp("2012-01-05"), b)])
    assert out.set_index("contract").loc["CLH2012", "last_trade"] == pd.Timestamp("2012-02-17")
    assert set(conflicts["contract"]) == {"CLH2012"}


def test_exchange_holidays_use_settlement_existence():
    days = pd.bdate_range("2001-11-01", "2001-11-30")
    price_dates = days.difference(pd.DatetimeIndex(
        ["2001-11-22",            # Thanksgiving: holiday, no settlement
         "2001-11-23"]))          # day after: abbreviated session missing from the data
    hol = xc.exchange_holidays(days[0], days[-1], price_dates)
    # Veterans Day observed Mon 12 Nov 2001 has a settlement -> business day
    assert list(hol) == [pd.Timestamp("2001-11-22")]
    bdays = xc.scheduled_business_days(days[0], days[-1], price_dates)
    assert pd.Timestamp("2001-11-23") in bdays   # still a business day for expiry counting


def test_rule_on_scheduled_calendar_differs_from_price_dates():
    # Dec-2001 CL: the 25th (Sun) is not a business day; Fri 23rd is the business day
    # before it, and expiry is the third business day before that. Counting only price
    # dates would skip the 23rd and move the expiry back a day.
    days = pd.bdate_range("2001-10-01", "2001-12-31")
    price_dates = days.difference(pd.DatetimeIndex(["2001-11-22", "2001-11-23"]))
    sched = xc.scheduled_business_days(days[0], days[-1], price_dates)
    on_sched = ec.rule_expiries("CL", "cl", sched).set_index("contract")
    on_prices = ec.rule_expiries("CL", "cl", price_dates).set_index("contract")
    assert on_sched.loc["CLZ2001", "expiry"] == pd.Timestamp("2001-11-19")
    assert on_prices.loc["CLZ2001", "expiry"] == pd.Timestamp("2001-11-16")


def test_final_expiries_prefer_cme():
    rule = pd.DataFrame({"contract": ["CLG2012", "CLF2009"], "year": [2012, 2009],
                         "month": [2, 1], "expiry": pd.to_datetime(["2012-01-19", "2008-12-19"])})
    cme = xc.parse_cme_calendar(CME_HTML, "CL")
    out = ec.final_expiries(rule, cme).set_index("contract")
    assert out.loc["CLG2012", "expiry"] == pd.Timestamp("2012-01-20")
    assert out.loc["CLG2012", "source"] == "cme_published"
    assert out.loc["CLF2009", "source"] == "rulebook_rule"
    assert out.loc["CLH2012", "source"] == "cme_published"   # only in CME
    cmp_ = ec.compare_rule_to_cme(rule, cme)
    assert cmp_["matches"].tolist() == [False]


def _synthetic_nearbys(days, expiries, contango=0.5, noise=0.02, seed=0):
    """EIA-style C1..C3 from contracts with a common random walk plus a fixed curve."""
    rng = np.random.default_rng(seed)
    level = 60 + np.cumsum(rng.normal(0, noise, len(days)))
    labels = label_nearbys(days, expiries, depth=3)
    order = {c: i for i, c in enumerate(expiries["contract"])}
    out = {}
    for k in (1, 2, 3):
        out[f"c{k}"] = [lv + contango * order[c] for lv, c in zip(level, labels[k], strict=True)]
    return pd.DataFrame(out, index=days)


def _expiries(days):
    ex = [days[i] for i in (20, 41, 62, 83)]
    later = [days[-1] + pd.Timedelta(days=30 * k) for k in (1, 2, 3)]
    return pd.DataFrame({"contract": list("ABCDEFG"), "expiry": ex + later})


def test_settlement_diagnostic_detects_shifted_dates():
    days = pd.bdate_range("2010-01-04", periods=100)
    true = _expiries(days)
    px = _synthetic_nearbys(days, true)
    ok = ec.settlement_diagnostic(px, true.iloc[:4], tick=0.01)
    assert (ok["status"] == "consistent").all()
    shifted = true.iloc[:4].assign(expiry=[days[i] for i in (21, 42, 63, 84)])
    bad = ec.settlement_diagnostic(px, shifted, tick=0.01)
    assert (bad["status"] == "inconsistent").all()
    assert (bad["best_shift"] == -1).all()


def test_settlement_diagnostic_flat_curve_is_uninformative():
    days = pd.bdate_range("2010-01-04", periods=100)
    true = _expiries(days)
    px = _synthetic_nearbys(days, true, contango=0.0)
    diag = ec.settlement_diagnostic(px, true.iloc[:4], tick=0.01)
    assert (diag["status"] == "uninformative").all()
