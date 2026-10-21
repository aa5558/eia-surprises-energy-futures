# Phase 1: Research Design and Data Feasibility

*Status: approved 2026-10-21 with amendments. Where this document and [02_timing_integrity_and_data_budget.md](02_timing_integrity_and_data_budget.md) differ (pre-2011 timing rule, EDA boundary, H4, Databento plan), document 02 takes precedence.*

---

## 0. Verdict on the original idea

**The idea as first stated is weak. A narrower version of it is strong.**

"Transportation activity predicts energy futures" sounds appealing but has three problems an interviewer will spot quickly:

1. **Most transportation data is too slow and too thoroughly priced in.** Vehicle miles traveled (VMT) is monthly, comes out with a lag of weeks, and is revised. By the time it is public, the market has already seen four or five weekly EIA demand prints covering the same month. Testing VMT against futures returns mostly tests whether the market can read EIA's weekly report. It can.
2. **Transit ridership (MTA etc.) has almost no economic link to national oil demand.** NYC transit fuel use is a rounding error in US consumption, and ridership is partly a *substitute* for driving. A model using it would be data mining with a story attached.
3. **"Demand goes up, so price goes up" is not a tradable hypothesis.** Predictable demand (summer driving season, holidays) is already in the futures curve. Only *unexpected* information can move prices, and only *slow incorporation* of that information can be traded after the release.

The stronger, defensible project keeps the transportation angle through the right variable. **EIA weekly gasoline product supplied** is the best publicly available high-frequency measure of US transportation fuel demand. The project studies it together with the inventory data released alongside it, at the one moment that information becomes public: Wednesday 10:30 ET.

---

## 1. Data sources: what was actually checked

Everything marked ✅ below was downloaded or fetched during Phase 1 on 2026-10-21. Coverage dates are from parsing the downloaded files. Items marked ⚠️ were looked up but not fully verified. Items marked ❌ were not accessed.

### 1.1 EIA weekly petroleum fundamentals ✅

- **Provider:** US Energy Information Administration, Weekly Petroleum Status Report (WPSR).
- **Access:**
  - Keyless Excel bulk files: `https://www.eia.gov/dnav/pet/hist_xls/<SERIES>.xls`. These **worked without a key**.
  - EIA API v2: `https://api.eia.gov/v2/...`. This **requires a free API key**; the test call returned `API_KEY_MISSING`.
- **Licence:** US government work, public domain. Attribution requested.

| Series ID | Variable | Units | Coverage (verified) |
|---|---|---|---|
| WGFUPUS2 | Product supplied, finished motor gasoline | kb/d | 1991-02-08 → 2026-10-16 (1,862 wks) |
| WRPUPUS2 | Product supplied, total petroleum products | kb/d | 1990-11-09 → 2026-10-16 |
| WCESTUS1 | Crude stocks excl. SPR | kb | 1982-08-20 → 2026-10-16 |
| WCRSTUS1 | Crude stocks incl. SPR | kb | 1982-08-20 → 2026-10-16 |
| WGTSTUS1 | Total gasoline stocks | kb | 1990-01-05 → 2026-10-16 |
| WDISTUS1 | Distillate stocks | kb | 1982-08-20 → 2026-10-16 |
| WCRFPUS2 | Crude field production | kb/d | 1983-01-07 → 2026-10-16 |

**Timing (verified on EIA's schedule page).**
- The standard release is **Wednesday 10:30 ET**, covering the week ending the previous Friday. That is a lag of about 5 days.
- Holiday weeks usually move the release to **Thursday 12:00 ET**. Rare exceptions exist; for example, the Christmas 2025 release was Monday 2025-12-29 at 17:00.

**Point-in-time release calendar (verified).**
- The WPSR archive lists every edition from **August 2011 to October 2026** with its actual release date and data-ending date.
- URL pattern: `/petroleum/supply/weekly/archive/YYYY/YYYY_MM_DD/wpsr_YYYY_MM_DD.php`.
- A few folders carry a `_data` suffix (for example `2022_06_17_data`), which points to irregular releases in June 2022. To be checked in Phase 3.
- **No archive exists before Aug 2011.** For earlier weeks we need a conservative timing rule (§4.3).

**Revisions (partly verified).**
- EIA's own documents say weekly figures are not systematically revised. Past WPSR editions are not republished, and corrections are carried forward.
- Monthly survey data (the Petroleum Supply Monthly, PSM) is the benchmark. Weekly crude production can be re-benchmarked.
- **Open item:** confirm that today's weekly history files equal the first-release values. Method: compare a sample of archived WPSR tables (2011+) with the current history file. If they differ, we use archived first-release values wherever possible.

**Data-quality caveat.** "Product supplied" means disappearance from the primary supply system, not consumption at the pump. Weekly estimates are noisy compared with the monthly PSM. Noise in our signal attenuates any estimated effect (see §3.4).

### 1.2 EIA NYMEX futures prices ✅, but discontinued

- **Access:** `RCLC1..4` (WTI Cushing, contracts 1–4) and `EER_EPMRR_PE1..4_Y35NY_DPG` (RBOB, contracts 1–4), via the same keyless Excel endpoint.
- **What the prices are:** official NYMEX 2:30 pm settlement prices.

| Series | Coverage (verified) |
|---|---|
| WTI contract 1 | 1983-04-04 → **2024-04-05** |
| WTI contract 2 | 1985-01-02 → **2024-04-05** |
| RBOB contract 1/2 | 2005-10-03 → **2024-04-05** |
| Heating oil contracts | 1980 → **2024-04-05** (per EIA page) |

EIA's own page header says: *"Futures prices after April 5, 2024, are not available."*

Three problems found in this data:

1. **No contract identity.** "Contract 1" silently switches to the next contract at expiry, so naive percent changes in contract 1 include fake roll returns.
   - I tested whether roll days can be inferred from prices alone. That heuristic flagged **28–124 candidate "rolls" per year, against about 12 true expiries**, so it does not work. Rolls must come from an explicit **expiry calendar**: the CME rule for each product, checked against the data.
2. **WTI settled at −$37.63 on 2020-04-20.** This was the only non-positive day, at the expiry of the May 2020 contract.
   - Log returns and percent returns are undefined or meaningless there. **P&L must be computed in dollars per contract**: Δprice × multiplier.
   - A strategy that rolls a few days before expiry would not have held that contract. That is realistic, and it must be documented, not exploited.
3. **Nothing after 2024-04-05.** We need a second source, or the sample ends there.

### 1.3 Futures prices after April 2024 ⚠️

| Source | Status | Assessment |
|---|---|---|
| **Databento, CME Globex MDP 3.0 (`GLBX.MDP3`)** | ⚠️ Website checked | Licensed vendor. CME data from 2010, individual contracts with contract definitions (true expiries), daily and intraday bars. **$125 free credits for new accounts** (a 2023 post said credits expire after 6 months; re-check). The exact cost of the pull is unverified, but daily plus 1-minute bars around ~800 release events should be small. **Redistribution terms unverified, so raw data is never committed.** Needs *your* account and API key. |
| Yahoo Finance `CL=F`, `RB=F` | ❌ Not used | Unofficial. Roll method undocumented. Terms prohibit redistribution and automated access. Not defensible in an interview. |
| Nasdaq Data Link "CHRIS" | ❌ | Free continuous-futures dataset, deprecated. |
| CME DataMine | ❌ | Official, paid. |

**Recommendation: Databento.** It also enables the **intraday extension** (§4.5): entering at 10:35 ET instead of the 14:30 settlement. That turns a daily-bar proxy study into a realistic execution study.

### 1.4 Transportation activity ⚠️

| Source | Status | Use |
|---|---|---|
| FHWA Traffic Volume Trends (VMT) | ⚠️ Page checked | Monthly. Latest listed: Aug 2026. Re-adjusted annually and subject to revision. History back to 1970. Publication lag not stated (to be measured from ALFRED vintages). **Secondary use only.** |
| FRED/ALFRED `TRFVOLUSM227NFWA` (VMT), FRED energy series | ⚠️ | FRED's keyless CSV endpoint returned a **"Site Maintenance" page** on 2026-10-21, so it is temporarily down; retry in Phase 3. The FRED API needs a free key. **ALFRED vintages** are the right tool for point-in-time VMT. |
| BTS Transportation Services Index | ❌ Not accessed | Monthly; possible secondary check. |
| MTA ridership | ❌ Not accessed | **Rejected on economic grounds** (§0). |

### 1.5 Spot prices ✅ (context only, not tradable)

| Series | Variable | Coverage (verified) |
|---|---|---|
| RWTC | WTI spot | 1986-01-02 → 2026-10-20 |
| EER_EPMRU_PF4_Y35NY_DPG | NY Harbor conventional gasoline spot | 1986 → 2026-10-20 |
| EER_EPD2F_PF4_Y35NY_DPG | NY Harbor heating oil spot | 1986 → 2026-10-20 |

The NY Harbor RBOB spot series (`EER_EPMRR_PF4_Y35NY_DPG`) returned an empty file. Unresolved.

Spot data is used for EDA only. **It is never presented as futures P&L.**

### 1.6 Analyst consensus forecasts ❌

The Reuters, WSJ and Platts weekly inventory polls are not freely available as history. Economic-calendar websites forbid scraping.

**Consequence:** every "surprise" in this project is a **model-based surprise**. It is named that way and treated as an error-ridden proxy for the true surprise.

### 1.7 Environment check

This machine has **Python 3.9.6 only**: no 3.11+, no `uv`, no `brew`, no `conda`. Phase 2 needs a Python ≥ 3.11 toolchain. I recommend installing `uv`, which can also manage the Python version. This needs your OK.

---

## 2. Comparing the design options

| Criterion | A: Weekly EIA demand and inventory surprises | B: Transportation activity (VMT) → prices | C: Calendar spreads |
|---|---|---|---|
| Economic rationale | Strong. Scheduled information shock about supply and demand. Large prior literature to build on. | Weak to moderate. Information is stale and already in EIA weeklies. | Strong. Theory of storage links inventories to the slope of the curve. |
| Data quality | Good weekly data from 1991. Release calendar verified from 2011. | Monthly, revised, lag unverified. | Needs ≥ 2 contracts with known expiries. EIA C1–C4 to 2024, Databento after. |
| Avoiding look-ahead | Very good. Exact release timestamps exist. | Poor without ALFRED vintages; revisions are a trap. | Good, with the same timing as A. |
| Statistical power | About 1,500 weekly events. | About 300–400 monthly observations; low power. | About 1,500 weekly events. |
| Trading realism | Good with settlement prices; excellent with intraday bars. | Low; monthly rebalancing on stale data. | Good. Spreads are cheaper to trade and have lower beta. Roll handling is harder. |
| Interview relevance | High. Event studies, surprises, HAC, OOS testing, execution timing. | Moderate. | High. Term structure, roll mechanics. |
| Time to build | Moderate. | Low to moderate. | Moderate to high (alone). |
| Originality | Moderate. The literature studies the *announcement reaction*; the **post-release tradable drift** under realistic timing is less studied. | Low as a trading study. | Moderate. |

### Recommendation: Option A as the core, with C as a secondary target and B for validation and falsification only

All three share one data pipeline:

- **A (primary):** model-based EIA surprises → front-month **WTI (CL)** and **RBOB (RB)** futures returns after the release.
- **C (secondary target, same features):** does the same surprise predict the change in the **CL contract-1 minus contract-2 calendar spread**? Theory of storage: an unexpected stock build should weaken the front of the curve relative to later months.
- **B (secondary):**
  - VMT is used to *validate* that weekly gasoline product supplied tracks real driving (monthly aggregation in EDA).
  - It also gives a monthly robustness check with its true publication lag.
  - It is **not** a trading signal.

---

## 3. Final research design

### 3.1 Research question

> **Do model-based surprises in EIA's weekly gasoline demand and inventory data, measured using only information available before each release, predict WTI and RBOB futures returns over the following week, after the release is public? Does a trading rule based on them survive realistic execution timing and transaction costs out of sample?**

This splits into two separately tested questions:

- **Q1, contemporaneous (not tradable, used as a diagnostic):** Do prices react to our surprise measure on release day?
  - If not, the surprise measure is too noisy, and a null result for Q2 is uninformative.
  - This test checks the measuring instrument. It is not a strategy.
- **Q2, predictive (tradable):** After the release, does the price keep moving in the same direction (*underreaction / drift*) or move back (*overreaction / reversal*)?
  - Theory does not fix the sign, so H1 is two-sided.

### 3.2 Hypotheses (fixed in advance)

For target $y \in$ {CL return, RB return, CL C1–C2 spread change} and surprise vector $s_t$:

- $H_0^{(1)}$: $\beta = 0$ in $r^{ann}_t = \alpha + \beta' s_t + \varepsilon_t$ (no announcement reaction).
- $H_0^{(2)}$: $\gamma = 0$ in $r^{post}_{t\to t+h} = \alpha + \gamma' s_t + \delta' x_t + u_t$, where $x_t$ holds price-only controls known at entry (momentum, realised volatility, curve slope).
  - $H_1^{(2)}$: $\gamma \neq 0$.
- $H_0^{(3)}$: the out-of-sample MSE of the fundamentals model is ≥ the MSE of the price-only benchmark.
  - Tested with Clark–West, because the models are nested.

### 3.3 Instruments, frequency and period

| Item | Choice |
|---|---|
| Instruments | NYMEX WTI crude (CL, 1,000 bbl, tick $0.01 = $10) and RBOB (RB, 42,000 gal, tick $0.0001 = $4.20). Specs to be re-checked on CME pages in Phase 3. |
| Event frequency | Weekly: one observation per WPSR release. |
| Price frequency | Daily settlement prices. Optional 1-minute bars (Databento, 2010+). |
| Feature history | Crude stocks from 1982. Gasoline demand and stocks from 1990–91. Five-year seasonal baselines mean features start in **1996**. |
| CL sample | 1996-01 → 2026-10. Ends 2024-04 if the fallback is used. |
| RB sample | 2006-01 → 2026-10. RBOB futures start Oct 2005. |

### 3.4 Surprise construction

All surprises use expanding windows and only data released before the current release.

1. **Inventory change surprises** (crude ex-SPR, gasoline, distillate):
   - Actual change minus the *expected* change.
   - Expectations are compared across three models:
     - (a) the average change in the same calendar week over the prior 5 years (the benchmark EIA itself publishes);
     - (b) a seasonal regression with Fourier terms plus holiday dummies;
     - (c) (b) plus last week's surprise, to allow for autocorrelation.
2. **Gasoline demand surprise:** product supplied minus a seasonal forecast. The forecast uses the same three models plus holiday-week dummies (Memorial Day, July 4, Labor Day, Thanksgiving, Christmas). A smoother 4-week-average version is also tested.
3. **Standardisation:** each surprise is divided by its expanding-window standard deviation.

**Measurement error.** A model-based surprise equals the true surprise plus forecast error. Under classical errors-in-variables, OLS shrinks toward zero:

$$\hat\beta \to \beta\,\frac{\sigma^2_s}{\sigma^2_s+\sigma^2_e}$$

Halova, Kurov & Kucher (2014, *J. Futures Markets*) find that measurement error biases inventory-surprise estimates downward even when survey data is used. Our version will be noisier still. That is a known, stated limitation, and part of why Q1 exists.

**Information leakage.** The American Petroleum Institute's private survey comes out Tuesday at 16:30 ET, so part of the "surprise" is known before Wednesday. Our announcement window (Tuesday settle → Wednesday settle) contains both releases. We cannot separate them without API data, which is paid.

### 3.5 Timing (the central anti-look-ahead rule)

```
Fri F (reference week ends)
  └─ Tue F+4 14:30 ET  settlement P_pre      (API survey at 16:30, private)
       └─ Wed F+5 10:30 ET  EIA release ── information becomes public
            └─ Wed 14:30 ET settlement P_post    ← earliest daily-bar entry (4 h after release)
                 └─ ... holding period ...
                      └─ Tue F+11 14:30 settle   ← exit before the NEXT release
```

- **Announcement return (Q1):** $P_{post} - P_{pre}$. This is not tradable with daily bars.
- **Drift return (Q2):** Wednesday settle → next Tuesday settle. Exiting just before the next release keeps each trade's return free of the next announcement. Longer horizons (h = 2 and 4 weeks) are tested too; their overlapping returns need HAC standard errors.

**Holiday and irregular releases.**
- From 2011 onward, the **archived release date** is used, and entry is at the first settlement after release.
- Before Aug 2011, a conservative rule applies: **entry at Thursday settlement**, which is after release in normal and holiday weeks alike. This rule is checked against the 2011–2026 archive in Phase 3.
- As a robustness check, the whole sample is re-run with Thursday entry.

### 3.6 Continuous contracts and rolling

- **Expiry calendars from CME rules:**
  - CL stops trading about 3 business days before the 25th of the month before delivery. RB stops on the last business day of the month before delivery. Exact rules to be confirmed.
  - Trading days are inferred from the dates in the price data itself.
  - The calendar is checked against the data: on the day after a computed expiry, contract 1 should match the previous day's contract 2 closely.
  - From 2010, Databento contract definitions give the true expiries.
- **Position rule:** hold the nearest contract until **N business days before expiry** (N = 5 by default, with sensitivity tests). Then hold the next contract. Each day's P&L is the price change *of the contract actually held*. A spread between two different contracts is never booked as a return.
- **Return definition:** dollar P&L per contract. Percent returns are always defined on a stated capital base, never on a futures price that may be near zero or negative.

### 3.7 Data splits (fixed now, before any return is examined)

| Segment | CL | RB | Purpose |
|---|---|---|---|
| Development | 1996-01 → 2016-12 | 2006-01 → 2016-12 | Feature design and model fitting. Model selection uses walk-forward (expanding window) validation folds by year, 2006–2016. |
| **Locked test** | **2017-01 → 2026-10** | same | Evaluated **once**, after the specification is frozen in a committed config file and git tag. |

- The test window contains 2020 (COVID crash, negative WTI) and 2022 (Russia–Ukraine). Results are also reported excluding 2020H1.
- **Phase 4 EDA rule:** before the test is run, *fundamental* data may be explored across the full sample. *Return-based* analysis is limited to the development sample.
- **Phase 1 itself ran no return regressions**, so the test set is still clean.

### 3.8 Models (simplest first)

| # | Model |
|---|---|
| 0 | Zero / historical-mean return |
| 1 | Price-only: momentum (1 and 4 weeks), realised volatility, C1–C2 slope (carry) |
| 2 | Model 1 + surprises (OLS) |
| 3 | Ridge / Lasso, penalty chosen by walk-forward validation |
| 4 | Logistic regression on return direction |
| 5 | Gradient boosting, **only if** models 2–3 beat model 1 in validation |

**Statistical toolkit:**

- Newey–West HAC standard errors (overlapping horizons, heteroskedasticity).
- Augmented Dickey–Fuller / KPSS tests on the inputs.
- Ljung–Box tests on residuals.
- Out-of-sample $R^2$ (Campbell–Thompson).
- Clark–West and Diebold–Mariano tests.
- Rolling coefficients, plus Chow / Bai–Perron break tests (shale era ~2014; US crude export ban lifted Dec 2015; 2020).
- Stationary block bootstrap for Sharpe-ratio confidence intervals.

**Multiple testing:**

- The primary family is about 5 surprise features × 3 targets. Holm and Benjamini–Hochberg corrections are reported.
- Strategy variants are judged with the Deflated Sharpe Ratio, and with White's Reality Check or Hansen's SPA test across the grid.
- Every variant tried is logged in an experiment registry, including the failures.

### 3.9 Trading strategy

- **Decision time:** the first settlement after release. Only surprises from releases before that time are used.
- **Signal:** the model-predicted return $\hat r$, or the standardised surprise for the simplest rule.
- **Rule A, threshold:** long or short 1 unit if $|\hat r| > k$ (or $|z| > k$), flat otherwise. $k$ is chosen in validation.
- **Rule B, volatility-scaled:** number of contracts ∝ $\hat r/\hat\sigma^2$, capped, targeting 10% annual volatility on a stated capital base. Defaults: $1M capital, notional ≤ 2× capital, collateral earns the T-bill rate, results reported as excess returns.
- **Exit:** Tuesday settlement before the next release (default), or after h weeks.

**Costs, per contract per side:**

| Scenario | Spread + slippage | Commission + fees | Total CL / RB |
|---|---|---|---|
| Optimistic | ½ tick | $1.50 | $6.50 / $3.60 |
| Base | 1 tick | $2.50 | $12.50 / $6.70 |
| Conservative | 2 ticks | $4.00 | $24.00 / $12.40 |
| Stress | 4 ticks | $5.00 | $45.00 / $21.80 |

Roll trades are charged as well. *Commission levels are assumptions, to be checked against current broker and exchange fee schedules.*

**Benchmarks:**

- always-long front month (roll-adjusted);
- price-only model strategy;
- random-sign strategy with the same turnover.

### 3.10 Robustness and falsification (fixed in advance)

1. **Stale-signal placebo:** use the surprise from 4 releases earlier. Information that old should be fully priced. This needs no future data.
2. **Non-release-day placebo:** run the same rule with entry on Friday or Monday using the latest *available* surprise. If the effect is about information arrival, it should concentrate after releases.
3. **Cross-target placebo:** gasoline-demand surprises should matter more for RB than for CL. A finding the other way round is a red flag.
4. **Block-permutation test:** shuffle surprises in blocks of whole years to build a null distribution for the strategy Sharpe ratio.
5. **Other variants:** sensitivity to cost scenarios, roll offset N, holding horizon, entry day (Wednesday vs Thursday), surprise model, and threshold $k$; winsorising surprises; excluding 2008–09 / 2020 / 2022; sub-periods before and after the shale era.

### 3.11 Statistical power: what to expect

To reach t ≈ 2 with n weekly observations, the predictive correlation must be at least about $2/\sqrt{n}$. A rough mapping to an annualised Sharpe ratio is $SR \approx \rho\sqrt{52}$ (fundamental law of active management: information ratio ≈ IC·√breadth).

| Sample | n (weeks) | Minimum detectable ρ | Implied gross annual Sharpe |
|---|---|---|---|
| Development, CL | ~1,090 | 0.061 | ~0.44 |
| Locked test, Databento | ~510 | 0.089 | ~0.64 |
| Locked test, EIA-only fallback | ~375 | 0.103 | ~0.74 |

Weekly commodity return predictability, where it exists, is usually smaller than this. **A likely honest outcome:**

- a clear announcement-day reaction (Q1);
- weak or no drift after the release (Q2);
- a strategy whose net Sharpe ratio is not distinguishable from zero.

That is still a defensible, interview-worthy result *if the methods are rigorous*. A well-documented null result is better than an overfitted backtest.

---

## 4. Implementation roadmap

| Phase | Deliverables | Est. time (part-time, ~12 h/week) |
|---|---|---|
| 2. Repo and environment | `uv` + Python 3.12, `pyproject.toml`, configs (`data.yaml`, `research.yaml` with splits and fixed choices), package skeleton, CI-style `pytest` setup, first timing and roll unit tests | 0.5 week |
| 3. Data | EIA downloaders (Excel bulk + API v2), WPSR archive release-calendar scraper, expiry-calendar builder with validation, Databento loader (cost quote before any purchase), first-release vs current comparison, data-quality report | 1.5 weeks |
| 4. EDA | Demand trends and seasonality, inventory cycles, VMT vs product supplied, price behaviour by regime, missing and irregular weeks | 1 week |
| 5. Signal research | Surprise models compared by forecast accuracy, Q1 announcement regressions, Q2 development-sample regressions with HAC, walk-forward model selection, multiple-testing tables | 2 weeks |
| 6. Strategy and backtest | Vectorised weekly event backtester on dollar P&L, roll engine, cost model, sizing rules, look-ahead tests (changing future data must not change past positions) | 1 week |
| 7. Evaluation | Spec freeze (git tag) → one locked-test run; robustness grid; placebos; Deflated Sharpe / SPA; regime tables | 1 week |
| 8. Report and README | Research report, charts with sources, reproducibility commands | 1 week |
| 9. Interview prep | Concept map, derivations, likely interviewer challenges, résumé bullets based only on verified results | 0.5–1 week |

**Total:** roughly **8–9 weeks part-time.** It would be about half that if worked on intensively.

**Optional extension (§4.5): intraday execution with Databento 1-minute bars, 2010+.**
- Enter at 10:31, 10:35 or 11:00 ET instead of the 14:30 settlement.
- Measure how much of the reaction happens in the first minutes.
- This gives a realistic estimate of how much signal value is left for a non-HFT trader. Interviewers at market makers value this kind of analysis highly.
- About 1 extra week.

## 5. Main risks

1. **The signal is too weak and the surprise measure too noisy** (most likely). Mitigation: the Q1 diagnostic, power analysis, honest reporting.
2. **Futures data after 2024-04.** Depends on Databento access and cost. Fallback: end the sample at 2024-04-05.
3. **Pre-2011 release timing** is not documented by an archive. Mitigation: conservative Thursday-entry rule.
4. **Daily settlements cannot capture the immediate reaction.** The study measures *post-release* predictability only. This is stated clearly, and intraday data is the remedy.
5. **Regime breaks:** shale, the 2015 export-ban repeal, 2020, 2022. Handled with rolling estimates, sub-sample reporting and break tests.
6. **Multiple testing.** Handled with the fixed-in-advance feature list, the experiment registry, and corrections.
7. **Weekly-data revisions.** Checked against archived first releases (2011+).

## 6. Remaining verification tasks

- [ ] Databento: account, cost quote for CL/RB `ohlcv-1d` + `definition` (+ `ohlcv-1m` around releases), personal-use licence terms.
- [ ] Exact CME expiry rules for CL and RB, including historical changes.
- [ ] Re-check the CME contract specs and current fee schedules.
- [ ] FRED / ALFRED access once maintenance ends. VMT publication lag from vintages.
- [ ] WPSR first-release values vs current history (sample of archived tables).
- [ ] Irregular releases (June 2022 `_data` editions, government shutdowns).
- [ ] Why the empty `EER_EPMRR_PF4_Y35NY_DPG` (RBOB spot) download.

## 7. Sources accessed in Phase 1

- EIA keyless Excel series files: https://www.eia.gov/dnav/pet/hist_xls/ (series listed in §1)
- EIA NYMEX futures page: https://www.eia.gov/dnav/pet/pet_pri_fut_s1_d.htm
- EIA WPSR release schedule: https://www.eia.gov/petroleum/supply/weekly/schedule.php
- EIA WPSR archive: https://www.eia.gov/petroleum/supply/weekly/archive/
- EIA WPSR revision notice: https://www.eia.gov/petroleum/supply/weekly/includes/revision-notice.php
- EIA API v2 (key required): https://api.eia.gov/v2/
- FHWA Traffic Volume Trends: https://www.fhwa.dot.gov/policyinformation/travel_monitoring/tvt.cfm
- Databento GLBX.MDP3: https://databento.com/datasets/GLBX.MDP3 ; pricing: https://databento.com/pricing
- Halova, Kurov & Kucher (2014), *Noisy Inventory Announcements and Energy Prices*, J. Futures Markets 34(10): https://ideas.repec.org/a/wly/jfutmk/v34y2014i10p911-933.html
- FRED CSV endpoint (returned a maintenance page): https://fred.stlouisfed.org/graph/fredgraph.csv
