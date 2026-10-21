"""Expiry calendar: documented dates first, settlement behaviour only as a diagnostic.

Order of evidence:

1. CME-published last-trade dates (exchange metadata) where archived copies exist.
2. The rulebook rule on the scheduled business-day calendar elsewhere. Its accuracy is
   measured where both exist (rule vs CME) before it is trusted on earlier years.
3. A settlement diagnostic that never sets a date. EIA's "contract 1" switches to the
   next contract on the first settlement after expiry. Calendar *spreads* move far
   less from day to day than outright prices, so compare spreads: if the roll happened
   after ``e`` (next settlement ``d``), today's C1-C2 spread is the same contract pair
   as yesterday's C2-C3 spread,

       roll error    = |S12(d) - S23(e)|
       no-roll error = |S12(d) - S12(e)|

   and the margin ``no-roll - roll`` should be positive at the documented date and
   negative on neighbouring days. When ``|S12(e) - S23(e)|`` is within a few ticks the
   two hypotheses cannot be told apart and the check is "uninformative".
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from transport_energy.backtesting.contracts import expiry_table


def rule_expiries(root: str, rule: str, business_days: pd.DatetimeIndex) -> pd.DataFrame:
    """Rulebook expiries on a business-day calendar, as (contract, year, month, expiry)."""
    return expiry_table(root, rule, business_days)


def compare_rule_to_cme(rule: pd.DataFrame, cme: pd.DataFrame) -> pd.DataFrame:
    """Contracts in both tables with ``rule_expiry``, ``cme_last_trade`` and ``matches``."""
    m = rule.merge(cme[["contract", "last_trade"]], on="contract", how="inner")
    m = m.rename(columns={"expiry": "rule_expiry", "last_trade": "cme_last_trade"})
    m["matches"] = m["rule_expiry"] == m["cme_last_trade"]
    return m


def final_expiries(rule: pd.DataFrame, cme: pd.DataFrame) -> pd.DataFrame:
    """CME-published date where available, rule date otherwise; ``source`` says which."""
    r = rule.set_index("contract")
    out = r[["year", "month"]].copy()
    out["expiry"] = r["expiry"]
    out["source"] = "rulebook_rule"
    if not cme.empty:
        c = cme.set_index("contract")
        common = out.index.intersection(c.index)
        out.loc[common, "expiry"] = c.loc[common, "last_trade"]
        out.loc[common, "source"] = "cme_published"
        extra = c.index.difference(out.index)
        if len(extra):
            add = c.loc[extra, ["year", "month", "last_trade"]].rename(
                columns={"last_trade": "expiry"}).assign(source="cme_published")
            out = pd.concat([out, add])
    return out.reset_index(names="contract").sort_values("expiry").reset_index(drop=True)


def settlement_diagnostic(
    nearby: pd.DataFrame, expiries: pd.DataFrame, tick: float, window: int = 2,
    min_spread_ticks: float = 5.0,
) -> pd.DataFrame:
    """Per expiry inside the price sample: does the roll fit best on the documented date?

    ``nearby`` has columns ``c1, c2, c3`` indexed by settlement date. For candidate
    roll days ``e_k`` (the documented expiry shifted by k = -window..window settlements)
    the margin ``noroll - roll`` is computed on spreads; positive favours a roll after e_k.
    """
    px = nearby[["c1", "c2", "c3"]].dropna()
    dates = px.index
    a = px.to_numpy(dtype=float)
    s12, s23 = a[:, 0] - a[:, 1], a[:, 1] - a[:, 2]
    rows = []
    for _, ex in expiries.iterrows():
        e = ex["expiry"]
        if e < dates[0] or e >= dates[-1]:
            continue
        i0 = dates.searchsorted(e, side="right") - 1      # last settlement on/before e
        margins = {}
        for k in range(-window, window + 1):
            i = i0 + k
            if i < 0 or i + 1 >= len(dates):
                continue
            roll = abs(s12[i + 1] - s23[i])
            noroll = abs(s12[i + 1] - s12[i])
            margins[k] = noroll - roll
        separation = abs(s12[i0] - s23[i0])
        best = max(margins, key=margins.get) if margins else np.nan
        if separation < min_spread_ticks * tick:
            status = "uninformative"
        elif best == 0 and margins[0] > 0:
            status = "consistent"
        else:
            status = "inconsistent"
        rows.append({
            "contract": ex["contract"], "expiry": e, "source": ex.get("source", ""),
            "expiry_in_price_data": bool(dates[i0] == e), "s12_minus_s23": separation,
            "margin_at_expiry": margins.get(0, np.nan), "best_shift": best, "status": status,
        })
    return pd.DataFrame(rows)
