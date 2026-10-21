# Learning Notes 3: Surprise Models, Inference, Forecasting and Backtesting (Phases 5–6)

---

## 1. Building a "surprise" without analyst consensus

**Intuition.** Futures already price predictable information. Only the unexpected part of a
report can move prices, so we need an *expectation* for each number.

**Three models (`features/surprises.py`)**, all using only weeks before $t$. Here $y_t$ is
the weekly change in stocks, or the level of demand.

1. **5-year same-week mean:** $\hat y_t = \frac15\sum_{k=1}^5 y_{t-52k}$. This is EIA's own
   benchmark.
2. **Seasonal regression on a trailing 260-week window:**
   $$y_s = a + b\,s + \sum_{k=1}^{3}\big[c_k\sin(2\pi k\,\tfrac{doy_s}{365.25}) + d_k\cos(\cdot)\big] + \sum_h \gamma_h H_{h,s} + e_s.$$
   - Fourier terms model a smooth annual cycle with 6 parameters instead of 52 weekly dummies.
   - The trend absorbs slow demand growth.
   - The holiday dummies $H$ flag weeks containing Memorial Day, July 4, and so on.
3. **(2) + AR(1) on its residuals:** $\hat y_t = \hat y^{(2)}_t + \hat\phi\,\hat e_{t-1}$. If
   last week was unusually high relative to the season, part of that persists.

**Selection was out of sample, on fundamentals only.**

| Series | RMSE, 5-yr mean | RMSE, seasonal + AR(1) |
|---|---|---|
| Demand | 410 kb/d | 231 kb/d |
| Crude | 3,751 kb | 3,589 kb |

- Diebold–Mariano tests on squared errors confirm the differences. Model 3 won all four series.
- Why the 5-year mean is bad for demand: it ignores the trend, giving a bias of +146 kb/d.

**Why accuracy matters.** Under classical measurement error, the regression slope on a noisy
surprise is attenuated:
$$\hat\beta \to \beta\,\frac{\sigma^2_s}{\sigma^2_s+\sigma^2_u}.$$
A better expectation model means smaller $\sigma_u^2$ and more power.

**Standardisation.** $z_t = s_t/\mathrm{sd}(s_{<t})$ uses an expanding standard deviation of
*past* surprises only. Using the full-sample sd would leak the future scale.

---

## 2. Regressions with dependent, heteroskedastic errors

**The model:** $r_t = \alpha + \beta'z_t + \delta'x_t + \varepsilon_t$.

**Newey–West standard errors.**
- Ordinary OLS standard errors assume iid errors. Weekly futures returns have volatility
  clustering (heteroskedasticity), and overlapping or adjacent windows can autocorrelate.
- The HAC estimator of $\mathrm{Var}(\hat\beta)$ is
  $$(X'X)^{-1}\Big[\sum_t \hat u_t^2x_tx_t' + \sum_{\ell=1}^{L}w_\ell\sum_t(\hat u_t\hat u_{t-\ell})(x_tx_{t-\ell}'+x_{t-\ell}x_t')\Big](X'X)^{-1},$$
  with Bartlett weights $w_\ell = 1-\ell/(L+1)$.
- $L = \lfloor 4(n/100)^{2/9}\rfloor$, and at least $h-1$ for $h$-week overlapping returns.
- Code: `evaluation/inference.py::ols_hac`.

**Multiple testing.** There are 16 primary tests (2 markets × 2 windows × 4 surprises).
- At α = 5%, about 0.8 false positives are expected by chance.
- **Holm** controls the probability of *any* false rejection. Sort the p-values and compare
  $p_{(i)}$ with $\alpha/(m-i+1)$.
- **Benjamini–Hochberg** controls the expected *share* of false discoveries.
- We report both, and treat Holm as the confirmatory threshold.

**Development findings (in-sample).**
- **Release-day reaction:** a crude build lowers CL with t = −4.7, Holm p < 0.001. Gasoline
  and demand surprises move RB, with Holm p ≈ 0.03 and 0.04.
- **Drift after the release:** the coefficients point toward continuation, but no drift
  coefficient survives Holm.

---

## 3. Out-of-sample forecasting

**Walk-forward.**
- Each January, refit on all events whose *exit* settlement is earlier, then predict that
  year's events.
- Requiring the exit (not the entry) before the cut-off matters: an event that started in
  December but ends in January has a return that wasn't known on 1 January.

**Models.**

| Model | Definition |
|---|---|
| M0 | historical mean |
| M1 | price-only (momentum, volatility, carry) |
| M2 | M1 + surprises, OLS |
| M3 | ridge |
| M4 | logistic |
| M5 | gradient boosting, only if pre-registered evidence triggers it |

**Metrics.**
- **Campbell–Thompson out-of-sample $R^2$:**
  $1-\sum(y-\hat y)^2/\sum(y-\bar y_{\text{past}})^2$. Even 0.5% can matter economically at
  weekly frequency.
- **Clark–West.** For *nested* models (M1 ⊂ M3), the bigger model's estimation noise makes
  its MSE look worse even when it is right. CW adds back $(\hat y_{small}-\hat y_{big})^2$:
  $$f_t = (y_t-\hat y_{1,t})^2 - \big[(y_t-\hat y_{2,t})^2-(\hat y_{1,t}-\hat y_{2,t})^2\big],$$
  then tests $E[f_t] > 0$ with a HAC t-statistic.
- **Diebold–Mariano**, for non-nested comparisons: a HAC t-test on the difference in squared
  errors.

**Ridge** minimises $\sum(y-X\beta)^2+\lambda\|\beta\|^2$ on standardised regressors, which
shrinks noisy coefficients toward zero. Validation chose λ = 1000, the heaviest penalty on the
grid. Validation MSE fell monotonically toward "predict the mean". That is the data saying
the predictors add very little.

**Development OOS $R^2$ for M3:** +0.5% (CL) and −0.6% (RB). Gradient boosting was triggered
by a nominal Clark–West p < 0.05, exactly as pre-registered, and then did worse: −2% and
−31%. Flexible models overfit noise.

---

## 4. From forecast to position (`backtesting/event_backtest.py`)

**Signal (amendment A1).**
$$\hat z_t = \frac{\hat r_t - \overline{\hat r}_{train}}{\mathrm{sd}(\hat r_{train})}.$$
The first version used $\hat r_t/\mathrm{sd}$. With heavy shrinkage $\hat r_t\approx$ the
historical mean drift, so |z| was huge every week and the "strategy" was a constant short. We
caught this by inspecting *what the strategy traded*, not just its Sharpe ratio. Subtracting
the mean isolates what the conditioning information adds.

**Sizing to a volatility target.**
- One "unit" is $n = \sigma^*/(\hat\sigma_d\sqrt{h}\,P\,M)$ contracts, where:
  - $\sigma^* = 10\%/\sqrt{52}\times\$1\text{M}$ is the weekly dollar-risk target;
  - $\hat\sigma_d$ is the trailing 60-day volatility of daily returns, known at entry;
  - $h$ is the holding period in days, $P$ the price and $M$ the contract multiplier.
- **Rule A:** take one unit in the direction of $\hat z$ if $|\hat z| > k$.
- **Rule B:** take $\mathrm{clip}(\hat z,-2,2)$ units.
- Rule B is the Kelly-flavoured $\propto \hat r/\hat\sigma^2$ sizing:
  $\hat z\propto \hat r/\hat\sigma$, and $n\propto 1/\hat\sigma$.

**P&L is in dollars, within the contract held.** $q_{d-1}\,(P_{h_{d-1}}(d)-P_{h_{d-1}}(d-1))\,M$.
Costs are charged per contract per side, including both legs of every roll.

**Cross-check we ran.** Always-long trade P&L against $q\cdot P_{entry}\cdot M\cdot r^{drift}$
gave correlation 0.99999 across 900 trades. Before trusting a negative result, make sure it
isn't a bug.

**Annualisation.** Weekly returns use $\sqrt{52}$, never $\sqrt{252}$. Returns are measured on
a fixed $1M base and are not compounded, so a futures P&L is never divided by a futures price
that can go negative.

---

## 5. Development strategy results (not evidence)

| 2006–2016, net of base costs | Sharpe |
|---|---|
| Rule A (k = 1.5), the primary strategy | +0.35 |
| Rule B | +0.15 |
| Always long | −0.44 |
| Price-only benchmark | **+0.77** |

The surprise model **does not beat the price-only benchmark even in development**. Whatever
predictability exists in weekly drift comes mostly from momentum and carry. k was chosen on
these same years, so these Sharpe ratios are optimistic by construction.

---

## 6. Why the locked test is the only evidence

- **Researcher degrees of freedom.** Every choice made after looking at data (k, λ, the
  amendment) is a fork in the path. With 20 strategy trials, the *expected maximum* Sharpe
  under pure noise is well above zero.
- **The Deflated Sharpe Ratio** (Bailey & López de Prado) asks whether the observed Sharpe beats
  that expected maximum, given the number of trials, their variance, and the skew and kurtosis
  of the returns.
- **Hansen's SPA test** asks whether *any* of the K tradable variants beats zero, with a
  bootstrap that accounts for searching over K.
- **The spec freeze plus the code lock** make "I only ran it once" verifiable:
  - `integrity.py` refuses 2017+ data without the tag;
  - `locked_test.py` refuses to run if `src/` or `configs/` differ from the tag.
