import pandas as pd
import pytest

from transport_energy.timing import (
    align_asof,
    build_event_table,
    conservative_release_ts,
    first_settlement_after,
    last_settlement_before,
)


def ts(s: str, tz: str = "America/New_York") -> pd.Timestamp:
    return pd.Timestamp(s, tz=tz)


@pytest.fixture
def days(make_calendar):
    return make_calendar("2024-01-01", "2026-01-31", holidays=["2025-12-25"])


def test_wednesday_release_enters_at_wednesday_settlement(days):
    r = ts("2024-01-10 10:30")
    assert first_settlement_after(r, days) == pd.Timestamp("2024-01-10")
    assert last_settlement_before(r, days) == pd.Timestamp("2024-01-09")


def test_holiday_thursday_noon_release(days):
    r = ts("2024-01-18 12:00")
    assert first_settlement_after(r, days) == pd.Timestamp("2024-01-18")
    assert last_settlement_before(r, days) == pd.Timestamp("2024-01-17")


def test_release_after_settlement_waits_for_next_day(days):
    # Christmas 2025 edition was released Monday 29 Dec at 17:00 ET.
    r = ts("2025-12-29 17:00")
    assert first_settlement_after(r, days) == pd.Timestamp("2025-12-30")
    assert last_settlement_before(r, days) == pd.Timestamp("2025-12-29")


def test_release_exactly_at_settlement_is_not_usable_that_day(days):
    r = ts("2024-01-10 14:30")
    assert first_settlement_after(r, days) == pd.Timestamp("2024-01-11")


def test_timezones_are_respected(days):
    # 15:30 UTC = 10:30 EST in January.
    assert first_settlement_after(ts("2024-01-10 15:30", "UTC"), days) == pd.Timestamp("2024-01-10")
    # 20:00 UTC = 15:00 EST, after the 14:30 settlement.
    assert first_settlement_after(ts("2024-01-10 20:00", "UTC"), days) == pd.Timestamp("2024-01-11")


def test_naive_timestamps_are_rejected(days):
    with pytest.raises(ValueError, match="timezone-aware"):
        first_settlement_after(pd.Timestamp("2024-01-10 10:30"), days)


def test_event_table_brackets_and_exits_before_next_release(days):
    releases = pd.DataFrame({
        "reference_week_end": pd.to_datetime(["2024-01-05", "2024-01-12", "2024-01-19"]),
        "release_ts": [ts("2024-01-10 10:30"), ts("2024-01-18 12:00"), ts("2024-01-24 10:30")],
    })
    ev = build_event_table(releases, days)
    pre = pd.to_datetime(["2024-01-09", "2024-01-17", "2024-01-23"])
    entry = pd.to_datetime(["2024-01-10", "2024-01-18", "2024-01-24"])
    assert ev["pre_date"].tolist() == pre.tolist()
    assert ev["entry_date"].tolist() == entry.tolist()
    # Exit at the last settlement before the next release.
    assert ev["exit_date"].iloc[0] == pd.Timestamp("2024-01-17")
    assert ev["exit_date"].iloc[1] == pd.Timestamp("2024-01-23")
    assert pd.isna(ev["exit_date"].iloc[2])


def test_conservative_release_requires_calibration():
    with pytest.raises(ValueError, match="not calibrated"):
        conservative_release_ts(pd.Timestamp("2005-01-07"), None)


def test_conservative_release_enters_friday_after(make_calendar):
    days = make_calendar("2005-01-01", "2005-02-28")
    r = conservative_release_ts(pd.Timestamp("2005-01-07"), days_after=7)  # by Fri 14th 14:29
    assert first_settlement_after(r, days) == pd.Timestamp("2005-01-14")


def test_conservative_release_skips_non_trading_friday(make_calendar):
    days = make_calendar("2005-03-01", "2005-04-29", holidays=["2005-03-25"])  # Good Friday
    r = conservative_release_ts(pd.Timestamp("2005-03-18"), days_after=7)
    assert first_settlement_after(r, days) == pd.Timestamp("2005-03-28")


def test_align_asof_uses_only_strictly_earlier_releases():
    avail = pd.DataFrame({
        "available_at": [ts("2024-01-03 10:30"), ts("2024-01-10 10:30")],
        "surprise": [1.0, 2.0],
    })
    decisions = pd.Series([
        ts("2024-01-10 14:30"),  # after second release -> 2.0
        ts("2024-01-10 10:30"),  # exactly at release -> not yet usable -> 1.0
        ts("2024-01-09 14:30"),  # before second release -> 1.0
        ts("2024-01-02 14:30"),  # before any release -> NaN
    ])
    out = align_asof(decisions, avail)
    assert out["surprise"].iloc[:3].tolist() == [2.0, 1.0, 1.0]
    assert pd.isna(out["surprise"].iloc[3])
