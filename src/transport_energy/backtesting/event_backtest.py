"""Weekly event strategies: signal -> contracts -> daily contract-aware P&L -> weekly returns.

Sizing (docs/01 §3.9; capital and targets from configs/research.yaml):

* ``n_vol``: contracts whose dollar volatility over the holding period equals the
  weekly volatility target, ``sigma* = vol_target / sqrt(52) * capital``. The
  per-contract volatility uses the trailing 60-day std of daily held-contract returns,
  known at the entry settlement.
* **Rule A (threshold)**: ``q = direction * sign(z) * 1{|z| > k} * n_vol``. Long, short
  or no trade.
* **Rule B (volatility-scaled)**: ``q = direction * clip(z, -2, 2) * n_vol``. With
  ``z = r_hat / sd(r_hat)`` this is proportional to ``r_hat / sigma^2`` (forecast over
  variance), capped at twice the target risk.

Contracts are rounded to integers and capped so gross notional stays below
``max_gross_notional_multiple * capital``. P&L comes from ``backtesting.pnl.futures_pnl``
(within-contract price changes, roll trades charged), never from spliced series.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from transport_energy.backtesting.pnl import futures_pnl
from transport_energy.strategies.rules import events_to_daily_positions


@dataclass(frozen=True)
class SizingConfig:
    capital: float = 1_000_000.0
    vol_target_annual: float = 0.10
    max_gross_notional_multiple: float = 2.0
    vol_lookback: int = 60

    @property
    def weekly_dollar_vol(self) -> float:
        return self.vol_target_annual / np.sqrt(52) * self.capital


def trailing_vol(daily: pd.DataFrame, lookback: int) -> pd.Series:
    """Std of daily held-contract returns over the last ``lookback`` days, known at close."""
    return daily["ret"].rolling(lookback, min_periods=lookback // 2).std(ddof=1)


def vol_units(events: pd.DataFrame, daily: pd.DataFrame, multiplier: float,
              cfg: SizingConfig) -> pd.Series:
    """Contracts per unit of signal (``n_vol``) at each event's entry settlement."""
    vol = trailing_vol(daily, cfg.vol_lookback)
    days = daily.index
    n = []
    for _, ev in events.iterrows():
        e, x = ev["entry_date"], ev["exit_date"]
        if pd.isna(e) or pd.isna(x) or e not in days:
            n.append(0.0)
            continue
        hold = days.get_loc(x) - days.get_loc(e)
        price = daily.at[e, "p_held"]
        sig = vol.at[e]
        if not (price > 0 and sig > 0 and hold > 0):
            n.append(0.0)
            continue
        per_contract = sig * np.sqrt(hold) * price * multiplier
        n.append(cfg.weekly_dollar_vol / per_contract)
    return pd.Series(n, index=events.index, name="n_vol")


def size_positions(signal: pd.Series, n_vol: pd.Series, rule: str, k: float = 1.0,
                   direction: float = 1.0) -> pd.Series:
    z = signal.to_numpy(float)
    nv = n_vol.to_numpy(float)
    if rule == "threshold":
        raw = np.where(np.isnan(z), 0.0, np.sign(z) * (np.abs(z) > k)) * nv
    elif rule == "vol_scaled":
        raw = np.where(np.isnan(z), 0.0, np.clip(z, -2, 2)) * nv
    elif rule == "always_long":
        raw = nv.copy()
    else:
        raise ValueError(f"unknown rule {rule!r}")
    q = np.round(direction * raw)
    return pd.Series(q, index=signal.index, name="contracts")


def cap_notional(q: pd.Series, events: pd.DataFrame, daily: pd.DataFrame, multiplier: float,
                 cfg: SizingConfig) -> pd.Series:
    price = daily["p_held"].reindex(events["entry_date"]).to_numpy(float)
    cap = np.floor(cfg.max_gross_notional_multiple * cfg.capital / (np.abs(price) * multiplier))
    cap = np.where(np.isfinite(cap), cap, 0.0)
    return pd.Series(np.clip(q.to_numpy(), -cap, cap), index=q.index, name="contracts")


@dataclass
class BacktestResult:
    daily: pd.DataFrame       # gross_pnl, contracts_traded, costs, net_pnl, position, held
    weekly: pd.DataFrame      # gross / net returns on the capital base, per week
    trades: pd.DataFrame      # one row per event with a position


def run_backtest(events: pd.DataFrame, contracts: pd.Series, daily: pd.DataFrame,
                 panel: pd.DataFrame, multiplier: float, cost_per_side: float,
                 capital: float) -> BacktestResult:
    """Daily P&L of the event positions, aggregated to weeks ending Tuesday.

    ``panel`` is (date x contract) settlements; ``daily`` the output of
    ``features.events.contract_daily``. Events whose holding window lacks a settlement
    for the held contract are skipped (flat) and counted in ``trades.skipped``.
    """
    days = daily.index
    ok = events["entry_date"].notna() & events["exit_date"].notna()
    q = contracts.where(ok, 0.0)
    # skip events whose held contract lacks a settlement inside the window
    ret = daily["ret"]
    skipped = []
    for i, ev in events[ok].iterrows():
        w = ret.loc[(days > ev["entry_date"]) & (days <= ev["exit_date"])]
        if w.isna().any():
            skipped.append(i)
    q.loc[skipped] = 0.0
    pos = events_to_daily_positions(events, q, days)
    pnl = futures_pnl(pos, daily["held"], panel, multiplier, cost_per_side)
    pnl["position"] = pos
    pnl["held"] = daily["held"]
    wk = pnl[["gross_pnl", "costs", "net_pnl", "contracts_traded"]].resample("W-TUE").sum()
    wk["gross_ret"] = wk["gross_pnl"] / capital
    wk["net_ret"] = wk["net_pnl"] / capital
    trades = events.assign(contracts=q, skipped=events.index.isin(skipped))
    trade_pnl = []
    for _, ev in trades.iterrows():
        if ev["contracts"] == 0 or pd.isna(ev["entry_date"]):
            trade_pnl.append(np.nan)
            continue
        sel = (days >= ev["entry_date"]) & (days <= ev["exit_date"])
        trade_pnl.append(float(pnl.loc[sel, "net_pnl"].sum()))
    trades["net_pnl"] = trade_pnl
    return BacktestResult(pnl, wk, trades)


def summarize(result: BacktestResult, capital: float, periods_per_year: int = 52) -> dict:
    """Gross and net performance, costs and turnover on the fixed capital base."""
    from transport_energy.evaluation import metrics as m

    wk = result.weekly
    out = {}
    for kind in ("gross", "net"):
        r = wk[f"{kind}_ret"]
        eq = m.equity_curve(r)
        out[f"{kind}_ann_return"] = m.annualized_mean(r, periods_per_year=periods_per_year)
        out[f"{kind}_ann_vol"] = m.annualized_volatility(r, periods_per_year=periods_per_year)
        out[f"{kind}_sharpe"] = m.sharpe_ratio(r, periods_per_year=periods_per_year)
        out[f"{kind}_sortino"] = m.sortino_ratio(r, periods_per_year=periods_per_year)
        out[f"{kind}_max_drawdown"] = m.max_drawdown(eq)
    years = len(wk) / periods_per_year
    t = result.trades
    traded = t[t["contracts"] != 0]
    out.update({
        "weeks": len(wk),
        "trades": int(len(traded)),
        "pct_weeks_in_market": float(len(traded) / max(len(t), 1)),
        "contracts_traded_per_year": float(wk["contracts_traded"].sum() / years),
        "costs_per_year_usd": float(wk["costs"].sum() / years),
        "cost_drag_ann": float(wk["costs"].sum() / years / capital),
        "skipped_events": int(t["skipped"].sum()),
    })
    out.update({f"trade_{k}": v for k, v in m.trade_statistics(traded["net_pnl"]).items()})
    return out
