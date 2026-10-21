"""Expiry calendar: documented dates first, settlement behaviour only as a diagnostic.

Order of evidence:

1. CME-published last-trade dates (exchange metadata) where archived copies exist.
2. The rulebook rule on the scheduled business-day calendar elsewhere. Its accuracy is
   measured where both exist (rule vs CME) before it is trusted on earlier years.
3. A settlement diagnostic that never sets a date. EIA's "contract 1" switches to the
   next contract on the first settlement after expiry, so on a correctly dated expiry
   ``e`` (next settlement ``d``) the roll hypothesis

       |C1(d) - C2(e)| + |C2(d) - C3(e)|        (each term: one contract, one day)

   should fit better than the no-roll hypothesis

       |C1(d) - C1(e)| + |C2(d) - C2(e)|        (each term: one day plus a spread)

   and on neighbouring days the reverse. When the C1-C2 spread is within a few ticks of
   zero the two hypotheses cannot be told apart and the check is "uninformative".
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
    min_spread_ticks: float = 3.0,
) -> pd.DataFrame:
    """Per expiry inside the price sample: does the roll fit best on the documented date?

    ``nearby`` has columns ``c1, c2, c3`` indexed by settlement date. For candidate
    roll days ``e_k`` (the documented expiry shifted by k = -window..window settlements)
    the margin ``noroll - roll`` is computed; a positive margin favours a roll after e_k.
    """
    px = nearby[["c1", "c2", "c3"]].dropna()
    dates = px.index
    a = px.to_numpy(dtype=float)
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
            today, nxt = a[i], a[i + 1]
            roll = abs(nxt[0] - today[1]) + abs(nxt[1] - today[2])
            noroll = abs(nxt[0] - today[0]) + abs(nxt[1] - today[1])
            margins[k] = noroll - roll
        spread = abs(a[i0, 0] - a[i0, 1])
        best = max(margins, key=margins.get) if margins else np.nan
        if spread < min_spread_ticks * tick:
            status = "uninformative"
        elif best == 0 and margins[0] > 0:
            status = "consistent"
        else:
            status = "inconsistent"
        rows.append({
            "contract": ex["contract"], "expiry": e, "source": ex.get("source", ""),
            "expiry_in_price_data": bool(dates[i0] == e), "c1_c2_spread": spread,
            "margin_at_expiry": margins.get(0, np.nan), "best_shift": best, "status": status,
        })
    return pd.DataFrame(rows)
