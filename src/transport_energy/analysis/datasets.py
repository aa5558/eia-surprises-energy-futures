"""Assemble the event dataset (surprises + windows + returns) for one period.

``period="development"`` slices every input to dates before the test start *before*
any computation, so nothing derived here can depend on 2017+ data.
``period="full"`` passes the inputs through ``integrity.guard_development``, which
raises unless the specification has been frozen (``spec-freeze-*`` tag) and
``TEQ_UNLOCK_TEST`` names that tag.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np
import pandas as pd

from transport_energy.config import REPO_ROOT, load_config
from transport_energy.data.download import DEFAULT_RAW
from transport_energy.data.eia import load_group
from transport_energy.features import events as fe
from transport_energy.features import surprises as su
from transport_energy.integrity import default_test_start, development_slice, guard_development

PHASE3 = REPO_ROOT / "reports" / "tables" / "phase3"
SURPRISE_SERIES = {                       # name -> kind (pre-registered, docs/04 §2)
    "crude_stocks_ex_spr": "change",
    "gasoline_stocks": "change",
    "distillate_stocks": "change",
    "gasoline_product_supplied": "level",
}
SHORT = {"crude_stocks_ex_spr": "crude", "gasoline_stocks": "gasoline",
         "distillate_stocks": "distillate", "gasoline_product_supplied": "demand"}
MARKETS = ("CL", "RB")
EVENT_START = {"CL": pd.Timestamp("1996-01-01"), "RB": pd.Timestamp("2006-01-01")}


@dataclass
class Market:
    root: str
    daily: pd.DataFrame       # features.events.contract_daily output
    panel: pd.DataFrame       # date x contract settlements
    calc: fe.WindowCalc


@dataclass
class Dataset:
    period: str
    weekly: pd.DataFrame
    surprises: dict[str, pd.DataFrame]
    events: pd.DataFrame      # one row per (timing, week)
    markets: dict[str, Market]


def load_inputs(period: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    weekly = load_group("weekly", DEFAULT_RAW)
    futures = load_group("futures_daily", DEFAULT_RAW)
    calendar = pd.read_csv(PHASE3 / "release_calendar.csv",
                           parse_dates=["release_date", "data_ending"])
    for c in ("release_ts_earliest", "release_ts_latest"):
        calendar[c] = pd.to_datetime(calendar[c], utc=True).dt.tz_convert("America/New_York")
    if period == "development":
        weekly, futures = development_slice(weekly), development_slice(futures)
        calendar = calendar[calendar["data_ending"] < default_test_start()]
    elif period == "full":
        guard_development(weekly)
        guard_development(futures)
    else:
        raise ValueError(period)
    return weekly, futures, calendar


def first_release_targets(period: str) -> pd.DataFrame:
    """As-first-published weekly targets from archived editions (Aug 2011 on)."""
    from transport_energy.data.wpsr_tables import point_in_time_targets

    first = pd.read_csv(REPO_ROOT / "data" / "processed" / "wpsr_first_release_long.csv",
                        parse_dates=["week"])
    if period == "development":
        # an edition is usable only if published before the test start
        first = first[pd.to_datetime(first["release_date"]) < default_test_start()]
    return point_in_time_targets(first, SURPRISE_SERIES)


def expiries(root: str) -> pd.DataFrame:
    return pd.read_csv(PHASE3 / f"expiries_{root}.csv", parse_dates=["expiry"])


def inventory_state(level: pd.Series) -> pd.Series:
    """z-score of the level vs the same calendar week in the prior 5 years (H4 state)."""
    s = su.regular_weekly(level)
    lags = pd.concat([s.shift(52 * k) for k in range(1, 6)], axis=1)
    return (s - lags.mean(axis=1, skipna=False)) / lags.std(axis=1, ddof=1, skipna=False)


def build_market(root: str, futures: pd.DataFrame, roll_days: int) -> Market:
    r = root.lower()
    nearby = futures[[f"{r}_c1", f"{r}_c2", f"{r}_c3"]].dropna(how="all")
    nearby.columns = ["c1", "c2", "c3"]
    exp = expiries(root)[["contract", "expiry"]]
    daily = fe.contract_daily(nearby, exp, roll_days)
    from transport_energy.backtesting.contracts import contract_price_panel, label_nearbys

    labels = label_nearbys(nearby.index, exp.sort_values("expiry").reset_index(drop=True), 3)
    panel = contract_price_panel(nearby.set_axis([1, 2, 3], axis=1), labels)
    return Market(root, daily, panel, fe.WindowCalc(daily))


@cache
def build(period: str = "development", roll_days: int = 5) -> Dataset:
    weekly, futures, calendar = load_inputs(period)
    pit = first_release_targets(period)
    surprises = {SHORT[n]: su.surprise_table(weekly[n], k, pit[n])
                 for n, k in SURPRISE_SERIES.items()}
    markets = {m: build_market(m, futures, roll_days) for m in MARKETS}
    trading = {m: markets[m].daily.index for m in MARKETS}

    frames = []
    for m in MARKETS:
        days = trading[m]
        prec = fe.precise_windows(calendar, days)
        fridays = su.regular_weekly(weekly["crude_stocks_ex_spr"]).index
        fridays = fridays[fridays >= EVENT_START[m] - pd.Timedelta(days=7)]
        cons = fe.conservative_windows(fridays, days)
        for w in (prec, cons):
            w = w[w["week"] >= EVENT_START[m]]
            ev = fe.attach_returns(w, markets[m].calc, m.lower())
            frames.append(ev.assign(market=m))
    events = pd.concat(frames, ignore_index=True)

    # surprises known at the release of week t (and the stale placebo: 4 releases earlier)
    for short, tab in surprises.items():
        for model in su.MODELS:
            z = tab[f"z_{model}"]
            events[f"z_{short}_{model}"] = events["week"].map(z)
            events[f"z4_{short}_{model}"] = events["week"].map(z.shift(4))
    for name, short in (("crude_stocks_ex_spr", "crude"), ("gasoline_stocks", "gasoline")):
        state = inventory_state(weekly[name]).shift(1)
        events[f"state_{short}"] = events["week"].map(state)
    events["year"] = events["week"].dt.year
    if period == "development":
        late = events["exit_date"].notna() & (events["exit_date"] >= default_test_start())
        events.loc[late, [c for c in events if c.endswith(("_drift", "_spread_drift"))]] = np.nan
    return Dataset(period, weekly, surprises, events, markets)


def cost_per_side(root: str, scenario: str) -> float:
    from transport_energy.backtesting.costs import CostModel

    return CostModel.from_config(load_config("research"), root, scenario).per_contract_side
