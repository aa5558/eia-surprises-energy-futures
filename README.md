# Transportation Demand Signals for Energy Futures

**Status: Phase 2 (repository scaffolding). No data has been analysed and there are no results yet.**

## Research question

Do model-based surprises in the EIA's weekly gasoline-demand and petroleum-inventory data,
built only from information available before each release, predict WTI (CL) and RBOB (RB)
futures returns *after* the release becomes public? And does a trading rule based on them
survive realistic execution timing and transaction costs out of sample?

The project keeps two questions apart:

1. **Announcement reaction.** Do prices move on the surprise between the last settlement
   before the release and the first one after it? This is a diagnostic and is not tradable
   with daily data.
2. **Post-release drift.** Is there predictable movement from the first settlement after the
   release to the last settlement before the next release? This is the tradable part.

## Design documents

- [Phase 1: research design and data feasibility](docs/01_research_design_and_data_feasibility.md)
- [Timing, research integrity and data budget](docs/02_timing_integrity_and_data_budget.md)
- [Learning notes: foundations](docs/learning/01_foundations.md)

## Setup

```bash
# requires uv (https://docs.astral.sh/uv/)
uv sync              # creates .venv with Python 3.12 and the locked dependencies
uv run pytest        # unit and integration tests (synthetic data only, no network)
uv run ruff check .
```

## Layout

```
configs/             research.yaml (splits, timing, costs, pre-registered hypotheses), data.yaml
src/transport_energy/
  timing.py          release -> settlement mapping, as-of joins (core anti-look-ahead logic)
  integrity.py       code-enforced lock on the 2017+ test period
  backtesting/       expiry calendars, roll schedules, dollar P&L, transaction costs
  evaluation/        performance metrics with explicit annualization
  features/ strategies/ models/ data/ visualization/
tests/               unit + integration tests on deterministic synthetic data
docs/                design documents and learning notes
```

## Data attribution

Source: U.S. Energy Information Administration (EIA). Raw data is downloaded by scripts and
not committed. Vendor futures data (if approved) will never be committed.
