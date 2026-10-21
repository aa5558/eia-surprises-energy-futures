# Transportation Demand Signals for Energy Futures

**Do surprises in the EIA's weekly gasoline-demand and petroleum-inventory data predict WTI
(CL) and RBOB (RB) futures returns after the release? A point-in-time event study with a
pre-registered, git-locked out-of-sample test.**

## Result in one paragraph

- **Release day:** gasoline-inventory surprises move RBOB futures, and the effect replicates out
  of sample (2017–2024: −0.74% per sd of surprise, t = −3.7, Holm p = 0.004 across 16 tests).
- **After the release:** there is **no tradable drift**. Every drift coefficient has
  Holm p = 1.00, and forecasts have negative out-of-sample R².
- **Strategy:** the pre-registered strategy, which made +0.35 Sharpe in development, delivered
  a **net Sharpe of −0.50** in the locked test:
  - 95% CI [−1.14, +0.14];
  - Deflated Sharpe 0.001;
  - Hansen SPA p = 1.00.

  It failed every pre-registered success criterion. Costs were not the reason: the gross signal
  had no value.

Full write-up: **[docs/REPORT.md](docs/REPORT.md)**.

## What makes it rigorous

- **Point-in-time data.**
  - Release times come from EIA's documented schedules (791 of 793 editions). Unknown times are
    treated conservatively, so entry waits until the information is certainly public.
  - Values are as first published, from 793 archived editions. This found and corrected a
    2016 crude-stock restatement.
- **Contract-aware P&L.**
  - Exchange-published expiries (archived CME calendars and the NYMEX rulebook).
  - Rolls 5 days before expiry; dollar P&L within the contract held; 4 cost tiers.
- **Pre-registration and a code-enforced lock.**
  - The [protocol](docs/04_analysis_protocol.md) was committed before any return was analysed.
  - `integrity.py` refuses 2017+ data until a `spec-freeze-*` tag exists.
  - The test script refuses to run if the code differs from the tag.
  - It was run once from `spec-freeze-v1`, and an identical re-run confirms determinism.
- **Inference for dependent data:**
  - Newey–West regressions with Holm/BH corrections;
  - Clark–West and Diebold–Mariano forecast tests;
  - stationary-bootstrap Sharpe CIs, the Deflated Sharpe Ratio, Hansen's SPA test, and
    permutation and random-sign nulls.

## Documents

| | |
|---|---|
| [docs/REPORT.md](docs/REPORT.md) | Final research report (executive summary through conclusions) |
| [docs/01_research_design_and_data_feasibility.md](docs/01_research_design_and_data_feasibility.md) | Phase 1 design and data feasibility |
| [docs/02_timing_integrity_and_data_budget.md](docs/02_timing_integrity_and_data_budget.md) | Timing standards, integrity protocol, data budget |
| [docs/03_data_quality_report.md](docs/03_data_quality_report.md) | Phase 3 data collection and validation |
| [docs/04_analysis_protocol.md](docs/04_analysis_protocol.md) | Pre-registered analysis protocol, including amendment A1 |
| [docs/experiment_log.md](docs/experiment_log.md) | Every specification evaluated |
| [docs/INTERVIEW_PREP.md](docs/INTERVIEW_PREP.md) | Pitches, 10 hard questions, résumé bullets |
| [docs/learning/](docs/learning/) | Learning notes: foundations; data and EDA; models and backtest |

## Setup and reproduction

Requires [uv](https://docs.astral.sh/uv/), which installs Python 3.12 and the locked
dependencies.

```bash
uv sync
uv run pytest                                              # unit + integration tests, synthetic data, no network
uv run ruff check .

uv run python -m transport_energy.data.build               # Phase 3: download (about 30 min, polite rate limits) + validation tables
uv run python -m transport_energy.data.build --offline     #          re-parse cached files only
uv run python -m transport_energy.analysis.eda             # Phase 4: EDA, development data only
uv run python -m transport_energy.analysis.development     # Phases 5–6: model selection, writes configs/frozen_spec.yaml
TEQ_UNLOCK_TEST=spec-freeze-v1 \
  uv run python -m transport_energy.analysis.locked_test   # Phase 7: the locked test (refuses if code differs from the tag)
uv run python scripts/report_figures.py                    # report figures from saved tables
```

Raw data is downloaded to `data/raw/` (git-ignored) with a SHA-256 manifest. Result tables are
in `reports/tables/` and figures in `reports/figures/`.

## Layout

```
configs/      research.yaml (splits, timing, contracts, costs), data.yaml (sources), frozen_spec.yaml
src/transport_energy/
  data/         downloads + manifest, EIA parsing, release calendar, first-release tables, exchange calendar, quality
  features/     surprise models, event windows and contract-aware returns
  backtesting/  expiries and rolls, dollar P&L, costs, event backtester
  evaluation/   performance metrics, inference (HAC, CW, DM, bootstrap, DSR, SPA)
  analysis/     datasets, EDA, development (Phases 5–6), locked test (Phase 7)
  timing.py     release -> settlement mapping (strict anti-look-ahead)
  integrity.py  code-enforced lock on the 2017+ test period
tests/        unit + integration tests on synthetic data with known answers
scripts/      report figures from saved tables
```

## Data attribution

U.S. Energy Information Administration (EIA): Weekly Petroleum Status Report and petroleum
price series (public domain). NYMEX contract rules: CME Group NYMEX Rulebook chapters 200 and
191. Archived copies of the CME and EIA pages come from the Internet Archive. No vendor data was
used.
