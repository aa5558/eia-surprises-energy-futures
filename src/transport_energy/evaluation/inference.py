"""Statistical inference for weekly, serially dependent data.

* OLS with Newey-West (HAC) standard errors: residuals of overlapping or
  heteroskedastic returns are not iid, so plain OLS standard errors are too small.
* Holm (family-wise error) and Benjamini-Hochberg (false discovery rate) corrections.
* Out-of-sample R^2 (Campbell-Thompson), Clark-West (nested models) and
  Diebold-Mariano (non-nested) forecast comparisons, all with HAC variances.
* Stationary bootstrap (Politis-Romano) for confidence intervals of statistics of
  dependent series, e.g. a Sharpe ratio.
* Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014): probability that the true
  Sharpe exceeds the best one expected by chance after N trials.
* Hansen (2005) SPA test: is the best of K strategies better than a benchmark after
  accounting for having searched over K?
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.multitest import multipletests


def nw_lags(n: int, horizon: int = 1) -> int:
    """Newey-West (1994) plug-in lag, at least ``horizon - 1`` for overlapping returns."""
    return max(int(math.floor(4 * (n / 100) ** (2 / 9))), horizon - 1)


@dataclass(frozen=True)
class RegResult:
    params: pd.Series
    se: pd.Series
    tvalues: pd.Series
    pvalues: pd.Series
    nobs: int
    rsquared: float
    lags: int


def ols_hac(y: pd.Series, X: pd.DataFrame, horizon: int = 1, add_const: bool = True
            ) -> RegResult:
    """OLS of y on X (rows with any NaN dropped) with Newey-West standard errors."""
    data = pd.concat([y.rename("_y"), X], axis=1).dropna()
    Xm = sm.add_constant(data.drop(columns="_y"), has_constant="add") if add_const else \
        data.drop(columns="_y")
    lags = nw_lags(len(data), horizon)
    fit = sm.OLS(data["_y"], Xm).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return RegResult(fit.params, fit.bse, fit.tvalues, fit.pvalues, int(fit.nobs),
                     float(fit.rsquared), lags)


def adjust_pvalues(p: pd.Series) -> pd.DataFrame:
    """Holm and Benjamini-Hochberg adjusted p-values for one hypothesis family."""
    ok = p.notna()
    out = pd.DataFrame({"p": p, "p_holm": np.nan, "p_bh": np.nan})
    if ok.any():
        out.loc[ok, "p_holm"] = multipletests(p[ok], method="holm")[1]
        out.loc[ok, "p_bh"] = multipletests(p[ok], method="fdr_bh")[1]
    return out


def oos_r2(y: np.ndarray, f_model: np.ndarray, f_bench: np.ndarray) -> float:
    """1 - MSE(model) / MSE(benchmark); > 0 means the model beat the benchmark OOS."""
    y, fm, fb = (np.asarray(a, float) for a in (y, f_model, f_bench))
    return float(1 - np.mean((y - fm) ** 2) / np.mean((y - fb) ** 2))


def _hac_mean_t(d: np.ndarray, lags: int) -> tuple[float, float]:
    """Mean of d and its HAC t-statistic (Bartlett kernel)."""
    d = np.asarray(d, float)
    n = len(d)
    u = d - d.mean()
    var = u @ u / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * (u[k:] @ u[:-k]) / n
    se = math.sqrt(max(var, 1e-300) / n)
    return float(d.mean()), float(d.mean() / se)


def clark_west(y, f_small, f_big, horizon: int = 1) -> dict[str, float]:
    """Clark-West (2007) test that the larger nested model has lower MSPE (one-sided)."""
    y, fs, fb = (np.asarray(a, float) for a in (y, f_small, f_big))
    f = (y - fs) ** 2 - ((y - fb) ** 2 - (fs - fb) ** 2)
    _, t = _hac_mean_t(f, nw_lags(len(f), horizon))
    return {"cw_t": t, "p_one_sided": float(1 - stats.norm.cdf(t))}


def diebold_mariano(e1, e2, horizon: int = 1) -> dict[str, float]:
    """DM test of equal squared-error loss; positive t means model 2 is more accurate."""
    d = np.asarray(e1, float) ** 2 - np.asarray(e2, float) ** 2
    mean, t = _hac_mean_t(d, nw_lags(len(d), horizon))
    return {"dm_mean_loss_diff": mean, "dm_t": t, "p_two_sided": float(2 * (1 - stats.norm.cdf(
        abs(t))))}


def stationary_bootstrap_indices(n: int, mean_block: float, rng: np.random.Generator
                                 ) -> np.ndarray:
    """One resample of positions 0..n-1 in blocks of geometric length (mean ``mean_block``)."""
    p = 1.0 / mean_block
    idx = np.empty(n, dtype=int)
    idx[0] = rng.integers(n)
    restart = rng.random(n) < p
    starts = rng.integers(n, size=n)
    for t in range(1, n):
        idx[t] = starts[t] if restart[t] else (idx[t - 1] + 1) % n
    return idx


def sharpe(x: np.ndarray, periods_per_year: float) -> float:
    sd = np.std(x, ddof=1)
    return float(np.mean(x) / sd * math.sqrt(periods_per_year)) if sd > 0 else float("nan")


def bootstrap_sharpe_ci(returns, periods_per_year: float, mean_block: float = 8.0,
                        reps: int = 5000, alpha: float = 0.05, seed: int = 0
                        ) -> dict[str, float]:
    """Percentile CI for the annualized Sharpe ratio under the stationary bootstrap.

    Also returns the bootstrap probability that the Sharpe is <= 0.
    """
    x = np.asarray(returns, float)
    x = x[~np.isnan(x)]
    rng = np.random.default_rng(seed)
    draws = np.array([sharpe(x[stationary_bootstrap_indices(len(x), mean_block, rng)],
                             periods_per_year) for _ in range(reps)])
    draws = draws[~np.isnan(draws)]
    return {"sharpe": sharpe(x, periods_per_year),
            "ci_low": float(np.quantile(draws, alpha / 2)),
            "ci_high": float(np.quantile(draws, 1 - alpha / 2)),
            "p_sharpe_le_0": float(np.mean(draws <= 0))}


def expected_max_sharpe(n_trials: int, var_trials: float) -> float:
    """E[max of N iid N(0, var) Sharpe estimates] (Bailey & Lopez de Prado 2014, eq. 2)."""
    if n_trials < 2:
        return 0.0
    g = 0.5772156649
    z1 = stats.norm.ppf(1 - 1 / n_trials)
    z2 = stats.norm.ppf(1 - 1 / (n_trials * math.e))
    return math.sqrt(var_trials) * ((1 - g) * z1 + g * z2)


def deflated_sharpe(returns, n_trials: int, var_trials: float) -> dict[str, float]:
    """Probability that the per-period Sharpe exceeds the expected max under the null.

    ``var_trials`` is the variance of the *per-period* Sharpe ratios across trials.
    """
    x = np.asarray(returns, float)
    x = x[~np.isnan(x)]
    n = len(x)
    sr = float(np.mean(x) / np.std(x, ddof=1))
    skew = float(stats.skew(x))
    kurt = float(stats.kurtosis(x, fisher=False))
    sr0 = expected_max_sharpe(n_trials, var_trials)
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr ** 2, 1e-12))
    z = (sr - sr0) * math.sqrt(n - 1) / denom
    return {"sr_per_period": sr, "sr0_per_period": sr0, "dsr": float(stats.norm.cdf(z)),
            "n_trials": n_trials}


def spa_test(perf: pd.DataFrame, mean_block: float = 8.0, reps: int = 5000, seed: int = 0
             ) -> dict[str, float]:
    """Hansen (2005) SPA test, consistent p-value.

    ``perf`` columns are strategies, rows periods, values are performance *relative to
    the benchmark* (e.g. excess returns over a zero-return benchmark). H0: no strategy
    has positive expected relative performance.
    """
    d = perf.dropna().to_numpy(float)
    n, _ = d.shape
    dbar = d.mean(axis=0)
    rng = np.random.default_rng(seed)
    boots = np.empty((reps, d.shape[1]))
    for b in range(reps):
        boots[b] = d[stationary_bootstrap_indices(n, mean_block, rng)].mean(axis=0)
    omega = np.sqrt(n) * boots.std(axis=0, ddof=1)
    omega[omega == 0] = np.inf
    t_stat = max(0.0, float(np.max(np.sqrt(n) * dbar / omega)))
    thresh = -math.sqrt(2 * math.log(math.log(n)))
    # Hansen's consistent recentring: keep the mean only for strategies not clearly bad
    g = np.where(np.sqrt(n) * dbar / omega >= thresh, dbar, 0.0)
    t_boot = np.maximum(0.0, np.max(np.sqrt(n) * (boots - g) / omega, axis=1))
    return {"spa_stat": t_stat, "p_consistent": float(np.mean(t_boot >= t_stat)),
            "best": str(perf.columns[int(np.argmax(dbar))]), "n_strategies": d.shape[1]}
