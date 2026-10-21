"""Download manifest, EIA Excel parsing, WPSR Table 1 parsing, quality counts. Synthetic."""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from transport_energy.data import eia, quality, wpsr_tables
from transport_energy.data.download import DownloadError, Fetcher

# Layout copied from a real Table 1 CSV; every number is made up.
TABLE1 = '''"STUB_1","3/2/12","2/24/12","Difference","Percent Change"
"Crude Oil","1,000.000","999.000","1.000","0.1"
"Commercial (Excluding SPR)","345.700","344.868","0.832","0.2"
"Total Motor Gasoline","229.531","229.927","-0.396","-0.2"
"Distillate Fuel Oil","139.496","141.440","-1.944","-1.4"
"Distillate Fuel Oil","1.000","2.000","0","0"
"STUB_1","STUB_2","3/2/12","2/24/12","Difference"
"Crude Oil Supply ","(1)     Domestic Production","5,806","5,814","-8"
"Products Supplied ","(26)   Total","18,178","18,256","-78"
"Products Supplied ","(27)     Finished Motor Gasoline","8,262","8,363","-101"
'''


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content
        self.text = content.decode()


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls, self.headers = routes, [], {}

    def get(self, url, timeout):
        self.calls.append(url)
        status, body = self.routes[url]
        return FakeResponse(status, body)


def test_fetcher_records_hash_and_caches(tmp_path):
    s = FakeSession({"http://x/a.xls": (200, b"abc")})
    f = Fetcher(tmp_path, min_interval=0, session=s)
    p = f.fetch("http://x/a.xls", "eia/a.xls")
    assert p.read_bytes() == b"abc"
    entry = json.loads((tmp_path / "MANIFEST.json").read_text())["eia/a.xls"]
    assert entry["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert entry["url"] == entry["original_url"] == "http://x/a.xls"
    f.fetch("http://x/a.xls", "eia/a.xls")
    assert len(s.calls) == 1   # cached: not fetched twice


def test_fetchers_share_manifest_and_404_raises(tmp_path):
    s = FakeSession({"u1": (200, b"1"), "u2": (200, b"2"), "u3": (404, b"")})
    f1, f2 = Fetcher(tmp_path, min_interval=0, session=s), Fetcher(tmp_path, 0, session=s)
    f1.fetch("u1", "a")
    f2.fetch("u2", "b", original_url="orig")
    m = json.loads((tmp_path / "MANIFEST.json").read_text())
    assert set(m) == {"a", "b"} and m["b"]["original_url"] == "orig"
    with pytest.raises(DownloadError, match="404"):
        f1.fetch("u3", "c")


class FakeSheet:
    def __init__(self, rows):
        self.rows, self.nrows = rows, len(rows)

    def cell_value(self, r, c):
        return self.rows[r][c]


class FakeBook:
    def __init__(self, rows):
        self.sheet = FakeSheet(rows)

    def sheet_names(self):
        return ["Contents", "Data 1"]

    def sheet_by_name(self, name):
        return self.sheet


def test_parse_hist_xls(monkeypatch):
    rows = [["Back", "t"], ["Sourcekey", "WGFUPUS2"], ["Date", "t"],
            [33277.0, 6621.0], [33284.0, ""]]
    monkeypatch.setattr(eia.xlrd, "open_workbook", lambda p: FakeBook(rows))
    s = eia.parse_hist_xls("x.xls", expected_key="WGFUPUS2")
    assert s.index[0] == pd.Timestamp("1991-02-08")    # Excel serial 33277
    assert s.iloc[0] == 6621.0 and np.isnan(s.iloc[1])
    with pytest.raises(ValueError, match="source key"):
        eia.parse_hist_xls("x.xls", expected_key="OTHER")


def test_source_key_strips_frequency_suffix():
    assert eia.source_key("WGFUPUS2w") == "WGFUPUS2"
    assert eia.source_key("EER_EPMRR_PE1_Y35NY_DPGd") == "EER_EPMRR_PE1_Y35NY_DPG"


def test_parse_table1_units_labels_and_first_occurrence():
    t = wpsr_tables.parse_table1(TABLE1)
    cur = t[t["column"] == "current"].set_index("series")["value"]
    assert cur["crude_stocks_ex_spr"] == pytest.approx(345_700.0)   # million bbl -> kb
    assert cur["distillate_stocks"] == pytest.approx(139_496.0)     # first occurrence only
    assert cur["gasoline_product_supplied"] == 8262.0                # line number stripped
    assert cur["total_product_supplied"] == 18178.0
    assert set(t["week"]) == {pd.Timestamp("2012-03-02"), pd.Timestamp("2012-02-24")}


def test_parse_table1_missing_row_raises():
    with pytest.raises(ValueError, match="gasoline_stocks"):
        wpsr_tables.parse_table1(TABLE1.replace("Total Motor Gasoline", "Something"))


def test_compare_with_history_and_week_to_week():
    first = wpsr_tables.parse_table1(TABLE1)
    hist = pd.DataFrame({"crude_stocks_ex_spr": [345_700.0], "gasoline_stocks": [229_600.0]},
                        index=pd.DatetimeIndex(["2012-03-02"]))
    cmp_ = wpsr_tables.compare_with_history(first, hist).set_index("series")
    assert bool(cmp_.loc["crude_stocks_ex_spr", "matches"])
    assert cmp_.loc["gasoline_stocks", "diff"] == pytest.approx(69.0)
    assert np.isnan(cmp_.loc["distillate_stocks", "history"])
    # next edition re-publishes this week's numbers in its 'prior' column
    cur = first[first["column"] == "current"]
    nxt = pd.concat([cur.assign(column="prior"),
                     cur.assign(column="current", week=cur["week"] + pd.Timedelta(days=7))])
    w2w = wpsr_tables.week_to_week_revisions(pd.concat([first, nxt]))
    assert len(w2w) == 6 and w2w["matches"].all()
    nxt.loc[nxt["series"].eq("gasoline_stocks") & nxt["column"].eq("prior"), "value"] += 100
    w2w = wpsr_tables.week_to_week_revisions(pd.concat([first, nxt])).set_index("series")
    assert not w2w.loc["gasoline_stocks", "matches"]
    assert w2w.loc["gasoline_stocks", "diff"] == pytest.approx(100.0)


def test_weekly_quality_splits_periods():
    idx = pd.date_range("2016-12-02", "2017-01-27", freq="W-FRI").delete([1, 6])
    w = pd.DataFrame({"x": np.arange(len(idx), dtype=float)}, index=idx)
    q = quality.weekly_quality(w, test_start=pd.Timestamp("2017-01-01")).set_index("period")
    assert q.loc["development", "missing_fridays"] == 1
    assert q.loc["test", "missing_fridays"] == 1
    assert q.loc["development", "non_positive_values"] == 1   # the made-up zero
