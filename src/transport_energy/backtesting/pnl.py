"""Dollar P&L of a futures position, computed within the contract actually held.

Convention: ``positions[d]`` is the signed number of contracts held from the
settlement of date ``d`` to the next settlement, in contract ``held[d]``. The P&L
booked on date ``d`` is therefore

    q[d-1] * (P_{held[d-1]}(d) - P_{held[d-1]}(d-1)) * multiplier,

so a roll never mixes the prices of two different contracts. Working in dollars
(not percent of price) is required anyway: WTI settled at -$37.63 on 2020-04-20.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def contracts_traded(positions: pd.Series, held: pd.Series) -> pd.Series:
    """Contracts traded at each settlement, including both legs of a roll."""
    q = positions.to_numpy(dtype=float)
    q_prev = np.concatenate([[0.0], q[:-1]])
    h = held.to_numpy()
    rolled = np.concatenate([[False], h[1:] != h[:-1]])
    traded = np.where(rolled, np.abs(q_prev) + np.abs(q), np.abs(q - q_prev))
    return pd.Series(traded, index=positions.index, name="contracts_traded")


def futures_pnl(
    positions: pd.Series,
    held: pd.Series,
    prices: pd.DataFrame,
    multiplier: float,
    cost_per_contract_side: float = 0.0,
) -> pd.DataFrame:
    """Daily gross P&L, contracts traded, costs and net P&L in USD.

    Raises if a position is open in a contract with a missing settlement: missing
    prices are a data problem to be fixed upstream, never silently filled here.
    """
    if not positions.index.equals(held.index):
        raise ValueError("positions and held must share an index")
    if positions.isna().any():
        raise ValueError("positions contain NaN; flat must be encoded as 0")
    index = positions.index
    q = positions.to_numpy(dtype=float)
    cols = prices.columns.get_indexer(held.where(q != 0, prices.columns[0]))
    if (cols < 0).any():
        missing = sorted(set(held[(cols < 0)]))
        raise ValueError(f"no price column for held contracts {missing}")
    p = prices.reindex(index).to_numpy(dtype=float)

    gross = np.zeros(len(index))
    if len(index) > 1:
        rows = np.arange(1, len(index))
        prev_cols = cols[:-1]
        p_now, p_then = p[rows, prev_cols], p[rows - 1, prev_cols]
        open_prev = q[:-1] != 0
        bad = open_prev & (np.isnan(p_now) | np.isnan(p_then))
        if bad.any():
            first = index[1:][bad][0]
            raise ValueError(f"missing settlement for an open position around {first.date()}")
        gross[1:] = np.where(open_prev, q[:-1] * (p_now - p_then) * multiplier, 0.0)

    traded = contracts_traded(positions, held)
    costs = traded * cost_per_contract_side
    return pd.DataFrame(
        {"gross_pnl": gross, "contracts_traded": traded, "costs": costs, "net_pnl": gross - costs},
        index=index,
    )
