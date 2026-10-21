"""Phase 4 exploratory analysis, development sample only (data through 2016-12-31).

``uv run python -m transport_energy.analysis.eda`` writes figures to
``reports/figures/eda/`` and tables to ``reports/tables/eda/``.
"""

from __future__ import annotations

import logging
import warnings

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.stattools import acf, adfuller, kpss

from transport_energy.analysis import datasets as ds
from transport_energy.config import REPO_ROOT
from transport_energy.evaluation.inference import ols_hac
from transport_energy.features import surprises as su
from transport_energy.integrity import guard_development
from transport_energy.visualization import style

log = logging.getLogger("eda")
FIG = REPO_ROOT / "reports" / "figures" / "eda"
TAB = REPO_ROOT / "reports" / "tables" / "eda"
START = pd.Timestamp("1996-01-01")
LABEL = {"demand": "Gasoline product supplied (kb/d)",
         "crude": "Crude stocks ex-SPR, weekly change (kb)",
         "gasoline": "Gasoline stocks, weekly change (kb)",
         "distillate": "Distillate stocks, weekly change (kb)"}


def _tab(df: pd.DataFrame, name: str, index: bool = False) -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    df.to_csv(TAB / name, index=index)
    log.info("table %s", name)


def series(d: ds.Dataset) -> dict[str, pd.Series]:
    """Development weekly series from 1996: demand level and the three stock changes."""
    w = d.weekly
    out = {"demand": su.regular_weekly(w["gasoline_product_supplied"])}
    for short, name in (("crude", "crude_stocks_ex_spr"), ("gasoline", "gasoline_stocks"),
                        ("distillate", "distillate_stocks")):
        out[short] = su.regular_weekly(w[name]).diff()
    return {k: guard_development(v[v.index >= START]) for k, v in out.items()}


def fig_demand(s: dict[str, pd.Series]) -> None:
    d = s["demand"]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.plot(d.index, d, color=style.SERIES[0], lw=0.8, alpha=0.6, label="Weekly")
    ax.plot(d.index, d.rolling(52).mean(), color=style.INK, lw=1.8, label="52-week mean")
    ax.set_title("US gasoline product supplied, 1996–2016")
    ax.set_ylabel("thousand barrels per day")
    ax.legend(loc="lower right")
    style.save(fig, FIG / "01_demand_level.png")


def week_of_year(idx: pd.DatetimeIndex) -> np.ndarray:
    return np.minimum((idx.dayofyear - 1) // 7 + 1, 52)


def fig_seasonality(s: dict[str, pd.Series]) -> pd.DataFrame:
    fig, axes = plt.subplots(2, 2, figsize=(9, 5.5), sharex=True)
    rows = []
    for ax, key in zip(axes.flat, ("demand", "crude", "gasoline", "distillate"), strict=True):
        x = s[key].dropna()
        if key == "demand":   # remove the slow trend: deviation from the trailing 52w mean
            x = (x - x.rolling(52, min_periods=40).mean()).dropna()
        g = x.groupby(week_of_year(x.index))
        q = g.quantile([0.25, 0.5, 0.75]).unstack()
        ax.fill_between(q.index, q[0.25], q[0.75], color=style.SERIES[0], alpha=0.18, lw=0)
        ax.plot(q.index, g.mean(), color=style.SERIES[0], lw=1.6)
        ax.axhline(0, color=style.NEUTRAL, lw=0.8)
        title = ("Demand minus trailing 52-week mean (kb/d)" if key == "demand"
                 else LABEL[key])
        ax.set_title(title, fontsize=9)
        f = stats.f_oneway(*[v.to_numpy() for _, v in g])
        rows.append({"series": key, "anova_F_week_of_year": f.statistic, "p_value": f.pvalue,
                     "peak_week": int(g.mean().idxmax()), "trough_week": int(g.mean().idxmin()),
                     "seasonal_amplitude": float(g.mean().max() - g.mean().min())})
    for ax in axes[1]:
        ax.set_xlabel("week of year")
    fig.suptitle("Seasonal pattern by week of year, 1996–2016 (line: mean; band: IQR)",
                 fontsize=11, fontweight="bold", color=style.INK)
    fig.tight_layout()
    style.save(fig, FIG / "02_seasonality.png")
    return pd.DataFrame(rows)


def holiday_effects(s: dict[str, pd.Series]) -> pd.DataFrame:
    """Holiday-week effects controlling for week-of-year seasonality (HAC t-stats)."""
    rows = []
    for key in ("demand", "crude", "gasoline", "distillate"):
        x = s[key].dropna()
        if key == "demand":
            x = (x - x.rolling(52, min_periods=40).mean()).dropna()
        X = pd.get_dummies(pd.Series(week_of_year(x.index), index=x.index), prefix="w",
                           drop_first=True, dtype=float)
        H = su.holiday_dummies(x.index)
        res = ols_hac(x, X.join(H))
        for h in su.HOLIDAYS:
            rows.append({"series": key, "holiday": h, "effect": res.params[h],
                         "se_hac": res.se[h], "t": res.tvalues[h], "p": res.pvalues[h],
                         "n_holiday_weeks": int(H[h].sum())})
    return pd.DataFrame(rows)


def fig_holidays(h: pd.DataFrame) -> None:
    d = h[h["series"] == "demand"].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(7, 3.2))
    y = np.arange(len(d))
    ax.barh(y, d["effect"], color=style.SERIES[0], height=0.55)
    ax.errorbar(d["effect"], y, xerr=1.96 * d["se_hac"], fmt="none", ecolor=style.INK, lw=1)
    ax.axvline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_yticks(y, d["holiday"])
    ax.set_xlabel("kb/d relative to a normal week of the same season (95% HAC CI)")
    ax.set_title("Holiday-week effect on gasoline product supplied, 1996–2016")
    style.save(fig, FIG / "03_holiday_effects_demand.png")


def distributions(s: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    fig, axes = plt.subplots(2, 2, figsize=(9, 5.5))
    for ax, key in zip(axes.flat, ("demand", "crude", "gasoline", "distillate"), strict=True):
        x = (s[key].diff() if key == "demand" else s[key]).dropna()
        z = (x - x.mean()) / x.std()
        jb = stats.jarque_bera(x)
        rows.append({"series": key if key != "demand" else "demand_weekly_change",
                     "n": len(x), "mean": x.mean(), "sd": x.std(), "skew": stats.skew(x),
                     "excess_kurtosis": stats.kurtosis(x), "jarque_bera_p": jb.pvalue,
                     "share_beyond_3sd": float((z.abs() > 3).mean()),
                     "normal_share_beyond_3sd": float(2 * stats.norm.sf(3))})
        ax.hist(x, bins=60, density=True, color=style.SERIES[0], alpha=0.75)
        grid = np.linspace(x.min(), x.max(), 300)
        ax.plot(grid, stats.norm.pdf(grid, x.mean(), x.std()), color=style.INK, lw=1.2,
                label="normal, same mean/sd")
        ax.set_title(("Gasoline demand, weekly change (kb/d)" if key == "demand"
                      else LABEL[key]), fontsize=9)
        ax.set_yticks([])
    axes[0, 0].legend(loc="upper left")
    fig.suptitle("Distributions of weekly changes, 1996–2016", fontsize=11,
                 fontweight="bold", color=style.INK)
    fig.tight_layout()
    style.save(fig, FIG / "04_distributions.png")
    return pd.DataFrame(rows)


def fig_rolling_vol(s: dict[str, pd.Series]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(9, 5), sharex=True)
    for ax, key in zip(axes.flat, ("demand", "crude", "gasoline", "distillate"), strict=True):
        x = s[key].diff() if key == "demand" else s[key]
        ax.plot(x.index, x.rolling(52).std(), color=style.SERIES[0])
        ax.set_title(("Gasoline demand, weekly change" if key == "demand" else LABEL[key])
                     + ": 52-week std", fontsize=9)
    fig.suptitle("Volatility of weekly fundamentals over time", fontsize=11,
                 fontweight="bold", color=style.INK)
    fig.tight_layout()
    style.save(fig, FIG / "05_rolling_volatility.png")


def stationarity(d: ds.Dataset) -> pd.DataFrame:
    w = d.weekly
    rows = []
    cands = {
        "demand_level": su.regular_weekly(w["gasoline_product_supplied"]),
        "crude_level": su.regular_weekly(w["crude_stocks_ex_spr"]),
        "gasoline_level": su.regular_weekly(w["gasoline_stocks"]),
        "distillate_level": su.regular_weekly(w["distillate_stocks"]),
    }
    for k in list(cands):
        cands[k.replace("level", "change")] = cands[k].diff()
    for name, x in cands.items():
        x = x[x.index >= START].dropna()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            adf = adfuller(x, autolag="AIC", regression="ct" if "level" in name else "c")
            kp = kpss(x, regression="ct" if "level" in name else "c", nlags="auto")
        lb = acorr_ljungbox(x, lags=[4, 12], return_df=True)
        rows.append({"series": name, "n": len(x), "adf_stat": adf[0], "adf_p": adf[1],
                     "kpss_stat": kp[0], "kpss_p": kp[1],
                     "ljung_box_q4_p": lb["lb_pvalue"].iloc[0],
                     "ljung_box_q12_p": lb["lb_pvalue"].iloc[1],
                     "deterministic": "const+trend" if "level" in name else "const"})
    return pd.DataFrame(rows)


def fig_acf(s: dict[str, pd.Series]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(9, 5), sharey=True)
    for ax, key in zip(axes.flat, ("demand", "crude", "gasoline", "distillate"), strict=True):
        x = (s[key].diff() if key == "demand" else s[key]).dropna()
        a = acf(x, nlags=12, fft=True)[1:]
        band = 1.96 / np.sqrt(len(x))
        ax.bar(np.arange(1, 13), a, color=style.SERIES[0], width=0.6)
        ax.axhspan(-band, band, color=style.NEUTRAL, alpha=0.15, lw=0)
        ax.axhline(0, color=style.NEUTRAL, lw=0.8)
        ax.set_title(("Gasoline demand, weekly change" if key == "demand" else LABEL[key]),
                     fontsize=9)
    for ax in axes[1]:
        ax.set_xlabel("lag (weeks)")
    fig.suptitle("Autocorrelation of weekly changes (band: ±1.96/√n)", fontsize=11,
                 fontweight="bold", color=style.INK)
    fig.tight_layout()
    style.save(fig, FIG / "06_autocorrelation.png")


# --------------------------------------------------------------------------- prices
def price_regimes(d: ds.Dataset) -> pd.DataFrame:
    rows = []
    for m, mk in d.markets.items():
        r = guard_development(mk.daily["ret"].dropna())
        r = r[r.index >= ds.EVENT_START[m]]
        for y, g in r.groupby(r.index.year):
            rows.append({"market": m, "year": y, "ann_vol": g.std() * np.sqrt(252),
                         "return": float(np.expm1(np.log1p(g).sum())), "days": len(g)})
    return pd.DataFrame(rows)


def fig_price_vol(reg: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.2))
    for i, m in enumerate(("CL", "RB")):
        g = reg[reg["market"] == m]
        ax.plot(g["year"], g["ann_vol"], marker="o", ms=4, color=style.SERIES[i], label=m)
        ax.annotate(m, (g["year"].iloc[-1], g["ann_vol"].iloc[-1]), xytext=(4, 0),
                    textcoords="offset points", color=style.INK_2, fontsize=8, va="center")
    ax.set_ylabel("annualised volatility of daily held-contract returns")
    ax.set_title("Front-month futures volatility by year (development sample)")
    ax.legend(loc="upper left")
    style.save(fig, FIG / "07_futures_volatility.png")


def storage_and_carry(d: ds.Dataset) -> pd.DataFrame:
    """Theory of storage: low inventories <-> backwardation (positive C1-C2 carry)."""
    ev = d.events
    rows = []
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, (m, state) in zip(axes, (("CL", "state_crude"), ("RB", "state_gasoline")),
                              strict=True):
        e = ev[(ev["market"] == m) & (ev["timing"] == "conservative")]
        x, y = e[state], e[f"{m.lower()}_entry_carry"] * 100
        ok = x.notna() & y.notna()
        x, y = x[ok], y[ok]
        rho = stats.spearmanr(x, y)
        res = ols_hac(y, x.to_frame("state"))
        rows.append({"market": m, "n": int(ok.sum()), "spearman_rho": rho.statistic,
                     "slope_pct_per_sd": res.params["state"], "t_hac": res.tvalues["state"]})
        ax.scatter(x, y, s=9, alpha=0.35, color=style.SERIES[0], lw=0)
        bins = pd.qcut(x, 10)
        b = pd.DataFrame({"x": x, "y": y}).groupby(bins, observed=True).mean()
        ax.plot(b["x"], b["y"], color=style.INK, marker="o", ms=4, lw=1.4,
                label="decile means")
        ax.axhline(0, color=style.NEUTRAL, lw=0.8)
        ax.set_xlabel("inventory vs 5-year same-week norm (z, prior week)")
        ax.set_ylabel("carry (C1 − C2) / C1, %")
        ax.set_title(f"{m}: inventories and the curve", fontsize=9)
    axes[0].legend(loc="upper right")
    fig.tight_layout()
    style.save(fig, FIG / "08_storage_carry.png")
    return pd.DataFrame(rows)


def surprise_return_corr(d: ds.Dataset) -> pd.DataFrame:
    """Raw correlations of the 5-year-mean surprises with event returns (in-sample)."""
    rows = []
    ev = d.events
    for m in ("CL", "RB"):
        for timing in ("precise", "conservative"):
            e = ev[(ev["market"] == m) & (ev["timing"] == timing)]
            for short in ("crude", "gasoline", "distillate", "demand"):
                for w in ("ann", "drift"):
                    x, y = e[f"z_{short}_five_year"], e[f"{m.lower()}_{w}"]
                    ok = x.notna() & y.notna()
                    if ok.sum() < 30:
                        continue
                    r = stats.pearsonr(x[ok], y[ok])
                    rows.append({"market": m, "timing": timing, "surprise": short, "window": w,
                                 "n": int(ok.sum()), "corr": r.statistic, "p_iid": r.pvalue})
    return pd.DataFrame(rows)


def fig_announcement(d: ds.Dataset) -> None:
    ev = d.events
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.4), sharey=False)
    for ax, (m, short, lab) in zip(axes, (("CL", "crude", "crude stock surprise"),
                                          ("RB", "gasoline", "gasoline stock surprise")),
                                   strict=True):
        e = ev[(ev["market"] == m) & (ev["timing"] == "precise")]
        x, y = e[f"z_{short}_five_year"], e[f"{m.lower()}_ann"] * 100
        ok = x.notna() & y.notna()
        ax.scatter(x[ok], y[ok], s=10, alpha=0.4, color=style.SERIES[0], lw=0)
        b = pd.DataFrame({"x": x[ok], "y": y[ok]}).groupby(pd.qcut(x[ok], 8),
                                                           observed=True).mean()
        ax.plot(b["x"], b["y"], color=style.INK, marker="o", ms=4, lw=1.4, label="octile means")
        ax.axhline(0, color=style.NEUTRAL, lw=0.8)
        ax.set_xlabel(f"{lab} (z, 5-year-mean model)")
        ax.set_ylabel("announcement-window return, %")
        ax.set_title(f"{m}: release-day reaction, 2011-08 – 2016", fontsize=9)
    axes[0].legend(loc="upper right")
    fig.tight_layout()
    style.save(fig, FIG / "09_announcement_reaction.png")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    style.apply()
    d = ds.build("development")
    s = series(d)
    fig_demand(s)
    _tab(fig_seasonality(s), "seasonality_anova.csv")
    h = holiday_effects(s)
    _tab(h, "holiday_effects.csv")
    fig_holidays(h)
    _tab(distributions(s), "distribution_stats.csv")
    fig_rolling_vol(s)
    _tab(stationarity(d), "stationarity_tests.csv")
    fig_acf(s)
    reg = price_regimes(d)
    _tab(reg, "futures_volatility_by_year.csv")
    fig_price_vol(reg)
    _tab(storage_and_carry(d), "storage_carry.csv")
    _tab(surprise_return_corr(d), "surprise_return_correlations_insample.csv")
    fig_announcement(d)


if __name__ == "__main__":
    main()
