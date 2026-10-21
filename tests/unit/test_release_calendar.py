"""Release calendar: observed dates, documented times, conservative fallback. Synthetic HTML."""

import pandas as pd
import pytest

from transport_energy.data import release_calendar as rc
from transport_energy.timing import build_event_table

ARCHIVE_HTML = """
<table>
<thead id="2021-2022"><tr><th colspan="5">2021 - 2022</th></tr></thead>
<tr><td></td><td>Release date</td><td>Data ending</td><td>Release date</td><td>Data ending</td></tr>
<tr><td>January</td>
  <td><a href="/petroleum/supply/weekly/archive/2021/2021_01_06/wpsr_2021_01_06.php">6</a></td>
  <td>1/1</td>
  <td><a href="/petroleum/supply/weekly/archive/2022/2022_01_05/wpsr_2022_01_05.php">5</a></td>
  <td>12/31</td></tr>
<tr><td></td>
  <td><a href="/petroleum/supply/weekly/archive/2021/2021_01_13/wpsr_2021_01_13.php">13</a></td>
  <td>8</td><td></td><td></td></tr>
<tr><td>June</td><td></td><td></td>
  <td><a href="/petroleum/supply/weekly/archive/2022/2022_06_17_data/wpsr_2022_06_17_data.php">29</a></td>
  <td>17</td></tr>
</table>
"""

SCHEDULE_HTML = """
<html><body><script>var x = "ignore 10:30 a.m.";</script>
<p>The standard release time and day of the week will be at 10:30 a.m. (Eastern time)
on Wednesdays with the following exceptions. All times are Eastern.</p>
<table>
<tr><td>Data for the week ending</td><td>Alternate Release Date</td><td>Release Day</td>
<td>Release Time</td><td>Holiday</td></tr>
<tr><td>January 15, 2021</td><td>January 21, 2021</td><td>Thursday</td><td>12:00 p.m.</td>
<td>Martin Luther King Jr.</td></tr>
<tr><td>December 24, 2021</td><td>December 30, 2021</td><td>Thursday</td><td>11:00 a.m.</td>
<td>Christmas</td></tr>
</table></body></html>
"""


def page(html=SCHEDULE_HTML, snap="2021-01-10", url="copyA"):
    return rc.parse_schedule_page(html, pd.Timestamp(snap), url)


def test_archive_index_dates_months_years_and_suffix():
    a = rc.parse_archive_index(ARCHIVE_HTML)
    assert list(a["release_date"]) == [pd.Timestamp(d) for d in
                                       ["2021-01-06", "2021-01-13", "2022-01-05", "2022-06-29"]]
    # "12/31" in a January 2022 row belongs to the previous year
    assert a.loc[a["release_date"] == "2022-01-05", "data_ending"].item() == pd.Timestamp(
        "2021-12-31")
    # a bare day means the release month
    assert a.loc[a["release_date"] == "2021-01-13", "data_ending"].item() == pd.Timestamp(
        "2021-01-08")
    # the folder name is NOT the release date for irregular editions
    odd = a[a["folder_suffix"] == "_data"].iloc[0]
    assert odd["folder_date"] == pd.Timestamp("2022-06-17")
    assert odd["release_date"] == pd.Timestamp("2022-06-29")


@pytest.mark.parametrize("text,expected", [
    ("10:30 a.m.", "10:30"), ("10:30 a. m.", "10:30"), ("12:00 p.m.", "12:00"),
    ("5:00 p.m.", "17:00"), ("noon", "12:00"), ("11 a.m.", "11:00"),
])
def test_parse_clock(text, expected):
    assert rc.parse_clock(text) == expected


def test_schedule_page_rule_and_exceptions():
    p = page()
    assert (p.standard_weekday, p.standard_time) == ("Wednesday", "10:30")
    assert list(p.exceptions["time"]) == ["12:00", "11:00"]
    assert p.exceptions["scheduled_date"].iloc[0] == pd.Timestamp("2021-01-21")


def test_schedule_weekday_mismatch_raises():
    bad = SCHEDULE_HTML.replace("<td>January 21, 2021</td><td>Thursday",
                                "<td>January 21, 2021</td><td>Friday")
    with pytest.raises(ValueError, match="weekday"):
        page(bad)


def test_combine_latest_copy_wins_and_conflict_reported():
    revised = SCHEDULE_HTML.replace("12:00 p.m.", "10:30 a.m.")
    exc, cov, conflicts = rc.combine_schedules([page(), page(revised, "2021-01-18", "copyB")])
    row = exc[exc["data_ending"] == "2021-01-15"].iloc[0]
    assert row["time"] == "10:30" and row["source_url"] == "copyB"
    assert set(conflicts["source_url"]) == {"copyA", "copyB"}
    assert cov["start"].min() == pd.Timestamp("2021-01-10")   # capture date of copy A
    assert cov["end"].max() == pd.Timestamp("2021-12-30")


def _calendar(rows):
    archive = pd.DataFrame(rows, columns=["release_date", "data_ending"]).apply(pd.to_datetime)
    exc, cov, _ = rc.combine_schedules([page()])
    return rc.build_release_calendar(archive, exc, cov)


def test_documented_standard_and_exception_times():
    cal = _calendar([("2021-01-13", "2021-01-08"), ("2021-01-21", "2021-01-15")])
    assert list(cal["time_source"]) == [rc.TIME_DOCUMENTED] * 2
    assert cal["release_ts_latest"].iloc[0] == pd.Timestamp("2021-01-13 10:30",
                                                             tz="America/New_York")
    assert cal["release_ts_latest"].iloc[1] == pd.Timestamp("2021-01-21 12:00",
                                                             tz="America/New_York")
    assert (cal["release_ts_earliest"] == cal["release_ts_latest"]).all()


def test_date_off_schedule_or_uncovered_gets_whole_day():
    cal = _calendar([
        ("2021-01-14", "2021-01-08"),   # observed Thursday, schedule said Wednesday
        ("2022-03-09", "2022-03-04"),   # after the page's coverage ends
    ])
    assert (cal["time_source"] == rc.TIME_ASSUMED).all()
    assert list(cal["assumption_reason"]) == ["observed date differs from scheduled date",
                                              "time not documented"]
    first = cal.iloc[0]
    assert first["release_ts_earliest"] == pd.Timestamp("2021-01-14 00:00", tz="America/New_York")
    assert first["release_ts_latest"] == pd.Timestamp("2021-01-14 23:59:59",
                                                       tz="America/New_York")


def test_unknown_time_pushes_entry_to_next_settlement(make_calendar):
    days = make_calendar("2021-01-01", "2021-02-28")
    cal = _calendar([("2021-01-13", "2021-01-08"), ("2021-01-21", "2021-01-15"),
                     ("2021-01-28", "2021-01-22")])
    cal.loc[2, ["release_ts_earliest", "release_ts_latest"]] = [
        pd.Timestamp("2021-01-28 00:00", tz="America/New_York"),
        pd.Timestamp("2021-01-28 23:59:59", tz="America/New_York")]
    ev = build_event_table(cal.assign(reference_week_end=cal["data_ending"]), days)
    # documented 10:30 Wednesday: same-day settlement
    assert ev.loc[0, "entry_date"] == pd.Timestamp("2021-01-13")
    # unknown time on Thursday 28th: window opens Wednesday, entry waits for Friday
    assert ev.loc[2, "pre_date"] == pd.Timestamp("2021-01-27")
    assert ev.loc[2, "entry_date"] == pd.Timestamp("2021-01-29")
    # the previous holding period must end before the earliest possible release time
    assert ev.loc[1, "exit_date"] == pd.Timestamp("2021-01-27")


def test_release_window_check():
    cal = _calendar([("2021-01-13", "2021-01-08"), ("2021-01-21", "2021-01-15")])
    late = pd.DataFrame({"release_date": [pd.Timestamp("2021-02-05")],
                         "data_ending": [pd.Timestamp("2021-01-29")]})
    late = rc.build_release_calendar(late, *rc.combine_schedules([page()])[:2])
    chk = rc.check_release_window(pd.concat([cal, late], ignore_index=True))
    # F+7 with unknown time: latest possible time (23:59) is after the 14:29 bound
    assert list(chk["violates"]) == [False, False, True]
    assert list(chk["holiday_week"]) == [False, True, False]   # MLK Day 2021-01-18
