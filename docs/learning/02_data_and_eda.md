# Learning Notes 2: Point-in-Time Data (Phase 3) and Exploratory Analysis (Phase 4)

Each section covers:
- the economic intuition;
- the mathematics or statistics;
- the Python, with file references;
- why the decision matters;
- the key takeaway.

---

## 1. "Point-in-time" means three different dates

Every weekly number has three dates attached:

| Date | Example | What it is |
|---|---|---|
| Economic date | Friday F, end of the data week | what the number is *about* |
| Release time R | Wednesday 10:30 ET | when the number became *public* |
| Vintage | first print vs today's file | *which version* of the number |

A backtest is honest only if a decision at time S uses numbers with R < S **and** the vintage
that existed at S. Phase 2 handled R. Phase 3 found that the vintage matters too.

**Takeaway.** Most look-ahead bugs are not future prices. They come from using a number before
its release timestamp, or a revised number the market never saw. The two are handled
separately: release times come from documented schedules, and values from archived first
prints.

---

## 2. Release times: observed date vs documented time vs assumption

**Economic intuition.** If you assume the report came out at 10:30 when it actually came out
at 17:00, your "entry after the release" happens *before* the information existed.

**What we can and cannot observe.**
- The WPSR archive gives the **release date** of every edition since August 2011.
- **No source gives the actual release time.** What exists is EIA's *schedule*: "Wednesdays at
  10:30, with these holiday exceptions". The live page plus 194 archived copies document this
  from 2006 on.

**The rule (`data/release_calendar.py`).**
- A scheduled time is used only if
  - a schedule page in force for that period stated it, **and**
  - the observed date equals the scheduled date.
- Otherwise the release is an *interval*: the whole day, `[D 00:00, D 23:59:59]`.
- 791 of 793 editions got documented times. Two got intervals: the Hurricane Sandy week, and
  a delayed release in November 2023.

**Using an interval without look-ahead (`timing.build_event_table`).**
- The **pre-release** window closes at the *earliest* possible release time.
- The **entry** opens after the *latest* possible release time.

So uncertainty can only widen the announcement window and delay the entry. It can never let a
trade see the number early.

**Why not just assume 10:30?** Holiday releases moved from 10:30 (2007) to 11:00 (2014–15) to
12:00 (2025), and one 2025 release was at 17:00, after the settlement. Assuming a time is
exactly the kind of quiet bias an interviewer will probe.

**Validating the pre-2011 assumption.**
- Before 2011 there are no observed dates. The conservative strategy assumes the report was
  out by F+7 at 14:29 (Assumption A).
- This was tested on every observed release since 2011: 0 of 635 non-holiday weeks violated
  it.
- *Takeaway:* the assumption becomes a test with a known false-positive rate. With 0 violations
  in 635 weeks, the "rule of three" gives a 95% upper bound of 3/635 ≈ 0.5% on the true
  violation rate.

---

## 3. Revisions and the 2016 crude-stock restatement

**What we found.**
- Today's history file reports 2011–2016 crude stocks about 22–33 million barrels lower than
  what EIA published at the time, because EIA restated the definition in October 2016.
- The weekly *change* that the market traded on differs from the history-file change in 61 of
  283 weeks.

**Why it matters statistically.**
- A surprise is $s_t = y_t - E[y_t\mid\text{past}]$. If $y_t$ is a later restatement, $s_t$ is
  not the information shock the market saw.
- At best that adds noise, which biases slopes toward zero (errors-in-variables). At worst, a
  revision can correlate with later price moves, which is look-ahead.

**Fix (`wpsr_tables.point_in_time_targets`, `surprises.surprise_table(first_release=...)`).**
- Wherever an archived edition exists, use the change *as printed in that edition*: its
  current-week column minus its prior-week column.
- An edition counts as development data only if it was **released** before 2017.

**Takeaway.** 793 archived first releases were diffed against the current history. Five of the
six series matched in almost every week. Crude stock levels did not, because EIA restated them
in 2016. The surprises therefore use first prints wherever they exist.

---

## 4. Expiry calendars: documentation first, prices as a diagnostic

**Why it matters.**
- EIA's "contract 1" silently becomes the next contract after expiry. Get the expiry wrong
  and the price gap between two different contracts is booked as a return.
- That gap is seasonal (the RBOB summer/winter grade change, crude contango), so it can
  masquerade as a seasonal "signal".

**Evidence hierarchy.**
1. CME-published last-trade dates from archived exchange calendars.
2. The rulebook rule on the *scheduled* exchange calendar.
3. A settlement diagnostic that only checks.

**Two lessons from the data.**
- **A business day is not the same as "a day EIA has a price".** EIA omits abbreviated
  sessions such as the day after Thanksgiving. Counting EIA dates moves the CLZ2001 expiry from
  Nov 19 to Nov 16.
- **Test your test.** The first diagnostic compared outright prices across days. Daily oil
  moves ($1–2) swamp the calendar spread ($0.1–0.8), so it flagged authoritative CME dates as
  wrong 70% of the time.
  - Spreads are far less volatile than outright prices, so the fix compares spreads:
    $|S_{12}(d) - S_{23}(e)|$ vs $|S_{12}(d) - S_{12}(e)|$.
  - It was validated on synthetic data with heavy price noise before being trusted.

**Why compounding makes small labelling errors cancel.** If the held contract's price is
wrong on one day *inside* a window, the window return is unaffected:
$\frac{P_e}{P_{e-1}}\cdot\frac{P_{e+1}}{P_e} = \frac{P_{e+1}}{P_{e-1}}$. Only windows that
*start or end* on that day are exposed.

---

## 5. EDA findings (development data, 1996–2016)

| Question | Method | Finding |
|---|---|---|
| Is there seasonality? | One-way ANOVA by week of year | Yes, in every series (p ≈ 0). Demand peaks late June, about 830 kb/d above its January trough. |
| Holiday effects? | OLS with week-of-year fixed effects + holiday dummies, Newey–West | Labor Day week demand is 128 kb/d lower (t = −3.0). Distillate stocks build in most holiday weeks. |
| Normal tails? | Jarque–Bera, excess kurtosis, share beyond 3σ | No. Kurtosis up to 1.3; 3σ weeks happen 2–3× more often than under normality. |
| Stationary? | ADF (unit-root null) + KPSS (stationarity null) | Changes: yes. Crude stock *level*: unit root (ADF p = 0.85). So surprises are built on changes. |
| Persistent? | Ljung–Box Q(4), Q(12) | Strong autocorrelation in changes. That is why the AR(1) expectation model wins. |
| Theory of storage? | Spearman ρ and HAC slope of carry on the inventory z-score | High stocks go with contango: ρ = −0.72 (CL), −0.30 (RB). |
| Do surprises move prices? | Correlations (in-sample) | On release day, crude builds lower CL (ρ = −0.29), and demand surprises lift RB (+0.16). The drift afterwards is weak. |

**ADF vs KPSS.** They test opposite nulls. ADF says "unit root" unless the data reject it;
KPSS says "stationary" unless the data reject it. Agreement between the two is convincing.
Disagreement, as in some level series here, signals near-unit-root behaviour or a trend break.

**Why "theory of storage" matters to a trader.**
- Inventories are the buffer between supply and demand.
- When they are low, a barrel available *now* earns a convenience yield, so the front contract
  trades above the next one (backwardation).
- The decile plot (`reports/figures/eda/08_storage_carry.png`) shows exactly that, which also
  sanity-checks the contract-labelling pipeline.

**A caveat we kept.** The pre-registered H4 inventory state is a z-score against the same
calendar week in the prior 5 years. It explodes when stocks leave their historical range,
reaching z > 25 in 2015–16, because the 5-year standard deviation of a slowly trending level
is tiny. We did *not* redefine it after seeing this. Changing a pre-registered variable after
looking at the data is a forking path. It is reported as a limitation of the H4 test.
