"""End-to-end look-ahead test on SYNTHETIC data (not market evidence).

Pipeline: weekly releases -> event table -> as-of signal -> causal z-score ->
threshold positions -> daily positions -> roll schedule -> dollar P&L.

Central property: rewriting every observation after a cutoff (both the
fundamental releases and the futures prices) must not change any position or
P&L on or before the cutoff.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from transport_energy.backtesting.contracts import expiry_table, roll_schedule
from transport_energy.backtesting.pnl import futures_pnl
from transport_energy.features.transforms import expanding_zscore
from transport_energy.strategies.rules import events_to_daily_positions, threshold_position
from transport_energy.timing import align_asof, build_event_table, settlement_timestamps

pytestmark = pytest.mark.integration
TZ = "America/New_York"
CUTOFF = pd.Timestamp("2014-07-01")


def synthetic_inputs(seed: int = 0):
    days = pd.bdate_range("2013-06-03", "2015-06-30")
    ref_fridays = pd.date_range("2013-06-07", "2015-06-19", freq="W-FRI")
    release_ts = [(f + pd.Timedelta(days=5, hours=10, minutes=30)).tz_localize(TZ)
                  for f in ref_fridays]
    rng = np.random.default_rng(seed)
    releases = pd.DataFrame({
        "reference_week_end": ref_fridays,
        "release_ts": release_ts,
        "surprise": rng.normal(size=len(ref_fridays)),
    })
    # Expiries come from a longer calendar so the contract after the last roll is known;
    # futures_pnl deliberately raises if a position is open in an unidentified contract.
    expiries = expiry_table("CL", "cl", pd.bdate_range("2013-01-01", "2015-12-31"))
    prices = pd.DataFrame(
        50 + rng.normal(scale=0.8, size=(len(days), len(expiries))).cumsum(axis=0),
        index=days, columns=expiries["contract"],
    )
    return days, releases, expiries, prices


def run_pipeline(days, releases, expiries, prices):
    events = build_event_table(releases[["reference_week_end", "release_ts"]], days)
    decision_ts = pd.Series(settlement_timestamps(pd.DatetimeIndex(events["entry_date"]), tz=TZ))
    available = releases.rename(columns={"release_ts": "available_at"})
    available = available[["available_at", "surprise"]]
    signal = align_asof(decision_ts, available)["surprise"]
    z = expanding_zscore(signal, min_periods=10)
    event_pos = threshold_position(z, threshold=0.5)
    positions = events_to_daily_positions(events, event_pos, days)
    held = roll_schedule(days, expiries, business_days_before=5)
    pnl = futures_pnl(positions, held, prices, multiplier=1000, cost_per_contract_side=12.5)
    return events, signal, positions, pnl


def perturb_after_cutoff(releases, prices, cutoff):
    rel, px = releases.copy(), prices.copy()
    late = rel["release_ts"] > cutoff.tz_localize(TZ)
    rel.loc[late, "surprise"] = -10 * rel.loc[late, "surprise"] + 3
    px.loc[px.index > cutoff] = px.loc[px.index > cutoff] * 1.7 - 20
    return rel, px


def test_future_data_cannot_change_past_decisions():
    days, rel, exp, px = synthetic_inputs()
    _, _, pos_a, pnl_a = run_pipeline(days, rel, exp, px)
    rel_b, px_b = perturb_after_cutoff(rel, px, CUTOFF)
    _, _, pos_b, pnl_b = run_pipeline(days, rel_b, exp, px_b)

    pd.testing.assert_series_equal(pos_a.loc[:CUTOFF], pos_b.loc[:CUTOFF])
    pd.testing.assert_frame_equal(pnl_a.loc[:CUTOFF], pnl_b.loc[:CUTOFF])
    # Not vacuous: the perturbation must actually change something later on.
    assert not pos_a.loc[CUTOFF:].equals(pos_b.loc[CUTOFF:])
    assert not pnl_a.loc[CUTOFF:].equals(pnl_b.loc[CUTOFF:])


def test_signal_is_the_release_known_at_entry():
    days, rel, exp, px = synthetic_inputs()
    events, signal, _, _ = run_pipeline(days, rel, exp, px)
    # Wednesday 10:30 release, Wednesday 14:30 entry -> the event's own surprise is usable...
    np.testing.assert_allclose(signal.to_numpy(), rel["surprise"].to_numpy())
    # ...but at the pre-release settlement it is not: only the previous release is.
    pre_ts = pd.Series(settlement_timestamps(pd.DatetimeIndex(events["pre_date"]), tz=TZ))
    available = rel.rename(columns={"release_ts": "available_at"})[["available_at", "surprise"]]
    pre_signal = align_asof(pre_ts, available)["surprise"]
    np.testing.assert_allclose(pre_signal.to_numpy()[1:], rel["surprise"].to_numpy()[:-1])


def test_positions_never_span_a_release():
    days, rel, exp, px = synthetic_inputs()
    events, _, positions, _ = run_pipeline(days, rel, exp, px)
    settle = pd.Series(settlement_timestamps(days, tz=TZ), index=days)
    for r in events["release_ts"]:
        before = settle[settle < r].index.max()  # last close before the release
        if pd.isna(before):
            continue
        # A position held from `before` would carry P&L across the release.
        assert positions.loc[before] == 0


def test_pnl_is_within_contract_only():
    days, rel, exp, px = synthetic_inputs()
    _, _, positions, pnl = run_pipeline(days, rel, exp, px)
    held = roll_schedule(days, exp, business_days_before=5)
    manual = 0.0
    for d0, d1 in zip(days[:-1], days[1:], strict=True):
        q = positions.loc[d0]
        if q:
            c = held.loc[d0]
            manual += q * (px.at[d1, c] - px.at[d0, c]) * 1000
    assert pnl["gross_pnl"].sum() == pytest.approx(manual)
