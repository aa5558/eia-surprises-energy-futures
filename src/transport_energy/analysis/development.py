"""Phases 5–6 on the development sample: every selection the protocol allows, logged.

``uv run python -m transport_energy.analysis.development`` writes tables to
``reports/tables/phase5_6/``, figures to ``reports/figures/phase5_6/``, the experiment
registry to ``reports/tables/experiments_development.csv`` and the candidate frozen
specification to ``configs/frozen_spec.yaml``. Nothing here reads 2017+ data.
"""

from __future__ import annotations

import json
import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from transport_energy.analysis import datasets as ds
from transport_energy.analysis import modeling as md
from transport_energy.analysis import strategy as st
from transport_energy.config import REPO_ROOT
from transport_energy.evaluation import metrics as mt
from transport_energy.integrity import guard_development
from transport_energy.visualization import style

log = logging.getLogger("dev")
TAB = REPO_ROOT / "reports" / "tables" / "phase5_6"
FIG = REPO_ROOT / "reports" / "figures" / "phase5_6"
VAL_YEARS = list(range(2006, 2017))
VAL_START, VAL_END = "2006-01-01", "2016-12-31"
K_GRID = (0.5, 1.0, 1.5)


def _tab(df: pd.DataFrame, name: str) -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    df.to_csv(TAB / name, index=False)
    log.info("table %s (%d rows)", name, len(df))


class Registry:
    """Every specification evaluated on development returns (feeds DSR / SPA)."""

    def __init__(self):
        self.rows: list[dict] = []

    def add(self, kind: str, spec: str, **metrics) -> None:
        self.rows.append({"id": len(self.rows) + 1, "kind": kind, "spec": spec, **metrics})

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    style.apply()
    reg = Registry()
    d = ds.build("development")
    guard_development(pd.DatetimeIndex(d.events["exit_date"].dropna()))   # belt and braces

    # 1. surprise models (fundamentals only)
    sm, choice = md.surprise_model_comparison(d)
    _tab(sm, "surprise_model_comparison.csv")
    zcols = md.z_columns(choice)

    ev = d.events
    prec = ev[ev["timing"] == "precise"]
    cons = ev[ev["timing"] == "conservative"]

    # 2. primary family, in-sample, both timing regimes
    fam = pd.concat([md.family_regressions(prec, zcols, "development_precise_2011_2016"),
                     md.family_regressions(cons, zcols, "development_conservative_1996_2016")])
    _tab(fam, "primary_family_development.csv")
    for _, r in fam.iterrows():
        reg.add("regression", f"{r['sample']}|{r['market']}|{r['window']}|{r['surprise']}",
                t=r["t"], p=r["p"])
    sec = pd.concat([md.secondary_regressions(prec, choice, "development_precise"),
                     md.secondary_regressions(cons, choice, "development_conservative")])
    _tab(sec, "secondary_families_development.csv")
    _tab(pd.concat([md.h4_terciles(prec, choice, "development_precise"),
                    md.h4_terciles(cons, choice, "development_conservative")]),
         "h4_terciles_development.csv")

    # 3. walk-forward forecasts; ridge penalty by pooled validation MSE
    prim = md.primary_events(ev)
    lam_rows, preds_by_lam = [], {}
    for lam in md.LAMBDAS:
        p = pd.concat([md.walk_forward(prim, m, zcols, VAL_YEARS, lam) for m in ("CL", "RB")])
        preds_by_lam[lam] = p
        met = md.forecast_metrics(p, f"lambda={lam:.4g}")
        rel = float((met["mse_m3"] / met["mse_m0"]).sum())
        lam_rows.append({"lambda": lam, "pooled_rel_mse_m3": rel})
        reg.add("ridge_penalty", f"lambda={lam:.4g}", pooled_rel_mse=rel)
    lam_tab = pd.DataFrame(lam_rows)
    lam = float(lam_tab.loc[lam_tab["pooled_rel_mse_m3"].idxmin(), "lambda"])
    _tab(lam_tab, "ridge_lambda_selection.csv")
    preds = preds_by_lam[lam]
    met = md.forecast_metrics(preds, "development_validation_2006_2016")
    run_gbm = bool(((met["cw_p_m2_vs_m1"] < 0.05) | (met["cw_p_m3_vs_m1"] < 0.05)).any())
    if run_gbm:
        preds = pd.concat([md.walk_forward(prim, m, zcols, VAL_YEARS, lam, gbm=True)
                           for m in ("CL", "RB")])
        met = md.forecast_metrics(preds, "development_validation_2006_2016",
                                  models=("m1", "m2", "m3", "m5"))
    _tab(met, "forecast_metrics_development.csv")
    pooled = {m: float((met[f"mse_{m}"] / met["mse_m0"]).sum()) for m in ("m2", "m3")}
    model = min(pooled, key=pooled.get)
    for m in ("m1", "m2", "m3"):
        reg.add("forecast_model", m, **{
            f"oos_r2_{mk}": float(met.loc[met["market"] == mk, f"oos_r2_{m}_vs_m0"].iloc[0])
            for mk in ("CL", "RB")})

    # 4. strategies on validation years (pseudo out-of-sample; base costs for selection)
    preds = preds.reset_index(drop=True)
    sig = {m: md.signal(preds, m) for m in ("m1", "m2", "m3")}
    perf_rows, curves = [], {}

    def evaluate(name, rule, k, signal_name, scenario="base"):
        results = {}
        for mk in ("CL", "RB"):
            sel = preds["market"] == mk
            events = preds[sel]
            s = sig[signal_name][sel] if signal_name else pd.Series(1.0, index=events.index)
            results[mk] = st.run_market(d, events, s, rule, k, scenario)
        w = st.combine(results, VAL_START, VAL_END)
        perf = st.performance(w, st.sizing().capital)
        for mk, r in results.items():
            wm = st.combine({mk: r}, VAL_START, VAL_END)
            perf[f"net_sharpe_{mk}"] = mt.sharpe_ratio(wm["net_ret"], periods_per_year=52)
        perf_rows.append({"strategy": name, "rule": rule, "k": k, "signal": signal_name,
                          "scenario": scenario, **perf})
        reg.add("strategy", f"{name}|{rule}|k={k}|{signal_name}|{scenario}",
                net_sharpe=perf["net_sharpe"], gross_sharpe=perf["gross_sharpe"],
                per_period_sharpe_net=perf["per_period_sharpe_net"])
        curves[name] = w
        return perf, results

    k_scores = {}
    for k in K_GRID:
        perf, _ = evaluate(f"ruleA_{model}_k{k}", "threshold", k, model)
        k_scores[k] = perf["net_sharpe"]
    k_best = max(k_scores, key=lambda x: (np.nan_to_num(k_scores[x], nan=-np.inf), -x))
    _, res_primary = evaluate("PRIMARY_ruleA", "threshold", k_best, model)
    evaluate(f"ruleB_{model}", "vol_scaled", 0.0, model)
    evaluate("bench_always_long", "always_long", 0.0, None)
    evaluate(f"bench_price_only_m1_k{k_best}", "threshold", k_best, "m1")
    for sc in ("optimistic", "conservative", "stress"):
        evaluate(f"PRIMARY_ruleA_{sc}", "threshold", k_best, model, sc)
    rs = st.random_sign_sharpes(d, res_primary, 200, "base", VAL_START, VAL_END)
    perf_tab = pd.DataFrame(perf_rows)
    perf_tab["random_sign_pctile_of_primary"] = np.nan
    prim_sr = perf_tab.loc[perf_tab["strategy"] == "PRIMARY_ruleA", "net_sharpe"].iloc[0]
    perf_tab.loc[perf_tab["strategy"] == "PRIMARY_ruleA", "random_sign_pctile_of_primary"] = \
        float(np.mean(rs < prim_sr))
    _tab(perf_tab, "strategy_validation_2006_2016.csv")
    _tab(pd.DataFrame({"random_sign_net_sharpe": rs}), "random_sign_validation.csv")
    _tab(preds, "walk_forward_predictions_development.csv")

    # equity curves (validation, labelled as such)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    for i, (name, lab) in enumerate((("PRIMARY_ruleA", f"Rule A ({model}, k={k_best})"),
                                     (f"ruleB_{model}", f"Rule B ({model})"),
                                     ("bench_always_long", "Always long"))):
        w = curves[name]
        ax.plot(w.index, w["net_ret"].cumsum() * 100, color=style.SERIES[i], label=lab)
    ax.axhline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_ylabel("cumulative net return, % of $1M")
    ax.set_title("Development validation 2006–2016 (walk-forward, base costs; not out-of-sample)")
    ax.legend(loc="upper left")
    style.save(fig, FIG / "validation_equity.png")

    # 5. registry and candidate frozen spec
    regf = reg.frame()
    regf.to_csv(REPO_ROOT / "reports" / "tables" / "experiments_development.csv", index=False)
    strat = regf[regf["kind"] == "strategy"]
    v1 = REPO_ROOT / "reports" / "tables" / "experiments_development_v1.csv"
    if v1.exists():   # amendment A1: earlier trials still count against us
        old = pd.read_csv(v1)
        strat = pd.concat([strat, old[old["kind"] == "strategy"]], ignore_index=True)
    spec = {
        "frozen_on": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "protocol": "docs/04_analysis_protocol.md",
        "surprise_models": choice,
        "z_columns": zcols,
        "ridge_lambda": lam,
        "forecast_model": model,
        "gbm_triggered": run_gbm,
        "primary_rule": "threshold",
        "threshold_k": float(k_best),
        "secondary_rule": "vol_scaled",
        "roll_business_days": 5,
        "cost_scenario_primary": "base",
        "walk_forward": "annual refit each January on events with exit < 1 Jan; expanding",
        "test_window": {"start": "2017-01-01", "end": "2024-04-05"},
        "dsr_inputs": {"n_trials": int(len(strat)),
                       "var_per_period_sharpe": float(strat["per_period_sharpe_net"].var())},
        "success_criteria": "bootstrap 95% CI of primary net Sharpe > 0 AND DSR > 0.95 AND "
                            "SPA p < 0.05",
    }
    (REPO_ROOT / "configs" / "frozen_spec.yaml").write_text(
        "# Frozen specification for the locked test (generated by analysis.development).\n"
        + yaml.safe_dump(spec, sort_keys=False))
    log.info("spec: %s", json.dumps(spec, default=str))


if __name__ == "__main__":
    main()
