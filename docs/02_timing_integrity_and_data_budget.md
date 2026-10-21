# Timing Standards, Research Integrity and Data Budget

*Approved Phase 1 design, amended 2026-10-21 per review. Covers review items 2, 3, 6 and 7.
Nothing in this document has been run on real return data.*

---

## 1. How observations before August 2011 are used (review item 2)

### 1.1 The problem

The WPSR archive gives verified release dates only from **August 2011**. Before that, we know
each report's *reference week* (the week ending Friday $F$), but not exactly when it was
published. A trading simulation that enters "at the first settlement after the release" needs
that timestamp. If we assume Wednesday 10:30 and the true release was later, we would be
trading on information before it existed. That is look-ahead bias.

### 1.2 Principle: match each use of the data to the timing precision it needs

Not every use of the data needs a precise timestamp. There are four uses, each with its own
timing standard:

| Use | What it needs to be look-ahead-free | Sample |
|---|---|---|
| **U1. Estimating expectation (surprise) models** | Only the *order* of releases: week $t-1$'s report was public before week $t$'s. No timestamp needed. | 1991 → |
| **U2. Announcement-window economics** (Q1, H4) | A return window that is *certain* to contain the release and no other release. | 1996 → (wide window); 2011-08 → (exact window) |
| **U3. Trading simulation, precise timing** (primary strategy) | The exact release timestamp, so entry is at the first settlement after it. | **2011-08 → 2016-12** (development), **2017 →** (locked test) |
| **U4. Trading simulation, conservative timing** (long-sample check) | Entry that is after the release under a weak, checked assumption. | 1996 → 2016 (development), 2017 → (test) |

**U1 (surprise models).** The surprise for week $t$ is
$s_t = x_t - \mathbb{E}[x_t \mid x_{t-1}, x_{t-2}, \dots]$. Each conditioning value $x_{t-k}$
was published in an earlier report, before $x_t$. So the expectation uses only information
public before release $t$, whatever the exact clock times. The one extra requirement is that
the history files contain the values as first published, not later revisions. That is checked
on the 2011+ archive in Phase 3. If revisions turn up, pre-2011 surprises are flagged as built
from possibly revised data.

**U2 (wide window).** The **Friday-to-Friday return**, from the settlement on $F$ to the
settlement on $F+7$, contains exactly one WPSR release, under the following assumption.

> **Assumption A (release window).** In weeks with no federal holiday, the report for
> reference week $F$ was published after the settlement on Friday $F$ and before the
> settlement on Friday $F+7$.

The previous report (for $F-7$) came out around Wednesday $F-2$, and the next one (for $F+7$)
around Wednesday $F+12$. Both fall outside the window. The window is wider than needed, which
adds price noise unrelated to the release and weakens the test. It never adds look-ahead.

**U4 (conservative trading).** Enter at the **Friday $F+7$ settlement**. Exit at the
**Tuesday $F+11$ settlement**, the last one before the next normal Wednesday release. This
needs Assumption A plus one more: the next report was not released before Tuesday 14:30.

Two things follow:

- This strategy tests a **late drift**, starting about 2 days after a normal release. Any
  edge found will be smaller than what a precise-timing strategy could capture. That is
  conservative.
- It applies the same rule in every year, so pre-2011 and post-2011 results are directly
  comparable.

**Holiday weeks before Aug 2011** (a US federal holiday between Monday $F+3$ and Friday
$F+7$) are **excluded** from U2 and U4. Holidays are where release delays cluster (the
Christmas 2025 report came out 10 days after its reference Friday). The calendar comes from
`pandas` (`USFederalHolidayCalendar`), so no extra dependency is needed.

**Checking Assumption A (Phase 3).** Using the 2011–2026 archive, count the non-holiday
releases that fell outside the window. If the count is not zero, list every exception (for
example the June 2022 outage) and decide whether the assumption needs a wider margin. We will
also look for documentary evidence of the pre-2011 release schedule. If the schedule before
some date cannot be documented, U2 and U4 will start at the first date where it can.

### 1.3 How the 1996–2016 development period is used without look-ahead

Three different leaks are possible. Each is closed separately.

1. **Look-ahead in features.** Every feature is a *causal* function of releases published
   before the decision time: expanding windows, strictly-earlier as-of joins (`align_asof`),
   and no centred or full-sample statistics. Even tercile cut-offs (H4) use expanding
   quantiles, never full-sample ones.
2. **Look-ahead in execution.** Entry is always at a settlement after the release. For U3 this
   uses archived timestamps; for U4 it relies on Assumption A, checked on the archive.
3. **Look-ahead from the researcher.** Design choices made by looking at 1996–2016 results
   are in-sample with respect to that period. So **development-period performance is never
   reported as out-of-sample evidence**. Model selection uses walk-forward (expanding-window)
   folds *inside* the development period. Those give pseudo-out-of-sample scores for choosing
   models; the scores are not the final result. **The only out-of-sample evidence is the
   2017–2026 test**, run once.

### 1.4 Consequences for statistical power

Precise-timing trading development data is only about 280 weekly events (2011-08 to
2016-12). That is not enough to tune much. So:

- most specification work (surprise models, controls) uses U1 and U2 on the long sample;
- the precise-timing strategy gets very few tunable parameters (§4).

---

## 2. Research integrity protocol (review item 7)

1. **Code-enforced lock.** `transport_energy.integrity.guard_development()` raises on any data
   dated 2017-01-01 or later, unless `TEQ_UNLOCK_TEST` names an existing `spec-freeze-*` git
   tag. This is tested (`tests/unit/test_features_rules_integrity.py`).
2. **The EDA boundary is stricter than in Phase 1.** Phase 4 EDA, *including fundamentals*,
   is limited to dates up to 2016. Seeing, say, 2020's demand collapse could quietly shape
   the surprise models.
   - Automated data-quality checks (missing counts, schema, timing validation) run on all
     dates, but they produce counts, not plots or return statistics.
   - Descriptive analysis of 2017–2026 (2020, 2022) is produced **after** the locked test run,
     in Phase 7.
3. **Spec freeze.** Before the test, one commit records the final config: surprise model,
   features, thresholds, sizing, costs and roll offset. That commit is tagged
   `spec-freeze-v1`.
4. **One run.** The test runs once from the frozen tag, and its outputs are saved as-is.
5. **Post-hoc changes are labelled.** If a bug is found after the test, it is fixed, re-run,
   and **both** results are reported, with the change described in `docs/experiment_log.md`.
   Strategy parameters are never changed in response to test results.
6. **Experiment log.** Every development-period specification tried, successful or not, is
   logged with its date and purpose. The log feeds the multiple-testing corrections (Deflated
   Sharpe Ratio, SPA).

---

## 3. Secondary hypothesis H4: does inventory state change the response? (review item 6)

**Economic idea: the theory of storage.**

- When inventories are scarce, there is little buffer between supply and demand. The supply
  curve is steeper, and the convenience yield on a physical barrel is high and very sensitive
  to stock levels.
- So a given surprise should move prices more when inventories are low.
- Some studies find the opposite seasonal pattern (Halova et al. 2014 report smaller winter
  effects). **H4 is therefore tested two-sided.**

**Fixed specification (one interaction, no threshold search):**

$$r_t = \alpha + \beta\, s_t + \gamma\, L_{t-1} + \delta\,(s_t \times L_{t-1}) + \varepsilon_t$$

- $s_t$ is the standardised model-based surprise in stocks ($s_t > 0$ means an unexpected
  build).
- $L_{t-1}$ is the **previous week's** stock level, as a z-score against the mean and standard
  deviation of the same calendar week over the prior 5 years.
  - It describes the state *before* the release, so it is not mechanically tied to $s_t$.
  - It was public at release $t-1$.
- **Storage-theory prediction:** builds are bearish ($\beta < 0$) and hurt more when stocks
  are low. With $L < 0$ meaning low stocks, that implies $\delta > 0$.
- $H_0: \delta = 0$ against $H_1: \delta \neq 0$, with Newey–West standard errors.

**Pre-registered pairs.**
- Crude surprise × crude state → CL.
- Gasoline surprise × gasoline state → RB.

Each pair is tested on the announcement window (Q1, where there is power) and the drift
window (Q2). That makes **4 tests, with a Holm correction within the H4 family**.

**One robustness check.** Split events by expanding-window terciles of $L_{t-1}$ and compare
the slope on $s_t$ in the bottom and top terciles. There is no searching over cut-offs,
alternative state definitions or lags. Cushing stocks (arguably the relevant measure for WTI)
are noted as an idea for future work, *not* tested, to keep the family small.

---

## 4. How much tuning is allowed

Number of parameters chosen in development, all by walk-forward validation:

| Item | Options | Count |
|---|---|---|
| Surprise model | 5-year same-week mean / seasonal regression / seasonal + AR(1) | 3 |
| Threshold $k$ (threshold rule) | {0.5, 1.0, 1.5} standard deviations | 3 |
| Ridge penalty (if used) | log-grid of 10 | 10 |
| Roll offset, holding horizon, cost scenario | **Not tuned.** Reported as sensitivity analysis only. | 0 |

Everything else is fixed in `configs/research.yaml`.

---

## 5. Databento: minimum data and cost estimate (review item 3)

**Nothing has been bought or downloaded. No account exists.**

### 5.1 What Databento is needed for

| Period | Futures settlements available from | Need Databento? |
|---|---|---|
| 1996 – 2016 (development) | EIA (free) | **No** |
| 2017 – 2024-04-05 (test) | EIA (free) | Optional, for a single consistent test source |
| 2024-04-08 – 2026-10 (test) | nothing free | **Yes** |
| 2010-06 – 2016-12 (development) | EIA *and* Databento | Overlap used to **validate** Databento against EIA without touching test-period prices |
| Intraday around releases, 2011-08 → | nothing free | Optional extension: execution realism |

### 5.2 Can we buy only announcement windows? Yes

- Historical requests take arbitrary start and end times, and billing is by the bytes
  returned (priced in $/GB of uncompressed binary data).
- So we can request 1-minute bars for specific windows only. For example, 10:00–15:00 ET on
  each of about 790 release days since 2011-08, plus a matched set of non-release days for
  the placebo test.
- **Continuous symbols** (`CL.c.0`, `CL.c.1`, ...) return just the first, second, ...
  expiring contract, and Databento maps each date to the actual instrument. That avoids paying
  for the whole CL chain, which also includes thousands of spread instruments.
- Free metadata calls can quote the exact cost of a request *before* it is made. They need an
  account and key; I have not verified that they cost nothing.

### 5.3 Size estimate

Record sizes are approximate, from the Databento binary format spec as I recall it: about 56 B
for an OHLCV bar, about 80 B for a statistics record, and a few hundred bytes for a contract
definition. **To be confirmed with the cost endpoint.**

| Tier | Request | Estimated size |
|---|---|---|
| **1a, required** | Daily settlement proxy: 1-minute bars 14:00–14:31 ET, 6 continuous contracts (CL and RB × 3 nearbys), 2010-06 → 2026-10 (~4,100 days) | 4,100 × 31 × 6 × 56 B ≈ **43 MB** |
| **1b, required** | Contract definitions for the same 6 continuous contracts (true expiries, multipliers) | ≈ **5–15 MB** |
| **1c, conditional** | *Official* settlements (statistics schema). Cannot be filtered to settlement-only on the server; size unknown, roughly 50–1,000 records/instrument/day | **~30 MB – 2 GB**. Price one month first. |
| **2, recommended** | Release windows: 1-minute bars 10:00–15:00 ET, CL and RB × 2 nearbys, ~790 release days | 790 × 300 × 4 × 56 B ≈ **53 MB** |
| **2p, recommended** | Same window on ~790 matched non-release days (placebo) | ≈ **53 MB** |

**Plausible total: about 150 MB (without official settlements) to about 2 GB (with them).**

### 5.4 Cost estimate

Databento does not publish per-schema $/GB rates on its public pricing page. A third-party
review cites "from $0.50/GB", which I have not verified. Even at a pessimistic $10–20/GB:

- tiers 1a + 1b + 2 + 2p (~150 MB) ≈ **$1.50–$3**;
- adding 1c in the worst case (2 GB) ≈ **$20–40**.

Both are well within the **$125 free credit**.

**Caveats:**
- The credits **expire 6 months after signup** (one set per team). So sign up only when Phase 3
  is ready to download everything in one planned pass.
- Personal-use licensing and redistribution terms for historical CME data are **unverified**.
  Vendor data stays in git-ignored `data/raw/vendor/` and is never committed or shared. Charts
  of derived results should be acceptable, but this will be confirmed in the terms.

### 5.5 Choosing the daily settlement source (Phase 3, decided by data, on the overlap)

- CME settles CL from the volume-weighted average price of trades between 14:28 and
  14:30 ET (to be confirmed in the CME rulebook).
- From 1-minute bars we can build a settlement *proxy*: volume-weighted typical prices over
  14:28–14:30.
- We compare it with EIA's official settlements over **2010-06 to 2016-12** (development
  period only).
  - If the median absolute difference is ≤ 1 tick and large errors are rare, the proxy is
    used and tier 1c is skipped.
  - Otherwise we price tier 1c and ask for approval.
- `ohlcv-1d` bars were rejected: they follow UTC days and close at the end of the electronic
  session, about 2.5 hours after settlement. That is a timing mismatch with the EIA series.

### 5.6 Proposed purchase procedure

1. You create the account and put the key in `.env`. I install the optional `vendor`
   dependency.
2. I run **cost quotes only** for each tier and show you the exact numbers.
3. You approve specific tiers. I download them and record the request parameters and
   checksums in `data/raw/vendor/MANIFEST.json`.

**Fallback if Databento is declined:** the test sample ends on 2024-04-05 (about 375 test
weeks instead of about 510), and the intraday extension is dropped.
