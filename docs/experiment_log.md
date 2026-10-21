# Experiment Log

Every specification evaluated on real return data is recorded here, whether or not it worked.
This log feeds the multiple-testing corrections (Deflated Sharpe Ratio, SPA test).

| # | Date | Phase | Sample | Specification | Purpose | Result | Kept? |
|---|---|---|---|---|---|---|---|
| — | 2026-10-21 | 1–2 | — | none | No return data has been analysed yet | — | — |
| 1 | 2026-10-21 | 3–5 | — | Analysis protocol (docs/04) | Fix every Phase 4–7 procedure before any return is examined | committed before any return analysis | — |
| 2 | 2026-10-21 | 5–6 | dev 2006–16 | v1: Rule A on M3 (λ=1000), z = r̂/sd(fit); k∈{0.5,1,1.5}; Rule B; benchmarks; 3 cost variants | protocol §4–5 | primary k=1.5 net Sharpe −0.16; all surprise strategies < 0; price-only +0.40 | superseded by A1 |
| 3 | 2026-10-21 | 5–6 | dev 2006–16 | Amendment A1: z = (r̂ − mean fit)/sd(fit); same grid | v1 signal was a constant-sign bet on the mean drift | see v2 tables | yes |
| 4 | 2026-10-21 | 7 prep | dev 2012–16 | Dry run of the locked-test script on development data | catch bugs before the freeze (fixed: perf_of default dates bound at import) | mechanics only, not evidence | — |
| 5 | 2026-10-21 | 7 | — | **Spec freeze** `configs/frozen_spec.yaml`, tag `spec-freeze-v1` | protocol §6 | — | — |
| 6 | 2026-10-21 | 7 | **locked test 2017-01 → 2024-04-05** | Single run from `spec-freeze-v1` (all pre-registered tests and robustness variants) | confirmatory | Primary net Sharpe −0.50 [−1.14, +0.14], DSR 0.0008, SPA p = 1.00 → **fails all criteria**; Q1 RB←gasoline Holm p = 0.004; no drift (Holm p = 1) | reported as is |
| 7 | 2026-10-21 | 8 | — | Reproducibility: offline Phase 3 build, EDA, development pipeline and the locked test re-run from the same tag; outputs diffed | determinism check, not a new evaluation | identical outputs (see README) | — |

**Post-test note.** Nothing in `src/` or `configs/` changed after `spec-freeze-v1`. Report figures are drawn by
`scripts/report_figures.py` from saved tables. Known reporting quirk in the frozen code: per-market Sharpe
columns of the `excl_2020H1` robustness row do not apply the exclusion (the combined figure does).
