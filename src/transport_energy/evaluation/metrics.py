"""Performance metrics. Annualization is always explicit: weekly series use 52, never 252.

Returns are simple returns on a *fixed* capital base (``pnl / capital``), not
compounded, because a futures account's P&L is not a percentage of the futures
price and the capital base is a modelling choice that must be stated.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _check_ppy(periods_per_year: float) -> None:
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive (52 weekly, 252 daily)")


def pnl_to_returns(pnl: pd.Series, capital: float) -> pd.Series:
    if capital <= 0:
        raise ValueError("capital must be positive")
    return pnl / capital


def annualized_mean(returns: pd.Series, *, periods_per_year: float) -> float:
    _check_ppy(periods_per_year)
    return float(returns.mean() * periods_per_year)


def annualized_volatility(returns: pd.Series, *, periods_per_year: float) -> float:
    _check_ppy(periods_per_year)
    return float(returns.std(ddof=1) * math.sqrt(periods_per_year))


def sharpe_ratio(returns: pd.Series, *, periods_per_year: float) -> float:
    """mean / std * sqrt(periods per year), on excess returns supplied by the caller."""
    _check_ppy(periods_per_year)
    sd = returns.std(ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return float("nan")
    return float(returns.mean() / sd * math.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, *, periods_per_year: float) -> float:
    """mean / downside deviation * sqrt(ppy); downside deviation = sqrt(mean(min(r, 0)^2))."""
    _check_ppy(periods_per_year)
    r = returns.dropna()
    downside = math.sqrt(float(np.mean(np.minimum(r, 0.0) ** 2))) if len(r) else float("nan")
    if not np.isfinite(downside) or downside == 0:
        return float("nan")
    return float(r.mean() / downside * math.sqrt(periods_per_year))


def equity_curve(returns: pd.Series, start: float = 1.0) -> pd.Series:
    """Non-compounded equity on a fixed capital base: start + cumulative sum of returns."""
    return start + returns.fillna(0.0).cumsum()


def drawdown(equity: pd.Series) -> pd.Series:
    """Fractional drawdown from the running peak (<= 0)."""
    return equity / equity.cummax() - 1.0


def max_drawdown(equity: pd.Series) -> float:
    return float(drawdown(equity).min())


def trade_statistics(trade_pnl: pd.Series) -> dict[str, float]:
    """Win rate, average gain/loss and profit factor over closed trades."""
    t = trade_pnl.dropna()
    if t.empty:
        return {"n_trades": 0, "win_rate": float("nan"), "avg_gain": float("nan"),
                "avg_loss": float("nan"), "profit_factor": float("nan")}
    gains, losses = t[t > 0], t[t < 0]
    total_loss = -losses.sum()
    return {
        "n_trades": int(len(t)),
        "win_rate": float((t > 0).mean()),
        "avg_gain": float(gains.mean()) if len(gains) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "profit_factor": float(gains.sum() / total_loss) if total_loss > 0 else float("inf"),
    }
