"""Phase 7: the single locked out-of-sample evaluation, 2017-01 -> 2024-04-05.

Run once, after ``configs/frozen_spec.yaml`` is committed and tagged::

    TEQ_UNLOCK_TEST=spec-freeze-v1 uv run python -m transport_energy.analysis.locked_test

Refuses to run if the code or the frozen spec differ from the tag, so the evaluated
procedure is exactly the frozen one. Everything is pre-specified in
docs/04_analysis_protocol.md §6–8; outputs go to ``reports/tables/phase7`` and
``reports/figures/phase7`` as produced.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from transport_energy.analysis import datasets as ds
from transport_energy.analysis import modeling as md
from transport_energy.analysis import strategy as st
from transport_energy.config import REPO_ROOT
from transport_energy.evaluation import inference as inf
from transport_energy.evaluation import metrics as mt
from transport_energy.integrity import UNLOCK_ENV_VAR, is_test_unlocked
from transport_energy.visualization import style

log = logging.getLogger("locked_test")
TAB = REPO_ROOT / "reports" / "tables" / "phase7"
FIG = REPO_ROOT / "reports" / "figures" / "phase7"
TEST_YEARS = list(range(2017, 2025))
START, END = "2017-01-01", "2024-04-05"
PERM_DRAWS, RANDOM_SIGN_DRAWS = 1000, 1000


def _tab(df: pd.DataFrame, name: str) -> None:
    TAB.mkdir(parents=True, exist_ok=True)
    df.to_csv(TAB / name, index=False)
    log.info("table %s (%d rows)", name, len(df))


def verify_frozen() -> str:
    tag = os.environ.get(UNLOCK_ENV_VAR, "")
    if not is_test_unlocked():
        raise SystemExit(f"locked: set {UNLOCK_ENV_VAR} to an existing spec-freeze-* tag")
    diff = subprocess.run(["git", "diff", "--stat", tag, "--", "src", "configs"],
                          cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    if diff.strip():
        raise SystemExit(f"code/config differ from {tag}; refusing to run:\n{diff}")
    return tag


def winsorize_causal(z: pd.Series, lo=0.01, hi=0.99, min_periods=104) -> pd.Series:
    """Clip at expanding quantiles of *past* values only."""
    past = z.shift(1).expanding(min_periods=min_periods)
    return z.clip(past.quantile(lo), past.quantile(hi))


def forecasts(prim: pd.DataFrame, zcols: list[str], lam: float) -> pd.DataFrame:
    p = pd.concat([md.walk_forward(prim, m, zcols, TEST_YEARS, lam) for m in ("CL", "RB")])
    return p[(p["week"] >= START)].reset_index(drop=True)


def run(d: ds.Dataset, preds: pd.DataFrame, sig: pd.Series, rule: str, k: float,
        scenario: str = "base", entry_shift: str | None = None) -> dict:
    results = {}
    for mk in ("CL", "RB"):
        sel = preds["market"] == mk
        ev = preds[sel].copy()
        if entry_shift is not None:
            days = d.markets[mk].daily.index
            if entry_shift == "next_day":
                pos = days.get_indexer(ev["entry_date"]) + 1
                ev["entry_date"] = [days[i] if 0 < i < len(days) else pd.NaT for i in pos]
            elif entry_shift == "monday":
                mon = ev["entry_date"] + pd.to_timedelta((7 - ev["entry_date"].dt.weekday) % 7,
                                                          unit="D")
                mon = mon.where(ev["entry_date"].dt.weekday != 0,
                                ev["entry_date"] + pd.Timedelta(days=7))
                ev["entry_date"] = [days[days.searchsorted(x)] if x <= days[-1] else pd.NaT
                                    for x in mon]
            bad = ev["entry_date"].isna() | (ev["entry_date"] >= ev["exit_date"])
            ev.loc[bad, ["entry_date", "exit_date"]] = pd.NaT
        results[mk] = st.run_market(d, ev, sig[sel], rule, k, scenario)
    return results


def perf_of(results, start=START, end=END, drop=None) -> tuple[dict, pd.DataFrame]:
    w = st.combine(results, start, end)
    if drop is not None:
        w = w[~((w.index >= drop[0]) & (w.index <= drop[1]))]
    p = st.performance(w, st.sizing().capital)
    for mk, r in results.items():
        wm = st.combine({mk: r}, start, end)
        p[f"net_sharpe_{mk}"] = mt.sharpe_ratio(wm["net_ret"], periods_per_year=52)
    return p, w


def year_block_permutation(sig: pd.Series, preds: pd.DataFrame, rng) -> pd.Series:
    out = pd.Series(np.nan, index=sig.index)
    for mk in ("CL", "RB"):
        sel = preds["market"] == mk
        s = sig[sel]
        years = preds.loc[sel, "week"].dt.year
        blocks = [s[years == y].to_numpy() for y in sorted(years.unique())]
        order = rng.permutation(len(blocks))
        vals = np.concatenate([blocks[i] for i in order])
        out[sel] = vals
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    style.apply()
    tag = verify_frozen()
    spec = yaml.safe_load((REPO_ROOT / "configs" / "frozen_spec.yaml").read_text())
    zcols, lam, model, k = (spec["z_columns"], float(spec["ridge_lambda"]),
                            spec["forecast_model"], float(spec["threshold_k"]))
    choice = spec["surprise_models"]
    summary = {"tag": tag, "spec": spec}

    d = ds.build("full")
    ev = d.events
    test_ev = ev[(ev["week"] >= START) & (ev["entry_date"] <= END)]
    prec, cons = test_ev[test_ev["timing"] == "precise"], test_ev[test_ev["timing"] ==
                                                                  "conservative"]

    # --- hypothesis families (confirmatory: precise test sample)
    fam = md.family_regressions(prec, zcols, "test_precise_2017_2024")
    _tab(fam, "primary_family_test.csv")
    _tab(md.family_regressions(cons, zcols, "test_conservative_2017_2024"),
         "primary_family_test_conservative.csv")
    _tab(md.secondary_regressions(prec, choice, "test_precise"), "secondary_families_test.csv")
    _tab(md.h4_terciles(prec, choice, "test_precise"), "h4_terciles_test.csv")

    # --- forecasts (walk-forward with frozen hyper-parameters)
    prim = md.primary_events(ev)
    preds = forecasts(prim, zcols, lam)
    _tab(preds, "walk_forward_predictions_test.csv")
    met = md.forecast_metrics(preds, "test_2017_2024")
    _tab(met, "forecast_metrics_test.csv")

    # --- primary strategy and comparators
    sig = {m: md.signal(preds, m) for m in ("m1", "m2", "m3")}
    rows, weekly = [], {}

    def record(name, results, **kw):
        p, w = perf_of(results, **kw)
        rows.append({"strategy": name, **p})
        weekly[name] = w["net_ret"]
        return p, w

    res_primary = run(d, preds, sig[model], "threshold", k)
    p_primary, w_primary = record("PRIMARY_ruleA", res_primary)
    record("ruleB_vol_scaled", run(d, preds, sig[model], "vol_scaled", 0.0))
    record("bench_always_long", run(d, preds, pd.Series(1.0, index=preds.index),
                                    "always_long", 0.0))
    record("bench_price_only_m1", run(d, preds, sig["m1"], "threshold", k))
    _tab(pd.DataFrame(rows), "strategy_test.csv")

    # trade-level detail and gross vs net
    trades = pd.concat([r.trades.assign(market=mk) for mk, r in res_primary.items()])
    _tab(trades, "primary_trades_test.csv")
    _tab(w_primary.reset_index(names="week_ending"), "primary_weekly_test.csv")

    # --- inference on the primary metric
    boot = inf.bootstrap_sharpe_ci(w_primary["net_ret"], 52, mean_block=8, reps=5000)
    dsr = inf.deflated_sharpe(w_primary["net_ret"], spec["dsr_inputs"]["n_trials"],
                              spec["dsr_inputs"]["var_per_period_sharpe"])
    rs = st.random_sign_sharpes(d, res_primary, RANDOM_SIGN_DRAWS, "base", START, END)
    summary["primary"] = {**p_primary, "bootstrap": boot, "deflated_sharpe": dsr,
                          "random_sign_pctile": float(np.mean(rs < p_primary["net_sharpe"]))}
    _tab(pd.DataFrame({"random_sign_net_sharpe": rs}), "random_sign_test.csv")

    # --- robustness grid (fixed list, docs/04 §7)
    rob = []

    def variant(name, results, **kw):
        p, w = perf_of(results, **kw)
        rob.append({"variant": name, **p})
        weekly[f"rob::{name}"] = w["net_ret"]

    for sc in ("optimistic", "conservative", "stress"):
        variant(f"cost_{sc}", run(d, preds, sig[model], "threshold", k, sc))
    for kk in (0.5, 1.0, 1.5):
        variant(f"k_{kk}", run(d, preds, sig[model], "threshold", kk))
    variant("entry_next_day", run(d, preds, sig[model], "threshold", k,
                                  entry_shift="next_day"))
    variant("placebo_late_entry_monday", run(d, preds, sig[model], "threshold", k,
                                             entry_shift="monday"))
    stale = forecasts(prim, md.z_columns(choice, stale=True), lam)
    variant("placebo_stale_signal_lag4",
            run(d, stale, md.signal(stale, model), "threshold", k))
    # cross-target: each market traded on the other market's forecast for the same week
    other = preds.assign(market=preds["market"].map({"CL": "RB", "RB": "CL"}))
    cross = preds.merge(other[["market", "week", model, f"sd_fit_{model}"]],
                        on=["market", "week"], how="left", suffixes=("", "_x"))
    variant("placebo_cross_target",
            run(d, preds, cross[f"{model}_x"] / cross[f"sd_fit_{model}_x"], "threshold", k))
    for alt in ("five_year", "seasonal", "seasonal_ar"):
        cols = [f"z_{s}_{alt}" for s in md.SURPRISES]
        pa = forecasts(prim, cols, lam)
        variant(f"surprise_model_{alt}", run(d, pa, md.signal(pa, model), "threshold", k))
    wz = prim.copy()
    for c in zcols:
        for mk in ("CL", "RB"):
            sel = wz["market"] == mk
            wz.loc[sel, c] = winsorize_causal(wz.loc[sel, c])
    pw = forecasts(wz, zcols, lam)
    variant("winsorized_surprises", run(d, pw, md.signal(pw, model), "threshold", k))
    variant("excl_2020H1", res_primary, drop=(pd.Timestamp("2020-01-01"),
                                              pd.Timestamp("2020-06-30")))
    variant("sub_2017_2019", res_primary, start="2017-01-01", end="2019-12-31")
    variant("sub_2020_2024", res_primary, start="2020-01-01", end=END)
    pc = prim[~((prim["week"] >= START) & (prim["timing"] == "precise"))]
    pc = pd.concat([pc, ev[(ev["week"] >= START) & (ev["timing"] == "conservative")]])
    pcf = forecasts(pc, zcols, lam)
    variant("conservative_timing", run(d, pcf, md.signal(pcf, model), "threshold", k))
    for n in (3, 10):
        dn = ds.build("full", roll_days=n)
        pn = forecasts(md.primary_events(dn.events), zcols, lam)
        variant(f"roll_offset_{n}", run(dn, pn, md.signal(pn, model), "threshold", k))
    _tab(pd.DataFrame(rob), "robustness_test.csv")

    # year-block permutation null for the primary net Sharpe
    rng = np.random.default_rng(0)
    perm = []
    for _ in range(PERM_DRAWS):
        ps = year_block_permutation(sig[model], preds, rng)
        perm.append(perf_of(run(d, preds, ps, "threshold", k))[0]["net_sharpe"])
    perm = np.array(perm)
    summary["year_block_permutation_p"] = float(np.mean(perm >= p_primary["net_sharpe"]))
    _tab(pd.DataFrame({"perm_net_sharpe": perm}), "year_block_permutation_test.csv")

    # SPA across the strategy variants actually tradable (placebos excluded)
    cols = {n: s for n, s in weekly.items()
            if not ("placebo" in n or "excl_" in n or "sub_" in n or "bench" in n)}
    spa_df = pd.DataFrame(cols).fillna(0.0)
    summary["spa"] = inf.spa_test(spa_df, mean_block=8, reps=5000)

    c1 = boot["ci_low"] > 0
    c2 = dsr["dsr"] > 0.95
    c3 = summary["spa"]["p_consistent"] < 0.05
    summary["verdict"] = {"ci_above_zero": bool(c1), "dsr_above_0.95": bool(c2),
                          "spa_p_below_0.05": bool(c3),
                          "works_out_of_sample": bool(c1 and c2 and c3)}
    (TAB / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    figures(weekly, w_primary, rs, perm, p_primary, fam, k, model)
    log.info("verdict: %s", summary["verdict"])


def figures(weekly, w_primary, rs, perm, p_primary, fam, k, model) -> None:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    names = (("PRIMARY_ruleA", f"Rule A ({model}, k={k})"), ("ruleB_vol_scaled", "Rule B"),
             ("bench_always_long", "Always long"))
    for i, (n, lab) in enumerate(names):
        ax.plot(weekly[n].index, weekly[n].cumsum() * 100, color=style.SERIES[i], label=lab)
    ax.axhline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_ylabel("cumulative net return, % of $1M")
    ax.set_title("Locked out-of-sample test, 2017-01 – 2024-04 (base costs)")
    ax.legend(loc="upper left")
    style.save(fig, FIG / "test_equity.png")

    fig, ax = plt.subplots(figsize=(8, 2.8))
    eq = mt.equity_curve(w_primary["net_ret"])
    ax.fill_between(eq.index, mt.drawdown(eq) * 100, 0, color=style.SERIES[1], alpha=0.5, lw=0)
    ax.set_ylabel("drawdown, %")
    ax.set_title("Primary strategy drawdown (test)")
    style.save(fig, FIG / "test_drawdown.png")

    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2))
    for ax, (vals, lab) in zip(axes, ((rs, "random signs, same turnover"),
                                      (perm, "year-block permuted signals")), strict=True):
        ax.hist(vals, bins=40, color=style.SERIES[0], alpha=0.75)
        ax.axvline(p_primary["net_sharpe"], color=style.INK, lw=1.6)
        ax.annotate("primary", (p_primary["net_sharpe"], ax.get_ylim()[1] * 0.9),
                    xytext=(4, 0), textcoords="offset points", fontsize=8, color=style.INK)
        ax.set_title(f"Null: {lab}", fontsize=9)
        ax.set_xlabel("net Sharpe (annualised)")
        ax.set_yticks([])
    fig.tight_layout()
    style.save(fig, FIG / "test_null_distributions.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    f = fam.reset_index(drop=True)
    labels = [f"{r.market} {r.window}: {r.surprise}" for r in f.itertuples()]
    y = np.arange(len(f))
    ax.errorbar(f["t"], y, fmt="o", color=style.SERIES[0], ms=5)
    for x in (-1.96, 1.96):
        ax.axvline(x, color=style.NEUTRAL, lw=0.8, ls="--")
    ax.axvline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_yticks(y, labels, fontsize=7)
    ax.set_xlabel("Newey–West t-statistic (dashed: ±1.96, unadjusted)")
    ax.set_title("Primary hypothesis family, locked test (precise timing)")
    style.save(fig, FIG / "test_family_t_stats.png")


if __name__ == "__main__":
    main()
