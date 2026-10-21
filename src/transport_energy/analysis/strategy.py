"""Run event strategies from walk-forward forecasts (shared by development and test)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from transport_energy.analysis import datasets as ds
from transport_energy.backtesting import event_backtest as eb
from transport_energy.config import load_config
from transport_energy.evaluation import metrics as mt

PPY = 52


def sizing() -> eb.SizingConfig:
    cap = load_config("research")["capital"]
    return eb.SizingConfig(capital=float(cap["base_usd"]),
                           vol_target_annual=float(cap["vol_target_annual"]),
                           max_gross_notional_multiple=float(cap["max_gross_notional_multiple"]))


def multiplier(root: str) -> float:
    return float(load_config("research")["contracts"][root]["multiplier"])


def run_market(d: ds.Dataset, events: pd.DataFrame, sig: pd.Series, rule: str, k: float,
               scenario: str, cfg: eb.SizingConfig | None = None) -> eb.BacktestResult:
    """Backtest one market. ``events`` needs entry_date/exit_date; ``sig`` aligns to it."""
    cfg = cfg or sizing()
    root = events["market"].iloc[0]
    mk = d.markets[root]
    ev = events[["entry_date", "exit_date"]].copy()
    mult = multiplier(root)
    n_vol = eb.vol_units(ev, mk.daily, mult, cfg)
    q = eb.size_positions(sig.reindex(ev.index), n_vol, rule, k=k)
    q = eb.cap_notional(q, ev, mk.daily, mult, cfg)
    return eb.run_backtest(ev, q, mk.daily, mk.panel, mult, ds.cost_per_side(root, scenario),
                           cfg.capital)


def combine(results: dict[str, eb.BacktestResult], start=None, end=None) -> pd.DataFrame:
    """Weekly gross/net returns of the CL+RB portfolio (sum of P&L on one capital base)."""
    cols = ["gross_ret", "net_ret", "gross_pnl", "net_pnl", "costs", "contracts_traded"]
    frames = [r.weekly[cols] for r in results.values()]
    out = pd.concat(frames, axis=1, keys=list(results)).T.groupby(level=1).sum().T
    out = out.fillna(0.0)
    if start is not None:
        out = out[out.index >= pd.Timestamp(start)]
    if end is not None:
        out = out[out.index <= pd.Timestamp(end)]
    return out


def performance(weekly: pd.DataFrame, capital: float) -> dict[str, float]:
    out = {}
    for kind in ("gross", "net"):
        r = weekly[f"{kind}_ret"]
        out[f"{kind}_ann_return"] = mt.annualized_mean(r, periods_per_year=PPY)
        out[f"{kind}_ann_vol"] = mt.annualized_volatility(r, periods_per_year=PPY)
        out[f"{kind}_sharpe"] = mt.sharpe_ratio(r, periods_per_year=PPY)
        out[f"{kind}_sortino"] = mt.sortino_ratio(r, periods_per_year=PPY)
        out[f"{kind}_max_drawdown"] = mt.max_drawdown(mt.equity_curve(r))
    years = len(weekly) / PPY
    out["weeks"] = len(weekly)
    out["costs_per_year_usd"] = float(weekly["costs"].sum() / years)
    out["contracts_traded_per_year"] = float(weekly["contracts_traded"].sum() / years)
    out["per_period_sharpe_net"] = float(weekly["net_ret"].mean() / weekly["net_ret"].std())
    return out


def random_sign_sharpes(d: ds.Dataset, results: dict[str, eb.BacktestResult], draws: int,
                        scenario: str, start=None, end=None, seed: int = 0) -> np.ndarray:
    """Net Sharpe of the same |contracts| schedule with random signs (turnover-matched)."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(draws):
        res = {}
        for root, r in results.items():
            t = r.trades
            q = t["contracts"].abs() * rng.choice([-1.0, 1.0], size=len(t))
            mk = d.markets[root]
            res[root] = eb.run_backtest(t[["entry_date", "exit_date"]], q, mk.daily, mk.panel,
                                        multiplier(root), ds.cost_per_side(root, scenario),
                                        sizing().capital)
        w = combine(res, start, end)
        out.append(mt.sharpe_ratio(w["net_ret"], periods_per_year=PPY))
    return np.array(out)
