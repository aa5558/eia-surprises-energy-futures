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
