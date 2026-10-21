# Learning Notes 1: Foundations Built in Phase 2

These notes explain the mathematics and trading logic behind the code that exists so far.
Each section answers the same questions: what problem we are solving, why we use this method,
what it assumes, the formula, the intuition, what can go wrong, and how an interviewer will
push back.

---

## 0. The big picture

```
 EIA weekly report (reference week ends Fri F)                 NYMEX futures (CL, RB)
            │                                                          │
            ▼                                                          ▼
 ┌──────────────────────┐    release time R (Wed 10:30 ET)   ┌──────────────────────┐
 │ fundamentals x_t     │ ─────────────────────────────────► │ settlements P(d)     │
 │ (stocks, demand)     │                                    │ at 14:30 ET per      │
 └─────────┬────────────┘                                    │ contract             │
           │ expectation model uses only x_{t-1}, x_{t-2}... └─────────┬────────────┘
           ▼                                                           │ expiry calendar
 ┌──────────────────────┐                                              ▼ + roll rule
 │ surprise s_t =       │                                    ┌──────────────────────┐
 │ x_t − E[x_t | past]  │                                    │ held contract,       │
 └─────────┬────────────┘                                    │ dollar P&L within    │
           │ standardise with expanding stats                │ a single contract    │
           ▼                                                 └─────────┬────────────┘
 ┌──────────────────────┐   Q1: does price move on s_t?                │
 │ signal at decision   │◄──── P_pre (Tue settle) → P_post (Wed settle) │
 │ time S > R           │      (diagnostic, not tradable)              │
 └─────────┬────────────┘                                              │
           │ Q2: position from Wed settle to Tue settle (before next release)
           ▼                                                           ▼
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ backtest: positions × within-contract price changes × multiplier − costs   │
 └─────────┬────────────────────────────────────────────────────────────────────┘
           ▼
   metrics (52 weeks/yr), robustness, placebos  →  ONE locked test on 2017–2026
```

The single most important idea in the project is that **every arrow must point forward in
time**.

---

## 1. Information sets and look-ahead bias (`timing.py`, `integrity.py`)

**Problem.** A backtest is a claim about decisions someone *could have made*. If a decision at
time $S$ uses any information published after $S$, the backtest is fiction.

**The formal statement (probability theory).** Let $\mathcal{F}_S$ be the information set
(a σ-algebra, or *filtration*) available at time $S$. A trading rule is legitimate if and only
if the position $q_S$ is **$\mathcal{F}_S$-measurable**: it is a function only of what is
known at $S$.

The integration test `test_future_data_cannot_change_past_decisions` checks exactly this. If
$q_S$ depends only on $\mathcal{F}_S$, then changing anything outside $\mathcal{F}_S$ (all data
after the cutoff) cannot change $q_S$. The test changes all future surprises and prices and
asserts that past positions and P&L are identical. It also checks that the change *does*
alter later positions, so the test is not passing trivially.

**The as-of join.** `align_asof` attaches to each decision time $S$ the latest observation
with release time $R < S$. The inequality is **strict** on purpose. A value released at
exactly 14:30 cannot be traded at the 14:30 settlement, because the settlement price is being
formed at that moment.

**Why timestamps must carry a timezone.** EIA publishes in Eastern time. A naive timestamp
read as UTC moves the release by 4–5 hours, which is enough to land before or after the 14:30
settlement. So the code refuses naive timestamps (`_require_tz`).

**What could go wrong.**
- Revised data: today's history file differs from what was published at the time. That is
  checked in Phase 3.
- Holiday release shifts.
- Full-sample statistics hidden inside features, such as z-scoring with the full-sample mean.

**Interviewer challenge.** *"Your release is at 10:30 but you trade at 14:30. Aren't you
leaving money on the table, and does the delay bias anything?"*

Answer: yes, we miss the immediate reaction. That is deliberate. Daily settlement data can
only test what remains *after* the release (Q2). The bias runs *against* finding an effect, so
it is conservative. The intraday extension measures how much is lost.

---

## 2. Event windows: announcement versus drift (`build_event_table`)

For each release $t$ at time $R_t$:

| Window | From | To | What it measures | Tradable? |
|---|---|---|---|---|
| Announcement | last settlement before $R_t$ | first settlement after $R_t$ | how the market prices the news | No, with daily data |
| Drift | first settlement after $R_t$ | last settlement before $R_{t+1}$ | predictable movement after the news is public | Yes |

**Why exit before the next release?** If a holding period crossed release $t+1$, its return
would include the reaction to a *different* surprise. That adds noise and mixes two effects.
Ending at the last settlement before $R_{t+1}$ keeps each trade's return attributable to one
piece of information. `test_positions_never_span_a_release` checks this.

**Why Q1 is not wasted effort.** Our surprise is model-based and therefore noisy (§9). If
prices do not react to it even on release day, a null result in Q2 tells us nothing: the
measuring instrument was broken. Q1 checks the instrument.

---

## 3. Futures P&L and contract rolls (`backtesting/contracts.py`, `backtesting/pnl.py`)

**Problem.** A futures contract expires. "Contract 1" in EIA data is a *label* that jumps from
the May contract to the June contract at expiry. The two contracts trade at different prices.
That gap is the calendar spread, often several dollars.

**Formula.** Position $q_d$ (signed contracts) is held from the close of $d$ to the close of
$d+1$ in contract $c_d$. The dollar P&L on day $d+1$ is

$$\text{PnL}_{d+1} = q_d\,\big(P_{c_d}(d+1) - P_{c_d}(d)\big)\times M$$

where $M$ is the multiplier (1,000 bbl for CL, 42,000 gal for RB). Both prices come from the
**same contract** $c_d$.

**Why naive splicing is wrong.** Splicing contract 1 across an expiry books
$P_{\text{June}}(d+1) - P_{\text{May}}(d)$. That equals the true June price change *plus* the
spread $P_{\text{June}}(d) - P_{\text{May}}(d)$. In contango the spread is positive, so the
naive series manufactures gains on every roll for a long position. Twelve fake gains a year
can look like a strategy. In the unit test, the naive splice books +$7,000 where the true P&L
is +$1,000.

**Why dollars and not percent.** WTI settled at **−$37.63** on 2020-04-20. A percent return
measured on that price is meaningless, and a log return is undefined. A futures position has
no "invested price" in any case: you post margin, and the P&L is a cash flow. Percent returns
appear only after we divide by a *stated capital base* (`pnl_to_returns`).

**Expiry rules.** We reconstruct which contract "contract 1" referred to each day from CME
rules:
- CL: 3 business days before the 25th of the prior month.
- RB: last business day of the prior month.

Business days are taken from the price data itself. The calendar is checked against the data
in Phase 3. We also tried to detect rolls from price jumps alone: that found 28–124 "rolls"
per year instead of about 12, so an explicit calendar is needed.

**Roll timing.** We roll $N$ business days *before* expiry ($N = 5$ by default) because:
1. liquidity moves to the next contract before expiry;
2. holding into expiry exposes you to physical delivery mechanics. April 2020 is the extreme
   example.

**Interviewer challenge.** *"Is rolling a cost or a return?"*

The roll itself is two trades, so it costs two half-spreads plus commissions (we charge them).
The *roll yield* is different: it is the tendency of a futures price to converge toward spot
as expiry approaches. It shows up in the within-contract price changes. It is a genuine
return component, not an artefact.

---

## 4. Transaction costs (`backtesting/costs.py`)

**Formula.** The cost per contract per side is

$$c = k \cdot \text{tick} \cdot M + \text{commission}$$

For CL in the base case: $1 \times 0.01 \times 1000 + 2.50 = \$12.50$. A round trip costs
twice that.

**How big is the edge compared with the cost? (a useful interview calculation)**

Suppose the signal $X$ and the next-period return $Y$ are jointly normal with correlation
$\rho$, and we trade $\text{sign}(X)$. Then

$$\mathbb{E}[\text{sign}(X)\,Y] = \rho\,\sigma_Y\sqrt{2/\pi}$$

*Derivation sketch:* write $Y = \rho\sigma_Y Z_X + \text{independent noise}$, where
$Z_X = X/\sigma_X$. Then $\mathbb{E}[\text{sign}(Z_X) Z_X] = \mathbb{E}|Z_X| = \sqrt{2/\pi}$.

Example numbers:
- WTI near $70 with weekly volatility around 4% gives $\sigma_Y \approx \$2.80$/bbl, or
  \$2,800 per contract per week.
- With $\rho = 0.05$: expected gain ≈ $0.05 \times 2800 \times 0.80 \approx \$112$ per trade.
- The base-case round trip costs \$25, which is **about 22% of the expected edge**.

So at weekly frequency, costs matter, but the strategy lives or dies by $\rho$.

**What could go wrong.**
- Spreads widen exactly when news hits (release days). That is why the intraday extension and
  the stress cost scenario matter.
- Commission assumptions vary by broker.

---

## 5. Sharpe ratio and annualisation (`evaluation/metrics.py`)

**Formula.** For per-period excess returns $r_1, \dots, r_N$ with mean $\hat\mu$ and standard
deviation $\hat\sigma$:

$$\widehat{SR}_{\text{annual}} = \frac{\hat\mu}{\hat\sigma}\sqrt{P}$$

where $P$ is the number of periods per year: **52 for weekly, 252 for daily**.

**Why $\sqrt{P}$.** If period returns are independent and identically distributed, the annual
return is a sum of $P$ of them. Its mean is $P\mu$ and its variance is $P\sigma^2$. So the
ratio is $P\mu / (\sqrt{P}\,\sigma) = \sqrt{P}\,\mu/\sigma$. Using 252 on weekly data inflates
the Sharpe ratio by $\sqrt{252/52} \approx 2.2\times$. The code makes `periods_per_year` a
required argument so this cannot happen by default.

**Assumption to watch.** Independence. With positive autocorrelation (for example from
overlapping multi-week holds), $\sqrt{P}$ *overstates* the annual Sharpe ratio (Lo, 2002). In
that case we use the autocorrelation-adjusted version or non-overlapping returns.

**How uncertain is a Sharpe ratio?** Under IID normal returns, the standard error of the
per-period Sharpe ratio is $\approx \sqrt{(1 + SR^2/2)/N}$. Annualised, this is roughly
$1/\sqrt{\text{years}}$, so

$$t \approx SR_{\text{annual}}\sqrt{\text{years}}$$

A true annual Sharpe of 0.5 needs about **16 years** of data to reach $t = 2$. This is why a
"Sharpe of 1.2 over 3 years" proves very little. Expect to be asked this.

**Sortino ratio.** It replaces $\sigma$ with the downside deviation
$\sqrt{\tfrac{1}{N}\sum \min(r_i, 0)^2}$. Volatility from gains is not penalised. It is useful
when returns are skewed.

**Maximum drawdown.** This is the worst peak-to-trough fall in equity. We use a *fixed*
capital base (no compounding), so equity $= 1 + \sum r$. The base must be stated, because the
same dollar P&L gives different percentage drawdowns on \$1M and \$10M.

---

## 6. Causal standardisation (`features/transforms.py`)

$$z_t = \frac{x_t - \bar{x}_{<t}}{s_{<t}}$$

The mean and standard deviation use only observations **strictly before** $t$.

The common mistake is `(x - x.mean()) / x.std()` over the full sample. That uses future data
twice: the future mean shifts every past $z$, and the future volatility rescales it. In a
sample that ends in a high-volatility regime, early signals would be shrunk using information
nobody had then. The unit test checks that changing $x_T$ leaves $z_{<T}$ unchanged.

---

## 7. Why the test period is locked in code (`integrity.py`)

**Problem: researcher degrees of freedom.** Suppose each analysis choice has a 5% chance of
looking significant by luck. After $m$ independent tries,

$$P(\text{at least one false positive}) = 1 - 0.95^m$$

That is about 40% at $m = 10$ and 64% at $m = 20$.

If you check the test set, tweak, and check again, the test set quietly becomes a training
set. The only defence is to decide everything first and look once.

**Mechanism.** `guard_development()` raises on 2017+ data unless `TEQ_UNLOCK_TEST` names an
existing `spec-freeze-*` git tag. The frozen tag records exactly which specification was
tested.

**Interviewer challenge.** *"How do I know you didn't look anyway?"*

Answer: the git history shows the spec-freeze tag before the test outputs. The experiment log
lists every development trial. Multiple-testing corrections (Deflated Sharpe Ratio, SPA) are
computed from that log.

---

## 8. Preview: surprises and why they are noisy (built in Phase 5)

The true surprise is $s^*_t = x_t - \mathbb{E}[x_t \mid \mathcal{F}^{\text{market}}_{t^-}]$,
measured against what *traders* expected (analyst polls, the API survey, private data). We
only observe a model-based surprise

$$\tilde{s}_t = s^*_t + e_t$$

where $e_t$ is our forecast's error relative to the market's expectation.

**Errors-in-variables (econometrics).** Suppose $y_t = \beta s^*_t + \varepsilon_t$ and we run
OLS of $y$ on $\tilde{s}$, with $e \perp s^*$ and $e \perp \varepsilon$. Then

$$\text{plim}\,\hat\beta = \frac{\text{Cov}(y,\tilde{s})}{\text{Var}(\tilde{s})}
= \beta\,\frac{\sigma^2_{s^*}}{\sigma^2_{s^*} + \sigma^2_e}$$

The estimate is **attenuated toward zero** by the signal-to-noise ratio of our surprise.

Consequences:
1. Q1 slopes will understate the true price impact.
2. Comparing surprise models by how well they explain announcement returns (Q1 $R^2$) is a
   reasonable way to choose the one closest to market expectations. This choice is made on
   the development period only.
3. A null result in Q2 is weaker evidence than it looks if Q1 is also weak.

We will derive this in full, together with the HAC standard errors and the Clark–West test,
when we build the models.
