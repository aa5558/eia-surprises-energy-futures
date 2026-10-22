"""Additional paper figures, drawn only from saved, verified result tables.

``uv run python scripts/paper_figures.py`` writes ``reports/figures/paper/``.
Presentation only: nothing here recomputes or alters research results.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from transport_energy.config import REPO_ROOT
from transport_energy.visualization import style

T5 = REPO_ROOT / "reports/tables/phase5_6"
OUT = REPO_ROOT / "reports/figures/paper"
SRC = "Source: EIA weekly data; author's calculations (out-of-sample forecast weeks 2001–2016)"


def save(fig, name: str, source: str | None = SRC) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if source:
        fig.text(0.01, -0.04, source, fontsize=7, color=style.INK_2, ha="left", va="top")
    fig.savefig(OUT / name, bbox_inches="tight")
    plt.close(fig)


def surprise_rmse() -> None:
    """Forecast RMSE of each expectation model, relative to the 5-year same-week mean."""
    t = pd.read_csv(T5 / "surprise_model_comparison.csv")
    wide = t.pivot(index="series", columns="model", values="rmse")
    rel = wide.div(wide["five_year"], axis=0)
    order = ["demand", "distillate", "gasoline", "crude"]
    labels = {"demand": "Gasoline demand", "distillate": "Distillate stocks Δ",
              "gasoline": "Gasoline stocks Δ", "crude": "Crude stocks Δ"}
    models = [("five_year", "5-year same-week mean (EIA benchmark)"),
              ("seasonal", "Seasonal regression"),
              ("seasonal_ar", "Seasonal + AR(1) (selected)")]
    y = np.arange(len(order))
    h = 0.26
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for i, (m, lab) in enumerate(models):
        vals = rel.loc[order, m].to_numpy()
        ax.barh(y + (1 - i) * h, vals, height=h * 0.92, color=style.SERIES[i], label=lab)
        if m == "seasonal_ar":
            for yy, v in zip(y + (1 - i) * h, vals, strict=True):
                ax.annotate(f"{v:.2f}", (v, yy), xytext=(4, 0), textcoords="offset points",
                            va="center", fontsize=8, color=style.INK_2)
    ax.set_yticks(y, [labels[s] for s in order])
    ax.set_xlim(0, 1.12)
    ax.axvline(1.0, color=style.NEUTRAL, lw=0.8)
    ax.set_xlabel("RMSE relative to the 5-year same-week mean (lower is better)")
    ax.set_title("Expectation models for EIA weekly data: out-of-sample forecast error", pad=26)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, fontsize=7)
    save(fig, "surprise_model_rmse.png")


def timeline() -> None:
    """Schematic of the event windows (illustrative, not data)."""
    fig, ax = plt.subplots(figsize=(8.6, 2.5))
    ax.set_xlim(-0.6, 12.4)
    ax.set_ylim(-1.6, 1.9)
    ax.axis("off")
    ax.grid(False)
    ax.plot([-0.3, 12.1], [0, 0], color=style.INK_2, lw=1.2)
    pts = [(0, "Fri F", "data week ends"), (3.2, "Tue 14:30", "settlement $P_{pre}$"),
           (7.2, "Wed 14:30", "settlement = entry"),
           (11.6, "Tue 14:30", "exit, before next release")]
    for x, top, bottom in pts:
        ax.plot([x, x], [-0.12, 0.12], color=style.INK, lw=1.4)
        ax.text(x, 0.3, top, ha="center", va="bottom", fontsize=8, color=style.INK)
        ax.text(x, -0.3, bottom, ha="center", va="top", fontsize=7.5, color=style.INK_2)
    ax.plot([5.2], [0], marker="v", ms=9, color=style.SERIES[1])
    ax.text(5.2, 0.3, "Wed 10:30", ha="center", va="bottom", fontsize=8, color=style.INK)
    ax.text(5.2, -0.3, "EIA release", ha="center", va="top", fontsize=7.5,
            color=style.SERIES[1])
    ax.annotate("", xy=(7.2, 1.15), xytext=(3.2, 1.15),
                arrowprops=dict(arrowstyle="<->", color=style.SERIES[0], lw=1.6))
    ax.text(5.2, 1.3, "announcement window (Q1, not tradable)", ha="center", fontsize=8,
            color=style.SERIES[0])
    ax.annotate("", xy=(11.6, -1.1), xytext=(7.2, -1.1),
                arrowprops=dict(arrowstyle="<->", color=style.SERIES[2], lw=1.6))
    ax.text(9.4, -1.45, "drift window (Q2, tradable with daily settlements)", ha="center",
            fontsize=8, color=style.SERIES[2])
    save(fig, "event_timeline.png",
         source="Schematic. Exact release times come from EIA's documented schedules "
                "(791 of 793 editions); otherwise windows assume the whole release day.")


def primary_equity() -> None:
    """Primary strategy in the locked test: cumulative gross vs net return and drawdown."""
    w = pd.read_csv(REPO_ROOT / "reports/tables/phase7/primary_weekly_test.csv",
                    parse_dates=["week_ending"]).set_index("week_ending")
    gross, net = w["gross_ret"].cumsum() * 100, w["net_ret"].cumsum() * 100
    eq = 1 + w["net_ret"].cumsum()
    dd = (eq / eq.cummax() - 1) * 100
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(8, 4.4), sharex=True,
                                  gridspec_kw={"height_ratios": [2.2, 1]})
    ax.plot(gross.index, gross, color=style.SERIES[0], label="gross of costs")
    ax.plot(net.index, net, color=style.SERIES[1], label="net of base costs")
    ax.axhline(0, color=style.NEUTRAL, lw=0.8)
    ax.set_ylabel("cumulative return,\n% of $1M")
    ax.set_title("Primary strategy (Rule A), locked test 2017-01 – 2024-04", pad=24)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    ax2.fill_between(dd.index, dd, 0, color=style.SERIES[1], alpha=0.45, lw=0)
    ax2.set_ylabel("net drawdown, %")
    fig.tight_layout()
    save(fig, "primary_equity_test.png",
         source="Source: reports/tables/phase7/primary_weekly_test.csv (non-compounded weekly "
                "returns on a $1M base)")


def main() -> None:
    style.apply()
    surprise_rmse()
    timeline()
    primary_equity()


if __name__ == "__main__":
    main()
