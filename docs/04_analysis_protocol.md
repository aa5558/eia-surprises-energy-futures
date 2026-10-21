# Analysis Protocol for Phases 4–7 (fixed before any return was examined)

*Committed 2026-10-21, before any regression, forecast or backtest on futures returns had been
run, in development or test data. It turns the design in documents 01 and 02 into exact
procedures. Where it fills a gap those documents left open, the gap is marked **[filled]**
and the reason is given. Any later change is logged in `docs/experiment_log.md`.*

---

## 1. Samples

| Name | Events | Timing | Use |
|---|---|---|---|
| Development, precise | WPSR editions 2011-08 → 2016-12 | archived release date; documented or conservative time | in-sample estimates |
| Development, long | reference weeks 1996 → 2016, excluding holiday weeks | conservative: announcement window Fri F → Fri F+7; drift window Fri F+7 → Tue F+11 | in-sample estimates; training the forecasting models |
| **Locked test** | WPSR editions 2017-01 → 2024-04-05 | precise | **the only out-of-sample evidence** |
| Test, conservative | same weeks | conservative | robustness only |

The test ends on 2024-04-05 because EIA stopped publishing futures settlements then, and
Databento was deferred (doc 02 §5 fallback). RB events start in 2006, after the 5-year
baseline that follows the start of RBOB trading in October 2005. CL events start in 1996.

Returns are compounded **within the contract held**, rolling 5 business days before the
exchange-documented expiry. They are simple returns of the held contract. Calendar-spread
changes are in $/bbl.

## 2. Surprises (fundamentals only, no returns)

The four pre-registered series:
- weekly change in crude stocks excluding SPR;
- weekly change in gasoline stocks;
- weekly change in distillate stocks;
- the level of gasoline product supplied (demand).

Three expectation models are compared: the 5-year same-week mean, a seasonal regression, and
the seasonal regression plus AR(1). Their definitions are in
`src/transport_energy/features/surprises.py`.

- **Selection:** for each series, the model with the lowest RMSE over development forecast
  weeks 2001–2016 (all three models have forecasts from 2001). Diebold–Mariano tests are
  reported. This uses fundamentals only.
- **Standardisation:** $z_t = s_t/\mathrm{sd}(s_{<t})$, using the expanding standard
  deviation of past surprises, with at least 52 weeks.

## 3. Primary hypothesis family (16 tests)

For each market $m\in\{\mathrm{CL},\mathrm{RB}\}$ and window $w\in\{\text{ann}, \text{drift}\}$:

$$r^{w}_{m,t} = \alpha + \sum_{j=1}^{4}\beta_j z_{j,t} + \delta' x_{m,t} + \varepsilon_t,$$

- $x$ (drift only) holds 1-week and 4-week momentum, 20-day realised volatility and the
  C1–C2 carry, all measured at the entry settlement. The announcement regression has no
  controls.
- Standard errors are Newey–West, with the plug-in lag.
- That gives 4 regressions × 4 coefficients = **16 p-values**. Holm and Benjamini–Hochberg
  corrections are applied within the family.
- The test-period family is the confirmatory one. Development results are reported but
  labelled in-sample.

**Secondary families** (Holm within each):
- **Calendar spread:** crude $z$ → change in CL held-minus-next spread, announcement and
  drift windows (2 tests).
- **H4:** as in doc 02 §3 (4 tests). The state $L_{t-1}$ is the previous week's level
  z-score against the same calendar week in the prior 5 years.

## 4. Forecasting models for the drift return

- **Walk-forward:** expanding window, refit every January, training on all earlier
  development-long and precise events. Each event uses the timing of its own regime.
- **Development validation years:** 2006–2016.
- **Test years:** 2017–2024, using the same refit procedure. Data from before each refit
  date is legitimately in the past.

| Model | Definition |
|---|---|
| M0 | expanding mean of past drift returns |
| M1 | OLS on $x$ (price-only) |
| M2 | OLS on $x$ + four $z$ |
| M3 | ridge on standardised M2 regressors. $\lambda$ comes from a 10-point log grid $10^{-2}\dots10^{3}$, chosen by inner walk-forward MSE on development years 2006–2016 and then frozen. |
| M4 | logistic regression on the sign of the drift. Reported as hit rate and log loss; not used for sizing. |
| M5 | gradient boosting, **only** if M2 or M3 beats M1 in development validation with Clark–West $p<0.05$ |

Metrics:
- out-of-sample $R^2$ against M0;
- Clark–West for M2 vs M1 and for M3 vs M1;
- Diebold–Mariano for M2 vs M3.

## 5. Strategy (one primary specification)

- **Signal:** $\hat z_t = \hat r_t/\mathrm{sd}(\hat r_{<t})$, where $\hat r_t$ comes from
  whichever of M2 and M3 has the lower development-validation MSE.
- **[filled]** The direction is taken from the forecast itself; there is no separate sign
  parameter.
- **Primary rule:** Rule A (threshold) on each market's own drift forecast, holding from the
  entry settlement to the exit settlement.
  - $k\in\{0.5, 1.0, 1.5\}$, chosen by development-validation **net** Sharpe (base costs,
    2006–2016, CL+RB combined).
  - **Primary metric:** the net Sharpe of the combined CL+RB portfolio under the base cost
    scenario, with precise timing and roll offset 5.
- **Secondary rule:** Rule B (volatility-scaled), which has no parameters.
- **Sizing:** vol target 10% a year on $1M, with gross notional capped at 2× capital
  (`event_backtest.py`).
- **Benchmarks:**
  - always long, with the same windows and sizing;
  - a price-only strategy: Rule A on M1 forecasts with the same $k$;
  - random signs with the same $|q|$ schedule (1,000 draws).

## 6. Locked test and inference

Before the test:
- the frozen values go in `configs/frozen_spec.yaml`: surprise model per series, ridge
  $\lambda$, chosen model, $k$, and the cost scenarios;
- that file is committed and tagged `spec-freeze-v1`;
- the test is run once with `TEQ_UNLOCK_TEST=spec-freeze-v1`, and outputs are stored as
  produced.

Inference on the test:
- a stationary-bootstrap 95% CI for the Sharpe ratio (mean block 8 weeks, 5,000 draws) and
  the bootstrap probability that Sharpe ≤ 0;
- the Deflated Sharpe Ratio, with the number of trials and their Sharpe variance taken from
  the development experiment log;
- Hansen's SPA test across the robustness-grid variants against a zero-return benchmark.

## 7. Robustness (fixed list; reported whatever the outcome)

- **Cost scenarios:** optimistic, base, conservative, stress.
- **Roll offset:** 3, 5 and 10 business days.
- **Entry timing:**
  - entry one settlement later (Thursday);
  - **late-entry placebo:** enter at the first settlement on or after the Monday following
    the release.
- **Stale-signal placebo:** use the surprise from 4 releases earlier.
- **Cross-target placebo:**
  - RB positions driven by the CL forecast, and the reverse;
  - for the H1 family: gasoline-demand surprises should matter more for RB than for CL.
- **Year-block permutation:** shuffle signals across calendar years (1,000 draws) to build a
  null distribution for the Sharpe ratio.
- **Signal variants:** surprises winsorised at expanding 1%/99% quantiles; the alternative
  surprise models.
- **Threshold:** $k \in \{0.5, 1.0, 1.5\}$.
- **Sample splits:** excluding 2020-H1; sub-periods 2017–2019 and 2020–2024-04; conservative
  timing.

## 8. What counts as a finding

A strategy "works out of sample" only if all three hold:
1. the primary metric's bootstrap 95% CI lies above 0;
2. the Deflated Sharpe Ratio is above 0.95;
3. the SPA p-value is below 0.05.

Anything weaker is reported as *no reliable evidence*. Coefficient findings require a Holm
p-value below 0.05 in the test family.

---

## 9. Amendments made during development (before the spec freeze; test data untouched)

**A1 — signal standardisation (2026-10-21).**
- **Finding.** The first development run (registry v1, kept in
  `reports/tables/experiments_development_v1.csv`) chose ridge $\lambda=1000$, the heaviest
  penalty on the grid. Its forecasts were close to the training mean of the drift return.
  Dividing them by the small dispersion of fitted values gave $|\hat z|>k$ in most weeks, with
  the sign of the historical mean drift. For RB, 255 of 381 validation weeks passed the
  threshold. The "surprise strategy" was mostly a constant short.
- **Change.** $\hat z_t=(\hat r_t-\bar{\hat r}_{train})/\mathrm{sd}(\hat r_{train})$: the
  forecast's deviation from the unconditional mean, standardised by the dispersion of the
  fitted values. Both statistics come from the same refit. The unconditional drift is already
  covered by the always-long benchmark.
- **Disclosure.** I found the problem while investigating why the v1 development results were
  negative. That is a researcher degree of freedom. The v1 trials stay in the trial count used
  for the Deflated Sharpe Ratio, and the v1 results are reported alongside v2.
