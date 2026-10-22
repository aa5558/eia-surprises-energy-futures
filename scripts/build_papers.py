"""Build the research paper and one-page summary PDFs from saved, verified results.

    uv run --group docs python scripts/build_papers.py

Writes ``reports/Energy_Futures_Research.pdf`` and ``reports/Research_Summary.pdf``.
Every number in the text is read from ``reports/tables/`` (or recomputed from
``data/processed/`` for one count that was not tabulated) and checked with
assertions, so the documents cannot drift from the research outputs. Presentation
only: nothing here changes research code, configuration or results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "reports" / "tables"
FIG = ROOT / "reports" / "figures"
EQ = ROOT / "reports" / "figures" / "paper" / "equations"
OUT_PAPER = ROOT / "reports" / "Energy_Futures_Research.pdf"
OUT_SUMMARY = ROOT / "reports" / "Research_Summary.pdf"

INK, INK2, RULE, ACCENT = "#0b0b0b", "#52514e", "#b9b8b3", "#2a78d6"
SHADE = "#f2f1ee"

# --------------------------------------------------------------------------- fonts
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
for name, file in (("Serif", "DejaVuSerif.ttf"), ("Serif-Bold", "DejaVuSerif-Bold.ttf"),
                   ("Serif-Italic", "DejaVuSerif-Italic.ttf"),
                   ("Serif-BoldItalic", "DejaVuSerif-BoldItalic.ttf"),
                   ("Sans", "DejaVuSans.ttf"), ("Sans-Bold", "DejaVuSans-Bold.ttf"),
                   ("Sans-Oblique", "DejaVuSans-Oblique.ttf")):
    pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
pdfmetrics.registerFontFamily("Serif", normal="Serif", bold="Serif-Bold",
                              italic="Serif-Italic", boldItalic="Serif-BoldItalic")
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans-Oblique",
                              boldItalic="Sans-Bold")


def styles(scale: float = 1.0) -> dict[str, ParagraphStyle]:
    s = scale
    return {
        "title": ParagraphStyle("title", fontName="Sans-Bold", fontSize=19 * s,
                                leading=24 * s, textColor=INK, alignment=TA_LEFT),
        "subtitle": ParagraphStyle("subtitle", fontName="Sans", fontSize=11 * s,
                                   leading=15 * s, textColor=INK2),
        "h1": ParagraphStyle("h1", fontName="Sans-Bold", fontSize=12.5 * s, leading=16 * s,
                             textColor=INK, spaceBefore=10 * s, spaceAfter=4 * s,
                             keepWithNext=1),
        "h2": ParagraphStyle("h2", fontName="Sans-Bold", fontSize=10 * s, leading=13 * s,
                             textColor=INK, spaceBefore=6 * s, spaceAfter=2 * s,
                             keepWithNext=1),
        "body": ParagraphStyle("body", fontName="Serif", fontSize=9.6 * s, leading=13.6 * s,
                               textColor=INK, alignment=TA_JUSTIFY, spaceAfter=5 * s),
        "bullet": ParagraphStyle("bullet", fontName="Serif", fontSize=9.6 * s,
                                 leading=13.4 * s, textColor=INK, leftIndent=12 * s,
                                 bulletIndent=2 * s, spaceAfter=2 * s),
        "abstract": ParagraphStyle("abstract", fontName="Serif", fontSize=9.6 * s,
                                   leading=13.8 * s, textColor=INK, alignment=TA_JUSTIFY),
        "caption": ParagraphStyle("caption", fontName="Sans", fontSize=8 * s,
                                  leading=10.5 * s, textColor=INK2, spaceBefore=2 * s,
                                  spaceAfter=8 * s),
        "tcaption": ParagraphStyle("tcaption", fontName="Sans", fontSize=8 * s,
                                   leading=10.5 * s, textColor=INK2, spaceBefore=4 * s,
                                   spaceAfter=4 * s, keepWithNext=1),
        "cell": ParagraphStyle("cell", fontName="Sans", fontSize=7.8 * s, leading=9.6 * s,
                               textColor=INK),
        "cellb": ParagraphStyle("cellb", fontName="Sans-Bold", fontSize=7.8 * s,
                                leading=9.6 * s, textColor=INK),
        "small": ParagraphStyle("small", fontName="Sans", fontSize=7.5 * s, leading=9.5 * s,
                                textColor=INK2),
        "center": ParagraphStyle("center", fontName="Sans", fontSize=9 * s, leading=12 * s,
                                 textColor=INK2, alignment=TA_CENTER),
    }


# --------------------------------------------------------------------------- numbers
def mfmt(x: float, nd: int = 2, sign: bool = False) -> str:
    """Number with a true minus sign."""
    s = f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"
    return s.replace("-", "−")


def pct(x: float, nd: int = 1, sign: bool = False) -> str:
    return mfmt(100 * x, nd, sign) + "%"


@dataclass
class Results:
    fam_test: pd.DataFrame
    fam_test_cons: pd.DataFrame
    fam_dev: pd.DataFrame
    strat_test: pd.DataFrame
    strat_dev: pd.DataFrame
    summary: dict
    fc_test: pd.DataFrame
    fc_dev: pd.DataFrame
    robust: pd.DataFrame
    surprise: pd.DataFrame
    trades: pd.DataFrame
    weekly: pd.DataFrame
    storage: pd.DataFrame
    station: pd.DataFrame
    holiday: pd.DataFrame
    assumption: pd.DataFrame
    calendar: pd.DataFrame
    first_rel: pd.DataFrame
    w2w: pd.DataFrame
    rule_cl: pd.DataFrame
    rule_rb: pd.DataFrame
    secondary_test: pd.DataFrame
    crude_change_mismatch: tuple[int, int]


def crude_change_mismatch() -> tuple[int, int]:
    """Development weeks where the printed crude-stock change != history-file change.

    Recomputed from saved processed data (not tabulated during Phase 3)."""
    first = pd.read_csv(ROOT / "data/processed/wpsr_first_release_long.csv",
                        parse_dates=["week", "release_date"])
    # development weeks = data weeks before 2017 (same definition as the Phase 3 tables)
    f = first[first["series"] == "crude_stocks_ex_spr"]
    wide = f.pivot_table(index="edition", columns="column", values="value")
    week = f[f["column"] == "current"].set_index("edition")["week"]
    chg = pd.Series((wide["current"] - wide["prior"]).to_numpy(),
                    index=pd.DatetimeIndex(week.reindex(wide.index)))
    hist = pd.read_csv(ROOT / "data/processed/eia_weekly_history.csv",
                       parse_dates=["week_ending"]).set_index("week_ending")
    h = hist["crude_stocks_ex_spr"].diff().reindex(chg.index)
    ok = (chg - h).abs() <= 0.5
    dev = chg.index < pd.Timestamp("2017-01-01")
    return int((~ok[dev]).sum()), int(dev.sum())


def load() -> Results:
    rd = lambda p, **k: pd.read_csv(TAB / p, **k)  # noqa: E731
    return Results(
        fam_test=rd("phase7/primary_family_test.csv"),
        fam_test_cons=rd("phase7/primary_family_test_conservative.csv"),
        fam_dev=rd("phase5_6/primary_family_development.csv"),
        strat_test=rd("phase7/strategy_test.csv").set_index("strategy"),
        strat_dev=rd("phase5_6/strategy_validation_2006_2016.csv").set_index("strategy"),
        summary=json.loads((TAB / "phase7/summary.json").read_text()),
        fc_test=rd("phase7/forecast_metrics_test.csv").set_index("market"),
        fc_dev=rd("phase5_6/forecast_metrics_development.csv").set_index("market"),
        robust=rd("phase7/robustness_test.csv").set_index("variant"),
        surprise=rd("phase5_6/surprise_model_comparison.csv"),
        trades=rd("phase7/primary_trades_test.csv", parse_dates=["entry_date"]),
        weekly=rd("phase7/primary_weekly_test.csv"),
        storage=rd("eda/storage_carry.csv").set_index("market"),
        station=rd("eda/stationarity_tests.csv").set_index("series"),
        holiday=rd("eda/holiday_effects.csv"),
        assumption=rd("phase3/assumption_a_summary.csv").set_index("holiday_week"),
        calendar=rd("phase3/release_calendar.csv"),
        first_rel=rd("phase3/first_release_summary.csv"),
        w2w=rd("phase3/week_to_week_revisions_development.csv"),
        rule_cl=rd("phase3/expiry_rule_vs_cme_CL.csv"),
        rule_rb=rd("phase3/expiry_rule_vs_cme_RB.csv"),
        secondary_test=rd("phase7/secondary_families_test.csv"),
        crude_change_mismatch=crude_change_mismatch(),
    )


def row(df: pd.DataFrame, market: str, window: str, surprise: str,
        sample: str | None = None) -> pd.Series:
    d = df if sample is None else df[df["sample"] == sample]
    r = d[(d["market"] == market) & (d["window"] == window) & (d["surprise"] == surprise)]
    assert len(r) == 1, (market, window, surprise, sample)
    return r.iloc[0]


def facts(R: Results) -> dict:
    """Every number quoted in the documents, computed here and cross-checked."""
    F: dict = {}
    DEV = "development_precise_2011_2016"
    g = row(R.fam_test, "RB", "ann", "gasoline")
    F["rb_gas_coef"], F["rb_gas_t"], F["rb_gas_holm"] = g["coef"], g["t"], g["p_holm"]
    gc = row(R.fam_test_cons, "RB", "ann", "gasoline")
    F["rb_gas_cons_t"], F["rb_gas_cons_holm"] = gc["t"], gc["p_holm"]
    F["cl_crude_t_test"] = row(R.fam_test, "CL", "ann", "crude")["t"]
    F["cl_crude_t_dev"] = row(R.fam_dev, "CL", "ann", "crude", DEV)["t"]
    F["cl_crude_coef_dev"] = row(R.fam_dev, "CL", "ann", "crude", DEV)["coef"]
    F["cl_crude_coef_test"] = row(R.fam_test, "CL", "ann", "crude")["coef"]
    F["rb_dem_t_dev"] = row(R.fam_dev, "RB", "ann", "demand", DEV)["t"]
    F["rb_dem_t_test"] = row(R.fam_test, "RB", "ann", "demand")["t"]
    drift = R.fam_test[R.fam_test["window"] == "drift"]
    F["drift_min_holm"] = drift["p_holm"].min()
    F["drift_max_abs_t"] = drift["t"].abs().max()
    F["n_sig_holm"] = int((R.fam_test["p_holm"] < 0.05).sum())

    S = R.summary
    p = S["primary"]
    F.update(net_sharpe=p["net_sharpe"], gross_sharpe=p["gross_sharpe"],
             ci_lo=p["bootstrap"]["ci_low"], ci_hi=p["bootstrap"]["ci_high"],
             p_le0=p["bootstrap"]["p_sharpe_le_0"], dsr=p["deflated_sharpe"]["dsr"],
             n_trials=p["deflated_sharpe"]["n_trials"],
             sr0_week=p["deflated_sharpe"]["sr0_per_period"],
             spa_p=S["spa"]["p_consistent"], spa_n=S["spa"]["n_strategies"],
             perm_p=S["year_block_permutation_p"], rs_pct=p["random_sign_pctile"],
             works=S["verdict"]["works_out_of_sample"], weeks=p["weeks"],
             net_ret=p["net_ann_return"], gross_ret=p["gross_ann_return"],
             net_vol=p["net_ann_vol"], mdd=p["net_max_drawdown"],
             sortino=p["net_sortino"], cost_yr=p["costs_per_year_usd"],
             contracts_yr=p["contracts_traded_per_year"])
    F["k"] = S["spec"]["threshold_k"]
    F["lam"] = S["spec"]["ridge_lambda"]
    tr = R.trades[R.trades["contracts"] != 0]
    F["n_trades"], F["win_rate"] = len(tr), float((tr["net_pnl"] > 0).mean())
    F["n_trades_cl"] = int((tr["market"] == "CL").sum())
    F["n_trades_rb"] = int((tr["market"] == "RB").sum())
    F["skipped"] = int(R.trades["skipped"].sum())
    F["pnl_total"] = float(tr["net_pnl"].sum())
    F["pnl_2020"] = float(tr.loc[tr["entry_date"].dt.year == 2020, "net_pnl"].sum())
    F["gross_total"] = float(R.weekly["gross_pnl"].sum())
    F["cost_total"] = float(R.weekly["costs"].sum())
    F["excl2020_sharpe"] = R.robust.loc["excl_2020H1", "net_sharpe"]
    trad = R.robust[~R.robust.index.str.startswith("placebo")]
    F["rob_min"], F["rob_max"] = trad["net_sharpe"].min(), trad["net_sharpe"].max()
    F["rob_all_negative"] = bool((trad["net_sharpe"] < 0).all())
    for nm in ("placebo_late_entry_monday", "placebo_stale_signal_lag4", "placebo_cross_target"):
        F[nm] = R.robust.loc[nm, "net_sharpe"]
    F["dev_primary"] = R.strat_dev.loc["PRIMARY_ruleA", "net_sharpe"]
    F["dev_priceonly"] = R.strat_dev.loc["bench_price_only_m1_k1.5", "net_sharpe"]
    F["dev_ruleB"] = R.strat_dev.loc["ruleB_m3", "net_sharpe"]
    F["dev_long"] = R.strat_dev.loc["bench_always_long", "net_sharpe"]
    for m in ("CL", "RB"):
        F[f"oos_m3_{m}"] = R.fc_test.loc[m, "oos_r2_m3_vs_m0"]
        F[f"hit_{m}"] = R.fc_test.loc[m, "m4_hit_rate"]
        F[f"up_{m}"] = R.fc_test.loc[m, "m4_up_share"]
    sm = R.surprise.pivot(index="series", columns="model", values="rmse")
    F["rmse"] = sm
    F["demand_reduction"] = 1 - sm.loc["demand", "seasonal_ar"] / sm.loc["demand", "five_year"]
    F["rho_cl"], F["rho_rb"] = R.storage.loc["CL", "spearman_rho"], R.storage.loc["RB",
                                                                                 "spearman_rho"]
    F["adf_crude_level_p"] = R.station.loc["crude_level", "adf_p"]
    lab = R.holiday[(R.holiday["series"] == "demand") & (R.holiday["holiday"] == "Labor Day")]
    F["labor_eff"], F["labor_t"] = lab["effect"].iloc[0], lab["t"].iloc[0]
    F["n_editions"] = len(R.calendar)
    F["n_documented"] = int((R.calendar["time_source"] == "scheduled_documented").sum())
    a = R.assumption.loc[False]
    F["a_releases"], F["a_viol"] = int(a["releases"]), int(a["violations"])
    fr = R.first_rel.set_index(["series", "period"])
    F["crude_level_match"] = int(fr.loc[("crude_stocks_ex_spr", "development"), "matches"])
    F["crude_level_weeks"] = int(fr.loc[("crude_stocks_ex_spr", "development"), "weeks"])
    restate = R.w2w[(R.w2w["series"] == "crude_stocks_ex_spr") & (R.w2w["diff"] < -10000)]
    F["restatement_kb"] = float(restate["diff"].iloc[0])
    F["chg_mismatch"], F["chg_weeks"] = R.crude_change_mismatch
    F["rule_cl"] = (int(R.rule_cl["matches"].sum()), len(R.rule_cl))
    F["rule_rb"] = (int(R.rule_rb["matches"].sum()), len(R.rule_rb))
    F["rho_min"] = 2 / np.sqrt(F["weeks"])
    F["spread_p_min"] = R.secondary_test[R.secondary_test["family"] == "calendar_spread"][
        "p"].min()

    # Cross-checks against the values quoted in docs/REPORT.md (fail loudly on drift).
    checks = {
        "rb_gas_t": (F["rb_gas_t"], -3.67, 0.01), "rb_gas_holm": (F["rb_gas_holm"], 0.004, 5e-4),
        "net_sharpe": (F["net_sharpe"], -0.50, 0.01), "ci_lo": (F["ci_lo"], -1.14, 0.01),
        "ci_hi": (F["ci_hi"], 0.14, 0.01), "dsr": (F["dsr"], 0.0008, 1e-4),
        "spa_p": (F["spa_p"], 1.0, 1e-9), "perm_p": (F["perm_p"], 0.91, 1e-9),
        "cl_crude_t_dev": (F["cl_crude_t_dev"], -4.68, 0.01),
        "cl_crude_t_test": (F["cl_crude_t_test"], -1.51, 0.01),
        "dev_primary": (F["dev_primary"], 0.354, 1e-3),
        "dev_priceonly": (F["dev_priceonly"], 0.765, 1e-3),
        "pnl_2020": (F["pnl_2020"] / 1e3, -246, 1), "pnl_total": (F["pnl_total"] / 1e3, -310, 1),
        "restatement": (F["restatement_kb"], -30640, 1),
    }
    for key, (got, want, tol) in checks.items():
        assert abs(got - want) <= tol, f"{key}: table {got} vs report {want}"
    assert (F["chg_mismatch"], F["chg_weeks"]) == (61, 283), F["chg_mismatch"]
    assert F["n_documented"] == 791 and F["n_editions"] == 793
    assert F["a_viol"] == 0 and F["a_releases"] == 635
    assert F["n_sig_holm"] == 1 and F["drift_min_holm"] == 1.0
    assert F["rob_all_negative"] and not F["works"]
    return F


# --------------------------------------------------------------------------- building blocks
def equation(tex: str, name: str, fontsize: float = 13.5) -> Image:
    """Render a display equation with matplotlib mathtext (DejaVu Serif) as a 300-dpi image."""
    EQ.mkdir(parents=True, exist_ok=True)
    path = EQ / f"{name}.png"
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f"${tex}$", fontsize=fontsize, color=INK)
    with matplotlib.rc_context({"mathtext.fontset": "dejavuserif"}):
        fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.03, transparent=True)
    plt.close(fig)
    w, h = PILImage.open(path).size
    img = Image(str(path), width=w / 300 * inch, height=h / 300 * inch)
    img.hAlign = "CENTER"
    return img


class Doc:
    def __init__(self, st: dict[str, ParagraphStyle], text_width: float):
        self.st, self.w = st, text_width
        self.story: list = []
        self.fig_n = self.tab_n = self.eq_n = 0

    def p(self, text: str, style: str = "body") -> None:
        self.story.append(Paragraph(text, self.st[style]))

    def bullets(self, items: list[str]) -> None:
        for it in items:
            self.story.append(Paragraph(it, self.st["bullet"], bulletText="•"))

    def h1(self, text: str) -> None:
        self.story.append(Paragraph(text, self.st["h1"]))

    def h2(self, text: str) -> None:
        self.story.append(Paragraph(text, self.st["h2"]))

    def eq(self, tex: str, name: str) -> None:
        self.eq_n += 1
        img = equation(tex, name)
        t = Table([[img, Paragraph(f"({self.eq_n})", self.st["center"])]],
                  colWidths=[self.w - 0.5 * inch, 0.5 * inch])
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        self.story.append(t)

    def fig(self, path: Path, caption: str, width_frac: float = 1.0) -> None:
        self.fig_n += 1
        w0, h0 = PILImage.open(path).size
        w = self.w * width_frac
        img = Image(str(path), width=w, height=w * h0 / w0)
        cap = Paragraph(f"<b>Figure {self.fig_n}.</b> {caption}", self.st["caption"])
        self.story.append(KeepTogether([img, cap]))

    def table(self, header: list[str], rows: list[list[str]], caption: str,
              col_widths: list[float] | None = None, bold_rows: tuple[int, ...] = (),
              align_right_from: int = 1) -> None:
        self.tab_n += 1
        cap = Paragraph(f"<b>Table {self.tab_n}.</b> {caption}", self.st["tcaption"])
        data = [[Paragraph(h, self.st["cellb"]) for h in header]]
        for i, r in enumerate(rows):
            stl = self.st["cellb"] if i in bold_rows else self.st["cell"]
            data.append([Paragraph(c, stl) for c in r])
        widths = col_widths or [self.w / len(header)] * len(header)
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 1.0, colors.HexColor(INK)),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(INK)),
            ("LINEBELOW", (0, -1), (-1, -1), 1.0, colors.HexColor(INK)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            *[("BACKGROUND", (0, i + 1), (-1, i + 1), colors.HexColor(SHADE))
              for i in bold_rows],
        ]))
        self.story += [cap, t, Spacer(1, 8)]   # caption kept with table; table may split


def page_decor(title: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Sans", 7.5)
        canvas.setFillColor(colors.HexColor(INK2))
        if doc.page > 1:
            canvas.drawString(doc.leftMargin, letter[1] - 0.55 * inch, title)
            canvas.setStrokeColor(colors.HexColor(RULE))
            canvas.setLineWidth(0.4)
            canvas.line(doc.leftMargin, letter[1] - 0.6 * inch,
                        letter[0] - doc.rightMargin, letter[1] - 0.6 * inch)
        canvas.drawCentredString(letter[0] / 2, 0.5 * inch, str(doc.page))
        canvas.restoreState()
    return draw


# --------------------------------------------------------------------------- the paper
def build_paper(R: Results, F: dict) -> None:
    margin = 0.95 * inch
    W = letter[0] - 2 * margin
    st = styles()
    d = Doc(st, W)
    rm = F["rmse"]

    # ---------------- title page
    d.story += [Spacer(1, 0.6 * inch)]
    d.p("Do EIA Gasoline-Demand and Inventory Surprises Predict Energy Futures Returns?",
        "title")
    d.story.append(Spacer(1, 6))
    d.p("A point-in-time event study and pre-registered out-of-sample trading test for WTI "
        "crude oil (CL) and RBOB gasoline (RB) futures, 1996–2024", "subtitle")
    d.story.append(Spacer(1, 14))
    d.p("<b>Amit Aviv</b><br/>Columbia University, Mathematics and Economics", "subtitle")
    d.p("October 2026", "subtitle")
    d.story.append(Spacer(1, 22))
    abstract = (
        "Every Wednesday the U.S. Energy Information Administration (EIA) publishes weekly "
        "gasoline demand and petroleum inventories. I construct model-based surprises in "
        "these data using only information available before each release, including "
        "<i>first-published</i> values recovered from 793 archived reports, and test whether "
        "they move NYMEX WTI and RBOB futures on release day and whether they predict "
        "returns after the release becomes public. Release windows are built from "
        "documented release schedules, returns are computed within the futures contract "
        "actually held, and the out-of-sample period (January 2017 to April 2024) was "
        "evaluated once, after the full specification was committed and tagged in git. "
        f"Gasoline-inventory surprises move RBOB futures on release day out of sample "
        f"({pct(F['rb_gas_coef'], 2)} per standard deviation, t = {mfmt(F['rb_gas_t'])}, "
        f"Holm-adjusted p = {F['rb_gas_holm']:.3f} across 16 pre-registered tests). There is "
        f"no evidence of post-release drift: all eight drift coefficients have Holm p = "
        f"{F['drift_min_holm']:.2f}, and walk-forward forecasts underperform the historical "
        f"mean. The pre-registered strategy, which earned a net Sharpe ratio of "
        f"{mfmt(F['dev_primary'], 2, True)} in development validation, earned "
        f"{mfmt(F['net_sharpe'], 2)} out of sample (95% bootstrap CI "
        f"[{mfmt(F['ci_lo'])}, {mfmt(F['ci_hi'], 2, True)}], Deflated Sharpe Ratio "
        f"{F['dsr']:.4f}, Hansen SPA p = {F['spa_p']:.2f}). Weekly EIA information appears "
        "to be incorporated by the first settlement after the release.")
    box = Table([[Paragraph("<b>Abstract.</b> " + abstract, st["abstract"])]], colWidths=[W])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(SHADE)),
                             ("LEFTPADDING", (0, 0), (-1, -1), 12),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                             ("TOPPADDING", (0, 0), (-1, -1), 10),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
    d.story.append(box)
    d.story.append(Spacer(1, 14))
    d.p("<b>Keywords:</b> event study; commodity futures; point-in-time data; look-ahead "
        "bias; Newey–West; multiple testing; walk-forward forecasting; Deflated Sharpe "
        "Ratio; SPA test; pre-registration.", "small")
    d.story.append(Spacer(1, 18))
    d.table(
        ["Question", "Locked-test result (2017-01 to 2024-04)", "Verdict"],
        [["Q1: release-day reaction",
          f"RB ← gasoline-stock surprise: {pct(F['rb_gas_coef'], 2)} per sd, "
          f"t = {mfmt(F['rb_gas_t'])}, Holm p = {F['rb_gas_holm']:.3f}",
          "Significant; replicates development"],
         ["Q2: post-release drift",
          f"All 8 drift coefficients Holm p = {F['drift_min_holm']:.2f}; OOS R² "
          f"{pct(F['oos_m3_CL'])} (CL), {pct(F['oos_m3_RB'])} (RB)", "No evidence"],
         ["Trading strategy (net)",
          f"Sharpe {mfmt(F['net_sharpe'])}, CI [{mfmt(F['ci_lo'])}, "
          f"{mfmt(F['ci_hi'], 2, True)}], DSR {F['dsr']:.4f}, SPA p = {F['spa_p']:.2f}",
          "Fails all pre-registered criteria"]],
        "Summary of findings. Q1 is a diagnostic of the surprise measure; Q2 and the "
        "strategy are the tradable hypotheses.",
        col_widths=[1.35 * inch, W - 3.05 * inch, 1.7 * inch], align_right_from=9)
    d.p("All numbers are produced by the project's code and stored in "
        "<font name='Sans'>reports/tables/</font>; reproduction commands are in Appendix A.",
        "small")
    d.story.append(PageBreak())

    # ---------------- 1 introduction
    d.h1("1. Research question and economic motivation")
    d.p("The EIA's <i>Weekly Petroleum Status Report</i> (WPSR) is among the most closely "
        "watched scheduled releases in commodity markets. Weekly <i>gasoline product "
        "supplied</i> is the best high-frequency public proxy for U.S. transportation fuel "
        "demand, and inventories are the buffer between supply and demand. Under the "
        "<i>theory of storage</i>, an unexpected inventory build signals looser balances and "
        "lowers the convenience yield of physical barrels, so prompt futures prices should "
        "fall; the effect should be larger when stocks are scarce.")
    d.p("Predictable variation (seasonality, holidays, trend) is already in the futures "
        "curve, so only the unexpected component of each report can move prices. The study "
        "separates two questions that are often conflated:")
    d.bullets([
        "<b>Q1 – announcement reaction (diagnostic).</b> Does the return from the last "
        "settlement before the release to the first settlement after it respond to the "
        "surprise? This is not tradable with daily data, but if it fails the surprise "
        "measure is too noisy for Q2 to be informative.",
        "<b>Q2 – post-release drift (tradable).</b> From the first settlement after the "
        "release to the last settlement before the next release, does the price keep moving "
        "(under-reaction) or revert (over-reaction)? Theory does not fix the sign, so tests "
        "are two-sided.",
    ])
    d.p("Announcement effects of EIA inventory news are documented (e.g. Halova, Kurov and "
        "Kucher, 2014). The tradable post-release question under realistic execution timing "
        "is studied far less, and it is where look-ahead bias is easiest to introduce.")
    d.fig(FIG / "paper/event_timeline.png",
          "Event windows for a standard week. The announcement window brackets the release; "
          "the drift window starts at the first settlement after the release and ends before "
          "the next release, so a holding period never contains two announcements.")

    # ---------------- 2 data
    d.h1("2. Data sources and point-in-time construction")
    d.table(
        ["Data", "Source", "Coverage"],
        [["Weekly fundamentals: gasoline product supplied; crude (ex-SPR), gasoline and "
          "distillate stocks", "EIA bulk history files", "1982/1991 – 2026-10"],
         ["NYMEX settlements, CL and RB contracts 1–3", "EIA (discontinued after 2024-04-05)",
          "1983/2005 – 2024-04-05"],
         [f"Release dates of {F['n_editions']} WPSR editions; first-published Table 1 values",
          "EIA WPSR archive", "2011-08 – 2026-10"],
         ["Release-time schedules (live page + 194 archived copies)",
          "EIA schedule page via the Internet Archive", "2006 – 2026"],
         ["Contract expiries (96 calendar copies) and contract rules",
          "CME product calendars; NYMEX Rulebook ch. 200 and 191", "1983 – 2024"]],
        "Data. All 1,105 source files are logged with URL, download time and SHA-256 hash. "
        "No vendor data was used.",
        col_widths=[2.9 * inch, 2.1 * inch, W - 5.0 * inch])
    d.p("<b>Release times are documented, not assumed.</b> A time is attached to a release "
        "only if an EIA schedule in force for that period states it <i>and</i> the observed "
        f"release date matches the scheduled date; {F['n_documented']} of {F['n_editions']} "
        "editions qualify. For the remaining two the release is treated as an interval "
        "covering the whole day: windows <i>close</i> at the earliest possible release time "
        "and <i>open</i> after the latest, so uncertainty can only delay entry. Holiday "
        "release times changed across years (10:30, 11:00, 12:00, 17:00), so none is "
        "assumed. For years before the archive (pre-August 2011) a conservative rule "
        "assumes each report was public by Friday F+7 at 14:29; on all observed releases "
        f"since 2011 it held in {F['a_releases'] - F['a_viol']} of {F['a_releases']} "
        "non-holiday weeks (holiday weeks are excluded by construction).")
    d.p("<b>First-published values, not revisions.</b> Comparing the archived first prints "
        "with today's history file revealed that EIA restated commercial crude stocks in "
        "October 2016 (the next edition re-printed the prior week "
        f"{abs(F['restatement_kb']) / 1000:.1f} million barrels lower) and applied the new "
        "definition backwards: crude levels match "
        f"in only {F['crude_level_match']} of {F['crude_level_weeks']} development weeks, and "
        f"the weekly <i>change</i> the market saw differs in {F['chg_mismatch']} of "
        f"{F['chg_weeks']}. Surprises therefore use each edition's own printed values "
        "wherever an archived edition exists.")
    d.p("<b>Contract-aware returns.</b> EIA's 'contract 1' silently rolls at expiry. Returns "
        "and P&amp;L are computed within the contract actually held, rolling five business "
        "days before the exchange-documented expiry, in dollars per contract (WTI settled at "
        "−$37.63 on 2020-04-20). Expiries come from CME-published last-trade dates where "
        "archived, and otherwise from the rulebook rule on a scheduled exchange calendar; "
        f"the rule matches CME on {F['rule_rb'][0]}/{F['rule_rb'][1]} RB and "
        f"{F['rule_cl'][0]}/{F['rule_cl'][1]} CL contracts where both exist.")

    # ---------------- 3 methodology
    d.h1("3. Methodology")
    d.h2("3.1 Surprises")
    d.p("For each weekly series, y<sub>t</sub> is the change in stocks or the level of "
        "demand, and the surprise is the forecast error of an expectation built from data "
        "published before release t:")
    d.eq(r"s_t = y_t - \mathbb{E}\,[\,y_t \mid y_{t-1}, y_{t-2}, \ldots\,],\qquad "
         r"z_t = s_t \,/\, \mathrm{sd}(s_{<t})", "surprise")
    d.p("Three pre-registered expectation models are compared: the five-year same-week mean "
        "(EIA's own benchmark); a seasonal regression with trend, three Fourier harmonics "
        "and holiday dummies on a trailing five-year window; and the same regression plus "
        "an AR(1) on its residuals. Standardising by the expanding standard deviation of "
        "<i>past</i> surprises avoids leaking the full-sample scale.")
    d.h2("3.2 Hypothesis tests")
    d.eq(r"r^{w}_{m,t} = \alpha + \sum_{j=1}^{4} \beta_j\, z_{j,t} + \delta' x_{m,t} + "
         r"\varepsilon_t", "regression")
    d.p("for market m ∈ {CL, RB} and window w ∈ {announcement, drift}. The controls "
        "x<sub>m,t</sub> (drift only) are one- and four-week momentum, 20-day realised "
        "volatility and the front-to-second contract carry, all measured at entry. Standard "
        "errors are Newey–West with lag L = ⌊4(n/100)<super>2/9</super>⌋, robust to "
        "heteroskedasticity and serial correlation. The 16 coefficients (2 markets × 2 "
        "windows × 4 surprises) form one pre-registered family, corrected with Holm "
        "(family-wise error) and Benjamini–Hochberg (false discovery rate).")
    d.h2("3.3 Forecast evaluation")
    d.p("Drift returns are forecast walk-forward: models are refit every January on events "
        "whose <i>exit</i> settlement precedes the refit date. Models are M0 (historical "
        "mean), M1 (price controls), M2 (M1 plus surprises), M3 (ridge on M2's regressors), "
        "M4 (logistic, direction) and M5 (gradient boosting, run only if a pre-registered "
        "trigger fired). Accuracy is measured by the out-of-sample R² of Campbell and "
        "Thompson and, for nested models, the Clark–West statistic:")
    d.eq(r"R^2_{OOS} = 1 - \mathrm{MSE}(\hat{y}_t)\,/\,\mathrm{MSE}(\bar{y}_{<t})", "oos")
    d.eq(r"f_t = (y_t-\hat{y}_{1,t})^2 - \left[\,(y_t-\hat{y}_{2,t})^2 - "
         r"(\hat{y}_{1,t}-\hat{y}_{2,t})^2\,\right],\qquad \mathrm{CW} = "
         r"\bar{f}\,/\,\widehat{\mathrm{se}}_{\mathrm{HAC}}(\bar{f})", "cw")
    d.p("where model 1 is nested in model 2; a positive Clark–West statistic indicates that "
        "the larger model adds predictive information after correcting for its estimation "
        "noise.")
    d.h2("3.4 Strategy inference")
    d.p("Sharpe-ratio uncertainty is measured with the stationary bootstrap (Politis and "
        "Romano, 1994; mean block length eight weeks). Selection across specifications is "
        "addressed with the Deflated Sharpe Ratio (Bailey and López de Prado, 2014), which "
        "compares the observed per-period Sharpe ratio with the expected maximum of N "
        "trials under the null, and with Hansen's (2005) SPA test across all tradable "
        "variants. Year-block permutations and turnover-matched random signs provide "
        "additional null distributions.")
    d.eq(r"\mathrm{DSR} = \Phi\left( (\widehat{SR} - SR_0)\,\sqrt{n-1}\;/\;"
         r"\hat{\sigma}_{SR} \right),\qquad \hat{\sigma}^{2}_{SR} = 1 - "
         r"\hat{\gamma}_3\,\widehat{SR} + \frac{\hat{\gamma}_4 - 1}{4}\,\widehat{SR}^{2}",
         "dsr")
    d.p("where SR<sub>0</sub> is the expected maximum Sharpe ratio across N independent "
        "trials under the null, and γ<sub>3</sub>, γ<sub>4</sub> are the skewness and "
        "kurtosis of returns.")
    d.h2("3.5 Research protocol")
    d.p("The analysis protocol was committed before any futures return was examined. Data "
        "dated 2017 or later is blocked in code until a <font name='Sans'>spec-freeze</font> "
        "git tag exists, and the test script refuses to run if the code differs from the "
        "tag. One amendment was made during development: the trading signal is the forecast's "
        "deviation from the unconditional mean, because the original scaling turned a "
        "heavily shrunk model into a constant short position. It is disclosed, and its "
        f"trials are counted in the Deflated Sharpe Ratio (N = {F['n_trials']}).")

    # ---------------- 4 EDA
    d.h1("4. Exploratory analysis (development sample, 1996–2016)")
    d.p("All series are strongly seasonal (one-way ANOVA by week of year, p &lt; 0.001). "
        "Gasoline demand peaks in late June; Labor Day weeks show demand "
        f"{abs(F['labor_eff']):.0f} kb/d below a normal week of the same season "
        f"(t = {mfmt(F['labor_t'])}). Weekly changes are fat-tailed and autocorrelated; "
        "inventory changes are stationary while the crude stock level has a unit root "
        f"(ADF p = {F['adf_crude_level_p']:.2f}), which is why surprises are defined on "
        "changes. The theory of storage is visible in the data: when crude stocks are high "
        "relative to their five-year norm, the curve is in contango (Spearman ρ = "
        f"{mfmt(F['rho_cl'])} for CL, {mfmt(F['rho_rb'])} for RB).")
    d.fig(FIG / "eda/02_seasonality.png",
          "Seasonal pattern of demand and weekly inventory changes by week of year, "
          "1996–2016 (line: mean; band: interquartile range).")
    d.fig(FIG / "eda/08_storage_carry.png",
          "Theory of storage: front-to-second-contract carry against the prior week's "
          "inventory deviation from its five-year same-week norm (development data).",
          width_frac=0.92)

    # ---------------- 5 results
    d.h1("5. Results")
    d.h2("5.1 Surprise models")
    d.p("The seasonal regression with AR(1) residuals has the lowest out-of-sample error for "
        "all four series and is selected (Figure 5). The gain is largest for demand, where "
        f"RMSE falls from {rm.loc['demand', 'five_year']:.0f} to "
        f"{rm.loc['demand', 'seasonal_ar']:.0f} kb/d ({pct(F['demand_reduction'], 0)}), "
        "because the five-year mean ignores the demand trend. Better expectations reduce the "
        "attenuation bias that measurement error imposes on regression slopes.")
    d.fig(FIG / "paper/surprise_model_rmse.png",
          "Out-of-sample RMSE of the three pre-registered expectation models relative to the "
          "five-year same-week mean (forecast weeks 2001–2016; fundamentals only).",
          width_frac=0.92)
    d.h2("5.2 Release-day reaction and post-release drift")
    rows_t = []
    for m, w, s, lab in (("RB", "ann", "gasoline", "RB, announcement ← gasoline stocks"),
                         ("RB", "ann", "demand", "RB, announcement ← gasoline demand"),
                         ("CL", "ann", "crude", "CL, announcement ← crude stocks"),
                         ("CL", "ann", "gasoline", "CL, announcement ← gasoline stocks"),
                         ("CL", "ann", "demand", "CL, announcement ← gasoline demand")):
        dv = row(R.fam_dev, m, w, s, "development_precise_2011_2016")
        ts = row(R.fam_test, m, w, s)
        rows_t.append([lab, pct(dv["coef"], 2), mfmt(dv["t"]), pct(ts["coef"], 2),
                       mfmt(ts["t"]), f"{ts['p_holm']:.3f}"])
    drift = R.fam_test[R.fam_test["window"] == "drift"]
    rows_t.append(["All 8 drift coefficients (CL and RB)", "–", "–", "–",
                   f"|t| ≤ {F['drift_max_abs_t']:.2f}", f"{drift['p_holm'].min():.2f}"])
    d.table(["Market, window ← surprise", "Dev. coef", "Dev. t", "Test coef", "Test t",
             "Test Holm p"], rows_t,
            "Selected coefficients of equation (2), percent return per one-standard-deviation "
            "surprise. Development: 2011-08 to 2016 (in-sample). Test: 2017-01 to 2024-04-05. "
            "Newey–West t-statistics; Holm adjustment across all 16 test-period coefficients.",
            col_widths=[2.35 * inch] + [(W - 2.35 * inch) / 5] * 5, bold_rows=(0,))
    d.p(f"Only one of the 16 test-period coefficients survives the Holm correction: "
        f"gasoline-inventory surprises lower RBOB on release day "
        f"({pct(F['rb_gas_coef'], 2)} per standard deviation, t = {mfmt(F['rb_gas_t'])}), "
        f"replicating the development sign; the result holds under conservative timing "
        f"(t = {mfmt(F['rb_gas_cons_t'])}, Holm p = {F['rb_gas_cons_holm']:.3f}). The crude "
        f"→ WTI reaction, strong in development (t = {mfmt(F['cl_crude_t_dev'])}), shrank "
        f"to t = {mfmt(F['cl_crude_t_test'])}, and the demand → RBOB coefficient changed "
        f"sign (t = {mfmt(F['rb_dem_t_dev'], 2, True)} in development, "
        f"{mfmt(F['rb_dem_t_test'])} in the test). Candidate explanations—information "
        "released earlier by the private API survey, the post-2015 export era, and "
        "measurement error in model-based surprises—are hypotheses, not tested results. No "
        "drift coefficient is significant, and the secondary calendar-spread and "
        f"inventory-state interaction tests are not significant (all p ≥ {F['spread_p_min']:.2f} "
        "for the spread family).")
    d.fig(FIG / "report/q1_dev_vs_test.png",
          "Release-day reaction per one-standard-deviation surprise with 95% Newey–West "
          "confidence intervals: development (2011–2016) versus the locked test (2017–2024).")
    d.fig(FIG / "report/family_t_test.png",
          "All 16 pre-registered test-period coefficients. The diamond marks the only effect "
          "significant after the Holm correction.", width_frac=0.9)
    d.h2("5.3 Forecasting")
    d.table(["Model", "Dev. CL", "Dev. RB", "Test CL", "Test RB"],
            [[lab, pct(R.fc_dev.loc["CL", c], 2, True), pct(R.fc_dev.loc["RB", c], 2, True),
              pct(R.fc_test.loc["CL", c], 2, True), pct(R.fc_test.loc["RB", c], 2, True)]
             for lab, c in (("M1 price-only (OLS)", "oos_r2_m1_vs_m0"),
                            ("M2 price + surprises (OLS)", "oos_r2_m2_vs_m0"),
                            ("M3 ridge (selected)", "oos_r2_m3_vs_m0"))],
            "Out-of-sample R² of drift forecasts relative to the historical mean (M0). "
            "Development: walk-forward validation 2006–2016.",
            col_widths=[2.35 * inch] + [(W - 2.35 * inch) / 4] * 4)
    d.p(f"Validation selected the heaviest ridge penalty on the grid (λ = {F['lam']:.0f}): "
        "out-of-sample error fell monotonically toward the unconditional mean. Gradient "
        "boosting, triggered by a nominal Clark–West result as pre-registered, did worse "
        "still in development. In the test every model underperforms the historical mean, "
        f"and the direction model's hit rate ({pct(F['hit_CL'])} CL, {pct(F['hit_RB'])} RB) "
        f"is below the share of up-weeks ({pct(F['up_CL'])}, {pct(F['up_RB'])}).")

    # ---------------- 6 strategy
    d.h1("6. Trading strategy and backtesting methodology")
    d.p("The signal is the standardised <i>conditional</i> drift forecast from M3, its "
        "deviation from the training-sample mean forecast divided by the dispersion of "
        "fitted values, both from the same annual refit:")
    d.eq(r"\hat{z}_t = \frac{\hat{r}_t - \overline{\hat{r}}_{\mathrm{train}}}"
         r"{\mathrm{sd}(\hat{r}_{\mathrm{train}})},\qquad "
         r"q_t = \mathrm{sign}(\hat{z}_t)\,\mathbf{1}\{|\hat{z}_t| > k\}\;"
         r"\frac{\sigma^{*}}{\hat{\sigma}_d \sqrt{h}\, P_t\, M}", "sizing")
    d.p(f"The primary rule (Rule A) is long, short or flat with threshold k = {F['k']:.1f}, "
        "chosen in development from {0.5, 1.0, 1.5}. Position size targets 10% annual "
        "volatility on a $1 million capital base: σ* is the weekly dollar-risk target, "
        "σ<sub>d</sub> the trailing 60-day daily volatility known at entry, h the holding "
        "period in days, P the price and M the contract multiplier (1,000 bbl for CL, 42,000 "
        "gal for RB); contracts are rounded and gross notional is capped at twice capital. "
        "Rule B sizes positions in proportion to clip(ẑ, −2, 2), equivalent to sizing by "
        "forecast over variance. Positions are opened at the first settlement after the "
        "release and closed at the last settlement before the next one. Daily P&amp;L is "
        "q<sub>d−1</sub>(P<sub>h</sub>(d) − P<sub>h</sub>(d−1))M in the contract h held, so "
        "rolls never book a spread between contracts; costs are charged per contract per "
        "side, including both legs of every roll. Benchmarks are always-long, a price-only "
        "strategy (Rule A on M1 forecasts) and turnover-matched random signs. Returns are "
        "weekly P&amp;L on the fixed capital base, annualised with √52.")

    # ---------------- 7 out-of-sample
    d.h1("7. Out-of-sample performance")
    srows = []
    for key, lab in (("PRIMARY_ruleA", "Rule A (primary)"), ("ruleB_vol_scaled", "Rule B"),
                     ("bench_always_long", "Always long"),
                     ("bench_price_only_m1", "Price-only benchmark")):
        r = R.strat_test.loc[key]
        srows.append([lab, mfmt(r["gross_sharpe"]), mfmt(r["net_sharpe"]),
                      pct(r["net_ann_return"]), pct(r["net_ann_vol"]), mfmt(r["net_sortino"]),
                      pct(r["net_max_drawdown"]), f"${r['costs_per_year_usd']:,.0f}"])
    d.table(["Strategy", "Gross Sharpe", "Net Sharpe", "Net return / yr", "Volatility / yr",
             "Sortino", "Max drawdown", "Costs / yr"], srows,
            f"Locked test, {F['weeks']} weeks (2017-01 to 2024-04-05), base costs, "
            "non-compounded returns on a $1 million base.",
            col_widths=[1.45 * inch] + [(W - 1.45 * inch) / 7] * 7, bold_rows=(0,))
    d.p(f"The primary strategy made {F['n_trades']} trades ({F['n_trades_cl']} CL, "
        f"{F['n_trades_rb']} RB) with a {pct(F['win_rate'])} win rate and lost "
        f"${abs(F['pnl_total']) / 1e3:,.0f}k over the test; 2020 accounts for "
        f"${abs(F['pnl_2020']) / 1e3:,.0f}k, but excluding the first half of 2020 the net "
        f"Sharpe ratio is still {mfmt(F['excl2020_sharpe'])}. {F['skipped']} events were "
        "skipped because a settlement was missing.")
    d.fig(FIG / "paper/primary_equity_test.png",
          "Primary strategy in the locked test: cumulative returns gross and net of base "
          "costs (percent of $1 million) and net drawdown. The two lines nearly coincide: "
          "the losses come from the signal, not from costs.")
    d.table(["Statistic", "Value", "Pre-registered criterion", "Met"],
            [["Net Sharpe, 95% stationary-bootstrap CI",
              f"{mfmt(F['net_sharpe'])} [{mfmt(F['ci_lo'])}, {mfmt(F['ci_hi'], 2, True)}]; "
              f"P(SR ≤ 0) = {F['p_le0']:.2f}", "CI above 0", "No"],
             [f"Deflated Sharpe Ratio (N = {F['n_trials']} trials)",
              f"{F['dsr']:.4f} (SR₀ = {F['sr0_week']:.3f} per week)", "&gt; 0.95", "No"],
             [f"Hansen SPA, {F['spa_n']} tradable variants", f"p = {F['spa_p']:.2f}",
              "p &lt; 0.05", "No"],
             ["Year-block permutation (1,000 draws)", f"p = {F['perm_p']:.2f}", "–", "–"],
             ["Random signs, matched turnover (1,000 draws)",
              f"primary at the {F['rs_pct'] * 100:.1f}th percentile", "–", "–"]],
            "Formal inference for the primary strategy's net returns.",
            col_widths=[2.3 * inch, 2.2 * inch, 1.3 * inch, W - 5.8 * inch])
    d.p("None of the three pre-registered success criteria is met. The bootstrap interval "
        f"contains zero and places {F['p_le0'] * 100:.0f}% of its mass at or below it. The "
        "Deflated Sharpe Ratio is essentially zero: with "
        f"{F['n_trials']} development trials, pure noise would be expected to produce a "
        f"best weekly Sharpe ratio of about {F['sr0_week']:.3f} "
        f"({mfmt(F['sr0_week'] * np.sqrt(52))} annualised), and the observed value is "
        "negative. The SPA test finds no variant that beats a zero-return benchmark after "
        "accounting for the search across variants. The null distributions in Figure 9 "
        "show the same thing from a different angle: randomly signed trades with the same "
        "turnover, or signals shuffled across years, do as well as the model's signal. "
        "Figure 8 shows that the reversal from development to test applies to every "
        "strategy, including the price-only benchmark, which is the pattern expected when "
        "development performance reflects selection on noise.")
    d.fig(FIG / "report/strategy_dev_vs_test.png",
          "Net Sharpe ratios in development validation (2006–2016, walk-forward, parameters "
          "selected on this period) and in the locked test. Every positive development result "
          "reversed.", width_frac=0.8)
    d.fig(FIG / "phase7/test_null_distributions.png",
          "The primary strategy's net Sharpe against two null distributions.")

    # ---------------- 8 robustness
    d.h1("8. Robustness and transaction costs")
    cost_rows = []
    for key, lab, cl, rb in (("cost_optimistic", "Optimistic (½ tick + $1.50)", "$6.50", "$3.60"),
                             (None, "Base (1 tick + $2.50)", "$12.50", "$6.70"),
                             ("cost_conservative", "Conservative (2 ticks + $4.00)", "$24.00",
                              "$12.40"),
                             ("cost_stress", "Stress (4 ticks + $5.00)", "$45.00", "$21.80")):
        v = F["net_sharpe"] if key is None else R.robust.loc[key, "net_sharpe"]
        cost_rows.append([lab, cl, rb, mfmt(v)])
    d.table(["Cost scenario (per contract per side)", "CL", "RB", "Net Sharpe"], cost_rows,
            "Transaction-cost sensitivity of the primary strategy in the locked test.",
            col_widths=[2.8 * inch, 1.1 * inch, 1.1 * inch, W - 5.0 * inch], bold_rows=(1,))
    d.p(f"Costs totalled ${F['cost_total'] / 1e3:,.1f}k against a gross loss of "
        f"${abs(F['gross_total']) / 1e3:,.0f}k: the failure is in the gross signal, not in "
        "execution costs. Every tradable variant in the pre-registered grid has a negative "
        f"net Sharpe ratio, from {mfmt(F['rob_min'])} to {mfmt(F['rob_max'])}—across cost "
        "scenarios, thresholds, roll offsets, Thursday entry, alternative surprise models, "
        "winsorised surprises, conservative timing and sub-periods. The placebos (late "
        f"Monday entry {mfmt(F['placebo_late_entry_monday'], 2, True)}, stale signal "
        f"{mfmt(F['placebo_stale_signal_lag4'])}, cross-market signal "
        f"{mfmt(F['placebo_cross_target'])}) perform no worse than the real signal, as "
        "expected if the signal carries no post-release information.")
    d.fig(FIG / "report/robustness_test.png",
          "Pre-registered robustness grid, locked test (orange: primary specification; green: "
          "placebos).", width_frac=0.9)

    # ---------------- 9 limitations / conclusions
    d.h1("9. Limitations")
    d.bullets([
        "<b>Daily settlements</b> cannot observe the minutes after the 10:30 release; any "
        "fast drift is invisible. Intraday data was deferred.",
        f"<b>Power.</b> With {F['weeks']} test weeks, a correlation of about "
        f"{F['rho_min']:.2f} (≈ 2/√n) is needed for t ≈ 2, roughly a gross Sharpe ratio of "
        f"{F['rho_min'] * np.sqrt(52):.2f}; only large effects were detectable. The test ends "
        "on 2024-04-05, when EIA stopped publishing futures prices.",
        "<b>Model-based surprises</b> stand in for consensus forecasts, attenuating "
        "coefficients; the Tuesday API survey pre-empts part of the information.",
        "<b>Before August 2011</b> surprises use restated history (no first-release archive) "
        "and release times are scheduled rather than observed throughout.",
        "<b>Expiries</b> after 2016 (RB) and November 2022 (CL) rely on the validated rulebook "
        "rule; a possible one-day labelling ambiguity on expiry days affects roughly 2% of "
        "events by about half a percent of price.",
        "<b>One development amendment</b> (signal standardisation) was made after seeing "
        "development results; it is disclosed and counted in the Deflated Sharpe Ratio.",
    ])
    d.h1("10. Conclusions")
    d.p("EIA weekly inventory surprises carry real release-day information: the gasoline "
        "→ RBOB effect replicated out of sample under a strict multiple-testing correction. "
        "There is no evidence of a tradable post-release drift with daily settlements; every "
        "strategy variant failed the pre-registered criteria and forecasts underperformed "
        "the historical mean. Development-period success—including a price-only benchmark "
        f"with a {mfmt(F['dev_priceonly'], 2, True)} Sharpe ratio—did not survive. Without the "
        "locked test, this project would have reported a profitable strategy. The natural "
        "next step is intraday: measuring how much of the reaction occurs in the first "
        "minutes after the release, and whether any drift exists at horizons a daily "
        "study cannot see.")

    d.h1("References")
    refs = [
        "Bailey, D. H. and López de Prado, M. (2014). The Deflated Sharpe Ratio. "
        "<i>Journal of Portfolio Management</i>, 40(5).",
        "Benjamini, Y. and Hochberg, Y. (1995). Controlling the false discovery rate. "
        "<i>JRSS B</i>, 57(1).",
        "Campbell, J. Y. and Thompson, S. B. (2008). Predicting excess stock returns out of "
        "sample. <i>Review of Financial Studies</i>, 21(4).",
        "Clark, T. E. and West, K. D. (2007). Approximately normal tests for equal predictive "
        "accuracy in nested models. <i>Journal of Econometrics</i>, 138(1).",
        "Diebold, F. X. and Mariano, R. S. (1995). Comparing predictive accuracy. <i>JBES</i>, "
        "13(3).",
        "Halova, M. W., Kurov, A. and Kucher, O. (2014). Noisy inventory announcements and "
        "energy prices. <i>Journal of Futures Markets</i>, 34(10).",
        "Hansen, P. R. (2005). A test for superior predictive ability. <i>JBES</i>, 23(4).",
        "Holm, S. (1979). A simple sequentially rejective multiple test procedure. "
        "<i>Scandinavian Journal of Statistics</i>, 6(2).",
        "Newey, W. K. and West, K. D. (1987, 1994). <i>Econometrica</i> 55(3); <i>Review of "
        "Economic Studies</i> 61(4).",
        "Politis, D. N. and Romano, J. P. (1994). The stationary bootstrap. <i>JASA</i>, 89.",
        "U.S. Energy Information Administration. Weekly Petroleum Status Report and petroleum "
        "price series (public domain). CME Group, NYMEX Rulebook chapters 200 and 191.",
    ]
    for r in refs:
        d.p(r, "small")
        d.story.append(Spacer(1, 2))

    d.h1("Appendix A. Reproduction")
    d.p("Every table and figure is produced by the repository. From the project root:")
    code = ParagraphStyle("code", parent=st["small"], fontName="Sans", textColor=INK,
                          leftIndent=12, leading=11)
    for line in ("uv sync && uv run pytest && uv run ruff check .",
                 "uv run python -m transport_energy.data.build          # data + validation",
                 "uv run python -m transport_energy.analysis.eda        # Phase 4",
                 "uv run python -m transport_energy.analysis.development  # Phases 5-6",
                 "TEQ_UNLOCK_TEST=spec-freeze-v1 uv run python -m "
                 "transport_energy.analysis.locked_test"):
        d.story.append(Paragraph(line.replace("&", "&amp;"), code))
    d.story.append(Spacer(1, 6))
    d.p("Re-running the pipeline from the frozen tag produced byte-identical result tables. "
        "The locked-test script refuses to run if the code differs from the tag.")

    doc = SimpleDocTemplate(str(OUT_PAPER), pagesize=letter, leftMargin=margin,
                            rightMargin=margin, topMargin=0.85 * inch, bottomMargin=0.8 * inch,
                            title="Do EIA Gasoline-Demand and Inventory Surprises Predict "
                                  "Energy Futures Returns?",
                            author="Amit Aviv", subject="Quantitative research paper")
    deco = page_decor("Aviv · EIA Surprises and Energy Futures")
    doc.build(d.story, onFirstPage=deco, onLaterPages=deco)


# --------------------------------------------------------------------------- one-pager
def build_summary(R: Results, F: dict) -> None:
    margin = 0.6 * inch
    W = letter[0] - 2 * margin
    st = styles(0.86)
    d = Doc(st, W)
    d.p("EIA Gasoline-Demand and Inventory Surprises and Energy Futures", "title")
    d.p("Research summary · Amit Aviv, Columbia University · WTI (CL) and RBOB (RB) futures, "
        "1996–2024", "subtitle")
    d.story.append(Spacer(1, 4))

    d.h2("Research question")
    d.p("Do the unexpected parts of the EIA's weekly gasoline-demand and inventory report "
        "move NYMEX crude and gasoline futures on release day (Q1), and do they predict "
        "returns <i>after</i> the release, when a trader can act (Q2)?")
    d.h2("Data and methods")
    d.bullets([
        f"<b>Point-in-time data:</b> release times documented for {F['n_documented']} of "
        f"{F['n_editions']} reports; first-published values from archived editions (found a "
        f"{abs(F['restatement_kb']) / 1000:.1f}-million-barrel 2016 crude restatement); "
        "contract-aware dollar P&amp;L with exchange-documented expiries.",
        "<b>Surprises:</b> actual minus a seasonal + AR(1) forecast, selected by "
        f"out-of-sample error ({pct(F['demand_reduction'], 0)} lower demand-forecast RMSE "
        "than EIA's five-year benchmark).",
        "<b>Inference:</b> Newey–West regressions, Holm correction across 16 pre-registered "
        "tests; walk-forward forecasts (OOS R², Clark–West); stationary-bootstrap Sharpe CI, "
        "Deflated Sharpe Ratio, Hansen SPA, permutation nulls.",
        "<b>Protocol:</b> development 1996–2016; locked test 2017-01 to 2024-04-05, run once "
        "after a git-tagged specification freeze enforced in code.",
    ])
    d.h2("Key findings")
    d.bullets([
        f"<b>1. A real release-day effect.</b> Gasoline-inventory surprises move RBOB: "
        f"{pct(F['rb_gas_coef'], 2)} per sd, t = {mfmt(F['rb_gas_t'])}, Holm p = "
        f"{F['rb_gas_holm']:.3f} out of sample, replicating development. The development crude "
        f"→ WTI effect (t = {mfmt(F['cl_crude_t_dev'])}) did not replicate "
        f"(t = {mfmt(F['cl_crude_t_test'])}).",
        f"<b>2. No post-release drift.</b> All 8 drift coefficients Holm p = "
        f"{F['drift_min_holm']:.2f}; forecast OOS R² {pct(F['oos_m3_CL'])} (CL) and "
        f"{pct(F['oos_m3_RB'])} (RB) versus the historical mean.",
        f"<b>3. The strategy failed out of sample.</b> Net Sharpe {mfmt(F['net_sharpe'])} "
        f"against {mfmt(F['dev_primary'], 2, True)} in development; every robustness variant "
        "negative; costs were not the cause.",
    ])
    rows = []
    for key, lab in (("PRIMARY_ruleA", "Rule A (primary)"), ("ruleB_vol_scaled", "Rule B"),
                     ("bench_always_long", "Always long"),
                     ("bench_price_only_m1", "Price-only")):
        r = R.strat_test.loc[key]
        rows.append([lab, mfmt(r["gross_sharpe"]), mfmt(r["net_sharpe"]),
                     pct(r["net_ann_return"]), pct(r["net_ann_vol"]),
                     pct(r["net_max_drawdown"])])
    d.table(["Locked test 2017–2024", "Gross Sharpe", "Net Sharpe", "Return / yr",
             "Vol / yr", "Max DD"], rows,
            "Strategy performance, base costs, $1 million base.",
            col_widths=[1.7 * inch] + [(W - 1.7 * inch) / 5] * 5, bold_rows=(0,))
    d.table(["Primary strategy statistic", "Value", "Criterion"],
            [["Net Sharpe, 95% bootstrap CI", f"[{mfmt(F['ci_lo'])}, "
              f"{mfmt(F['ci_hi'], 2, True)}]", "above 0 — not met"],
             [f"Deflated Sharpe Ratio (N = {F['n_trials']})", f"{F['dsr']:.4f}",
              "&gt; 0.95 — not met"],
             ["Hansen SPA p-value", f"{F['spa_p']:.2f}", "&lt; 0.05 — not met"]],
            "Main statistical results for the trading hypothesis.",
            col_widths=[2.6 * inch, 2.2 * inch, W - 4.8 * inch])
    d.fig(FIG / "report/strategy_dev_vs_test.png",
          "Net Sharpe ratios: development validation versus the locked test.",
          width_frac=0.62)
    d.h2("Limitations")
    d.p(f"Daily settlements miss the first minutes after the release; {F['weeks']} test weeks "
        "detect only large effects; model-based surprises (no consensus or API data) "
        "attenuate coefficients; pre-2011 data uses restated history; one disclosed "
        "development amendment. Full paper: <i>reports/Energy_Futures_Research.pdf</i>.")
    doc = SimpleDocTemplate(str(OUT_SUMMARY), pagesize=letter, leftMargin=margin,
                            rightMargin=margin, topMargin=0.5 * inch, bottomMargin=0.45 * inch,
                            title="Research Summary: EIA Surprises and Energy Futures",
                            author="Amit Aviv")
    doc.build(d.story)


def main() -> None:
    R = load()
    F = facts(R)
    build_paper(R, F)
    build_summary(R, F)
    print("verified facts:", len(F), "->", OUT_PAPER.name, OUT_SUMMARY.name)


if __name__ == "__main__":
    main()
