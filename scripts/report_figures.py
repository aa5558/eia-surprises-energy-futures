"""Report figures drawn from saved result tables only (no recomputation).

``uv run python scripts/report_figures.py`` reads ``reports/tables/phase5_6`` and
``reports/tables/phase7`` and writes ``reports/figures/report/``. It lives outside
``src/`` so the frozen evaluation code is untouched.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from transport_energy.config import REPO_ROOT
from transport_energy.visualization import style

T5, T7 = REPO_ROOT / "reports/tables/phase5_6", REPO_ROOT / "reports/tables/phase7"
OUT = REPO_ROOT / "reports/figures/report"
SRC = "Source: EIA (fundamentals, NYMEX settlements); author's calculations"


def save(fig, name: str) -> None:
    """Like style.save, but the source line sits below the x-axis label."""
    OUT.mkdir(parents=True, exist_ok=True)
    fig.text(0.01, -0.04, SRC, fontsize=7, color=style.INK_2, ha="left", va="top")
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


def coef_dev_vs_test() -> None:
    dev = pd.read_csv(T5 / "primary_family_development.csv")
    dev = dev[dev["sample"] == "development_precise_2011_2016"]
    test = pd.read_csv(T7 / "primary_family_test.csv")
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), sharey=True)
    for ax, (m, w) in zip(axes, (("CL", "ann"), ("RB", "ann")), strict=True):
        surprises = ["crude", "gasoline", "distillate", "demand"]
        y = np.arange(len(surprises))
        for i, (frame, lab, off) in enumerate(((dev, "development 2011–16", 0.15),
                                               (test, "locked test 2017–24", -0.15))):
            g = frame[(frame["market"] == m) & (frame["window"] == w)].set_index("surprise")
            g = g.loc[surprises]
            ax.errorbar(g["coef"] * 100, y + off, xerr=1.96 * g["se_hac"] * 100, fmt="o",
                        ms=5, color=style.SERIES[i], lw=1.2, label=lab)
        ax.axvline(0, color=style.NEUTRAL, lw=0.8)
        ax.set_yticks(y, [f"{s} surprise" for s in surprises])
        ax.set_xlabel("% return per 1 sd of surprise (95% HAC CI)")
        ax.set_title(f"{m}: release-day (announcement) reaction", fontsize=9)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.98), ncol=2)
    fig.tight_layout()
    save(fig, "q1_dev_vs_test.png")


def family_t() -> None:
    f = pd.read_csv(T7 / "primary_family_test.csv").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(8, 4.4))
    y = np.arange(len(f))
    sig = f["p_holm"] < 0.05
    ax.scatter(f.loc[~sig, "t"], y[~sig], color=style.SERIES[0], s=30, label="not significant")
    ax.scatter(f.loc[sig, "t"], y[sig], color=style.SERIES[1], s=45, marker="D",
               label="Holm p < 0.05")
    for x in (-1.96, 1.96):
        ax.axvline(x, color=style.NEUTRAL, lw=0.8, ls="--")
    ax.axvline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_yticks(y, [f"{r.market} {r.window}: {r.surprise}" for r in f.itertuples()],
                  fontsize=7)
    ax.set_xlabel("Newey–West t-statistic (dashed: ±1.96 unadjusted)")
    ax.set_title("Primary hypothesis family, locked test 2017–2024 (16 tests)")
    ax.legend(loc="lower right")
    save(fig, "family_t_test.png")


def strategy_dev_vs_test() -> None:
    dev = pd.read_csv(T5 / "strategy_validation_2006_2016.csv").set_index("strategy")
    test = pd.read_csv(T7 / "strategy_test.csv").set_index("strategy")
    names = [("PRIMARY_ruleA", "PRIMARY_ruleA", "Rule A (primary)"),
             ("ruleB_m3", "ruleB_vol_scaled", "Rule B"),
             ("bench_price_only_m1_k1.5", "bench_price_only_m1", "Price-only"),
             ("bench_always_long", "bench_always_long", "Always long")]
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(8, 3.4))
    d = [dev.loc[a, "net_sharpe"] for a, _, _ in names]
    t = [test.loc[b, "net_sharpe"] for _, b, _ in names]
    ax.barh(y + 0.2, d, height=0.36, color=style.SERIES[0], label="development validation 2006–16")
    ax.barh(y - 0.2, t, height=0.36, color=style.SERIES[1], label="locked test 2017–24")
    for yy, v in zip(y + 0.2, d, strict=True):
        ax.annotate(f"{v:+.2f}", (v, yy), xytext=(4 if v >= 0 else -4, 0),
                    textcoords="offset points", ha="left" if v >= 0 else "right",
                    va="center", fontsize=8, color=style.INK_2)
    for yy, v in zip(y - 0.2, t, strict=True):
        ax.annotate(f"{v:+.2f}", (v, yy), xytext=(4 if v >= 0 else -4, 0),
                    textcoords="offset points", ha="left" if v >= 0 else "right",
                    va="center", fontsize=8, color=style.INK_2)
    ax.axvline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_yticks(y, [n for _, _, n in names])
    ax.set_xlim(-1.0, 1.0)
    ax.set_xlabel("annualised net Sharpe ratio (base costs)")
    ax.set_title("Strategies: development validation vs locked test", pad=26)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    save(fig, "strategy_dev_vs_test.png")


def robustness() -> None:
    r = pd.read_csv(T7 / "robustness_test.csv")
    s = pd.read_csv(T7 / "strategy_test.csv").set_index("strategy")
    r = pd.concat([pd.DataFrame([{"variant": "PRIMARY", "net_sharpe":
                                  s.loc["PRIMARY_ruleA", "net_sharpe"]}]), r])
    r = r.iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    y = np.arange(len(r))
    colors = [style.SERIES[1] if v == "PRIMARY" else
              style.SERIES[2] if v.startswith("placebo") else style.SERIES[0]
              for v in r["variant"]]
    ax.scatter(r["net_sharpe"], y, color=colors, s=32)
    ax.axvline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_yticks(y, r["variant"], fontsize=7)
    ax.set_xlabel("annualised net Sharpe ratio, locked test")
    ax.set_title("Pre-registered robustness grid (orange: primary; green: placebos)")
    save(fig, "robustness_test.png")


def main() -> None:
    style.apply()
    coef_dev_vs_test()
    family_t()
    strategy_dev_vs_test()
    robustness()


if __name__ == "__main__":
    main()
