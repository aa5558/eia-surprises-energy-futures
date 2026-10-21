"""Phase 5 models and the shared machinery the locked test reuses unchanged.

Everything follows docs/04_analysis_protocol.md. Functions take the event table from
``analysis.datasets`` and never look past the information each step is allowed to use:

* surprise-model choice uses fundamentals only;
* forecasts are walk-forward: refit every January on events whose *exit* settlement is
  before that January, predict that year's events;
* the trading signal standardises each forecast by the dispersion of the *training*
  fitted values from the same refit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

from transport_energy.analysis import datasets as ds
from transport_energy.evaluation import inference as inf
from transport_energy.features import surprises as su

SURPRISES = ("crude", "gasoline", "distillate", "demand")
CONTROLS = ("mom1", "mom4", "rv", "carry")
LAMBDAS = tuple(np.logspace(-2, 3, 10))
PRECISE_START = pd.Timestamp("2011-08-01")


# --------------------------------------------------------------------------- surprises
def surprise_model_comparison(d: ds.Dataset, start: str = "2001-01-01",
                              end: str = "2016-12-31") -> tuple[pd.DataFrame, dict[str, str]]:
    """RMSE of each expectation model over common forecast weeks; DM vs the best."""
    rows, choice = [], {}
    for short, tab in d.surprises.items():
        t = tab[(tab.index >= start) & (tab.index <= end)]
        cols = [f"s_{m}" for m in su.MODELS]
        t = t.dropna(subset=cols)
        rmse = {m: float(np.sqrt(np.mean(t[f"s_{m}"] ** 2))) for m in su.MODELS}
        best = min(rmse, key=rmse.get)
        choice[short] = best
        for m in su.MODELS:
            dm = (inf.diebold_mariano(t[f"s_{m}"], t[f"s_{best}"]) if m != best
                  else {"dm_t": np.nan, "p_two_sided": np.nan})
            rows.append({"series": short, "model": m, "weeks": len(t), "rmse": rmse[m],
                         "bias": float(t[f"s_{m}"].mean()), "chosen": m == best,
                         "dm_t_vs_best": dm["dm_t"], "dm_p_vs_best": dm["p_two_sided"]})
    return pd.DataFrame(rows), choice


def z_columns(choice: dict[str, str], stale: bool = False) -> list[str]:
    pre = "z4" if stale else "z"
    return [f"{pre}_{s}_{choice[s]}" for s in SURPRISES]


def primary_events(ev: pd.DataFrame) -> pd.DataFrame:
    """One row per (market, week): precise timing when archived, conservative otherwise."""
    prec = ev[ev["timing"] == "precise"]
    cons = ev[(ev["timing"] == "conservative")]
    keyed = set(zip(prec["market"], prec["week"], strict=True))
    cons = cons[[(m, w) not in keyed for m, w in zip(cons["market"], cons["week"],
                                                       strict=True)]]
    cons = cons[cons["week"] < PRECISE_START]
    return pd.concat([cons, prec]).sort_values(["market", "week"]).reset_index(drop=True)


# --------------------------------------------------------------------------- regressions
def family_regressions(ev: pd.DataFrame, zcols: list[str], label: str) -> pd.DataFrame:
    """Primary family: 2 markets x 2 windows x 4 surprise coefficients (Newey-West)."""
    rows = []
    for m in ("CL", "RB"):
        e = ev[ev["market"] == m]
        for w in ("ann", "drift"):
            X = e[zcols].copy()
            if w == "drift":
                X = X.join(e[[f"{m.lower()}_entry_{c}" for c in CONTROLS]])
            y = e[f"{m.lower()}_{w}"]
            res = inf.ols_hac(y, X)
            for z in zcols:
                rows.append({"sample": label, "market": m, "window": w,
                             "surprise": z.split("_")[1], "coef": res.params[z],
                             "se_hac": res.se[z], "t": res.tvalues[z], "p": res.pvalues[z],
                             "nobs": res.nobs, "r2": res.rsquared, "nw_lags": res.lags})
    out = pd.DataFrame(rows)
    adj = inf.adjust_pvalues(out["p"])
    return out.assign(p_holm=adj["p_holm"], p_bh=adj["p_bh"])


def secondary_regressions(ev: pd.DataFrame, choice: dict[str, str], label: str
                          ) -> pd.DataFrame:
    rows = []
    cl = ev[ev["market"] == "CL"]
    zc = f"z_crude_{choice['crude']}"
    for w in ("ann", "drift"):
        res = inf.ols_hac(cl[f"cl_spread_{w}"], cl[[zc]])
        rows.append({"family": "calendar_spread", "test": f"crude_z -> CL spread ({w})",
                     "coef": res.params[zc], "t": res.tvalues[zc], "p": res.pvalues[zc],
                     "nobs": res.nobs})
    fam = pd.DataFrame(rows)
    fam[["p_holm"]] = inf.adjust_pvalues(fam["p"])[["p_holm"]]
    rows = []
    for m, short in (("CL", "crude"), ("RB", "gasoline")):
        e = ev[ev["market"] == m]
        z, st = e[f"z_{short}_{choice[short]}"], e[f"state_{short}"]
        X = pd.DataFrame({"s": z, "L": st, "sxL": z * st})
        for w in ("ann", "drift"):
            res = inf.ols_hac(e[f"{m.lower()}_{w}"], X)
            rows.append({"family": "H4_inventory_state",
                         "test": f"{short} surprise x state -> {m} ({w})",
                         "coef": res.params["sxL"], "t": res.tvalues["sxL"],
                         "p": res.pvalues["sxL"], "nobs": res.nobs,
                         "beta_s": res.params["s"], "t_s": res.tvalues["s"]})
    h4 = pd.DataFrame(rows)
    h4[["p_holm"]] = inf.adjust_pvalues(h4["p"])[["p_holm"]]
    return pd.concat([fam, h4], ignore_index=True).assign(sample=label)


def h4_terciles(ev: pd.DataFrame, choice: dict[str, str], label: str) -> pd.DataFrame:
    """Pre-set robustness check: slope on s in bottom vs top expanding tercile of L."""
    rows = []
    for m, short in (("CL", "crude"), ("RB", "gasoline")):
        e = ev[ev["market"] == m].sort_values("week")
        st = e[f"state_{short}"]
        q1 = st.expanding(min_periods=52).quantile(1 / 3).shift(1)
        q2 = st.expanding(min_periods=52).quantile(2 / 3).shift(1)
        for name, mask in (("low_stocks", st <= q1), ("high_stocks", st >= q2)):
            g = e[mask]
            res = inf.ols_hac(g[f"{m.lower()}_ann"], g[[f"z_{short}_{choice[short]}"]])
            rows.append({"sample": label, "market": m, "tercile": name, "nobs": res.nobs,
                         "slope": res.params.iloc[1], "t": res.tvalues.iloc[1]})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- forecasts
def _xy(e: pd.DataFrame, m: str, cols: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    X = e[cols].to_numpy(float)
    y = e[f"{m.lower()}_drift"].to_numpy(float)
    ok = ~np.isnan(X).any(axis=1)
    return X, y, ok


def _ols(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def _ridge(Xs, y, lam):
    # intercept unpenalised: centre y, ridge on standardised X
    n, p = Xs.shape
    yc = y - y.mean()
    beta = np.linalg.solve(Xs.T @ Xs + lam * np.eye(p), Xs.T @ yc)
    return y.mean(), beta


def walk_forward(ev: pd.DataFrame, market: str, zcols: list[str], years: list[int],
                 lam: float, gbm: bool = False) -> pd.DataFrame:
    """Out-of-sample drift forecasts for each event in ``years`` (annual refits).

    Training set for year Y: events of this market whose exit settlement is before
    1 January Y and whose drift return is observed.
    """
    e = ev[ev["market"] == market].sort_values("week")
    ctrl = [f"{market.lower()}_entry_{c}" for c in CONTROLS]
    out = []
    for year in years:
        cut = pd.Timestamp(year, 1, 1)
        train = e[(e["exit_date"] < cut) & e[f"{market.lower()}_drift"].notna()]
        test = e[e["week"].dt.year == year]
        if test.empty or len(train) < 100:
            continue
        pred = pd.DataFrame(index=test.index)
        pred["m0"] = train[f"{market.lower()}_drift"].mean()
        sd, mean_fit = {}, {}
        for name, cols in (("m1", ctrl), ("m2", ctrl + zcols)):
            X, y, ok = _xy(train, market, cols)
            ok &= ~np.isnan(y)
            beta = _ols(X[ok], y[ok])
            Xt, _, okt = _xy(test, market, cols)
            p = beta[0] + Xt @ beta[1:]
            pred[name] = np.where(okt, p, np.nan)
            fit = beta[0] + X[ok] @ beta[1:]
            sd[name], mean_fit[name] = float(np.std(fit, ddof=1)), float(np.mean(fit))
        X, y, ok = _xy(train, market, ctrl + zcols)
        ok &= ~np.isnan(y)
        mu, sdv = X[ok].mean(axis=0), X[ok].std(axis=0, ddof=1)
        icpt, b = _ridge((X[ok] - mu) / sdv, y[ok], lam)
        Xt, _, okt = _xy(test, market, ctrl + zcols)
        pred["m3"] = np.where(okt, icpt + ((Xt - mu) / sdv) @ b, np.nan)
        fit = icpt + ((X[ok] - mu) / sdv) @ b
        sd["m3"], mean_fit["m3"] = float(np.std(fit, ddof=1)), float(np.mean(fit))
        logit = LogisticRegression(C=1.0, max_iter=1000).fit((X[ok] - mu) / sdv, y[ok] > 0)
        prob = logit.predict_proba(np.nan_to_num((Xt - mu) / sdv))[:, 1]
        pred["m4_prob_up"] = np.where(okt, prob, np.nan)
        if gbm:
            g = GradientBoostingRegressor(n_estimators=200, max_depth=2, learning_rate=0.05,
                                          subsample=0.8, random_state=0).fit(X[ok], y[ok])
            pred["m5"] = np.where(okt, g.predict(np.nan_to_num(Xt)), np.nan)
        for name in ("m1", "m2", "m3"):
            pred[f"sd_fit_{name}"] = sd[name]
            pred[f"mean_fit_{name}"] = mean_fit[name]
        pred["refit_year"] = year
        pred["n_train"] = int(ok.sum())
        out.append(pred)
    preds = pd.concat(out)
    keep = ["market", "week", "timing", "entry_date", "exit_date", f"{market.lower()}_drift"]
    return e.loc[preds.index, keep].join(preds).rename(
        columns={f"{market.lower()}_drift": "drift"})


def forecast_metrics(p: pd.DataFrame, label: str, models=("m1", "m2", "m3")) -> pd.DataFrame:
    rows = []
    for m in p["market"].unique():
        g = p[(p["market"] == m)].dropna(subset=["drift", *models])
        y = g["drift"].to_numpy()
        row = {"sample": label, "market": m, "n": len(g)}
        for mod in models:
            row[f"oos_r2_{mod}_vs_m0"] = inf.oos_r2(y, g[mod], g["m0"])
        for big in [x for x in models if x != "m1"]:
            cw = inf.clark_west(y, g["m1"], g[big])
            row[f"cw_t_{big}_vs_m1"], row[f"cw_p_{big}_vs_m1"] = cw["cw_t"], cw["p_one_sided"]
        if "m2" in models and "m3" in models:
            dm = inf.diebold_mariano(y - g["m2"], y - g["m3"])
            row["dm_t_m3_better_than_m2"] = dm["dm_t"]
        if "m4_prob_up" in g:
            prob = g["m4_prob_up"].clip(1e-6, 1 - 1e-6)
            up = (y > 0).astype(float)
            base = np.clip(up.mean(), 1e-6, 1 - 1e-6)
            row["m4_hit_rate"] = float(((prob > 0.5) == (y > 0)).mean())
            row["m4_up_share"] = float(up.mean())
            row["m4_logloss"] = float(-np.mean(up * np.log(prob) + (1 - up) * np.log(1 - prob)))
            row["base_logloss"] = float(-np.mean(up * np.log(base) + (1 - up) * np.log(1 - base)))
        row["mse_m0"] = float(np.mean((y - g["m0"]) ** 2))
        for mod in models:
            row[f"mse_{mod}"] = float(np.mean((y - g[mod]) ** 2))
        rows.append(row)
    return pd.DataFrame(rows)


def signal(p: pd.DataFrame, model: str) -> pd.Series:
    """Standardised *conditional* forecast, known at the refit.

    z = (forecast - mean fitted value) / sd of fitted values, both from the same
    refit's training sample. Subtracting the mean removes the unconditional drift
    (already the always-long benchmark), so the signal measures only what the
    surprises and controls add. (Amendment A1, docs/04 §9: without it a heavily
    shrunk model turned into a constant-sign bet on the historical mean.)
    """
    return (p[model] - p[f"mean_fit_{model}"]) / p[f"sd_fit_{model}"]
