"""One chart style for every figure in the project (matplotlib, static PNG).

Colours are the validated reference palette's light-mode categorical slots, used in
fixed order. Charts with more than three series on screen at once are avoided or
faceted; text uses ink colours, never series colours.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6",
          "#e34948"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
NEUTRAL = "#8c8b86"


def apply() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 11, "axes.titleweight": "bold", "axes.labelsize": 9,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "xtick.color": INK_2, "ytick.color": INK_2, "xtick.labelsize": 8,
        "ytick.labelsize": 8, "legend.fontsize": 8, "legend.frameon": False,
        "lines.linewidth": 1.6, "font.size": 9, "figure.dpi": 110, "savefig.dpi": 160,
        "axes.prop_cycle": matplotlib.cycler(color=SERIES),
    })


def save(fig, path: Path, source: str = "Source: U.S. Energy Information Administration (EIA)"
         ) -> None:
    fig.text(0.01, 0.005, source, fontsize=7, color=INK_2, ha="left", va="bottom")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
