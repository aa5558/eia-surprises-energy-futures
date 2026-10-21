"""Model-based surprises in EIA weekly data (pre-registered in docs/01 §3.4).

For a weekly series observed at reference Fridays, the surprise of week ``t`` is

    s_t = y_t - E[y_t | y_{t-1}, y_{t-2}, ...]

where ``y_t`` is the weekly *change* for inventories and the *level* for gasoline
product supplied (demand). Every expectation uses only weeks strictly before ``t``,
all of which were published in earlier reports (doc 02, use U1), so no release
timestamp is needed to keep them causal.

Three expectation models, compared by out-of-sample forecast accuracy:

(a) ``five_year``: mean of the same calendar week in each of the prior 5 years
    (lags of 52, 104, ..., 260 weeks), the benchmark EIA itself publishes.
(b) ``seasonal``: OLS on a trailing 5-year window of intercept + linear trend +
    3 Fourier harmonics of the day of year + holiday-week dummies.
(c) ``seasonal_ar``: (b) plus an AR(1) on (b)'s in-window residuals, i.e. last
    week's deviation from the seasonal pattern partly persists.

A trailing (not expanding) window is used for (b) and (c) so the regression tracks the
slow trend in demand and matches the 5-year horizon of (a); this was fixed before any
return data was examined.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

MODELS = ("five_year", "seasonal", "seasonal_ar")
HOLIDAYS = ("New Year's Day", "Memorial Day", "Independence Day", "Labor Day",
            "Thanksgiving Day", "Christmas Day")
WINDOW = 260          # weeks (5 years)
MIN_OBS = 156         # weeks needed before a regression forecast is made
HARMONICS = 3


def regular_weekly(x: pd.Series) -> pd.Series:
    """Reindex to an unbroken Friday grid so positional lags equal calendar weeks."""
    s = x.dropna()
    grid = pd.date_range(s.index[0], s.index[-1], freq="W-FRI")
    extra = s.index.difference(grid)
    if len(extra):
        raise ValueError(f"non-Friday reference dates: {list(extra[:3])}")
    return s.reindex(grid)


def target_series(level: pd.Series, kind: str) -> pd.Series:
    """Weekly change for stocks (``kind='change'``), level for flows (``'level'``)."""
    s = regular_weekly(level)
    if kind == "change":
        return s.diff()
    if kind == "level":
        return s
    raise ValueError(f"unknown kind {kind!r}")


def holiday_dummies(fridays: pd.DatetimeIndex) -> pd.DataFrame:
    """1 if the holiday falls inside the data week (Saturday F-6 .. Friday F)."""
    cal = USFederalHolidayCalendar().holidays(fridays.min() - pd.Timedelta(days=7),
                                              fridays.max(), return_name=True)
    out = pd.DataFrame(0.0, index=fridays, columns=list(HOLIDAYS))
    for day, name in cal.items():
        if name not in HOLIDAYS:
            continue
        # the Friday that ends the week containing `day`
        friday = day + pd.Timedelta(days=(4 - day.weekday()) % 7)
        if friday in out.index:
            out.loc[friday, name] = 1.0
    return out


def design_matrix(fridays: pd.DatetimeIndex) -> pd.DataFrame:
    doy = fridays.dayofyear.to_numpy() / 365.25
    cols = {"const": np.ones(len(fridays)),
            "trend": np.arange(len(fridays), dtype=float) / 52.0}
    for k in range(1, HARMONICS + 1):
        cols[f"sin{k}"] = np.sin(2 * np.pi * k * doy)
        cols[f"cos{k}"] = np.cos(2 * np.pi * k * doy)
    X = pd.DataFrame(cols, index=fridays)
    return X.join(holiday_dummies(fridays))


def forecast_five_year(y: pd.Series, years: int = 5) -> pd.Series:
    lags = pd.concat([y.shift(52 * k) for k in range(1, years + 1)], axis=1)
    return lags.mean(axis=1, skipna=False).rename("five_year")


def _forecast_regression(y: pd.Series, ar: bool) -> pd.Series:
    X = design_matrix(y.index).to_numpy()
    yv = y.to_numpy(dtype=float)
    out = np.full(len(y), np.nan)
    for t in range(len(y)):
        lo = max(0, t - WINDOW)
        Xw, yw = X[lo:t], yv[lo:t]
        ok = ~np.isnan(yw)
        if t == 0 or ok.sum() < MIN_OBS:
            continue
        # drop holiday columns that never occur in the window (singular otherwise)
        keep = np.r_[True, True, np.ones(2 * HARMONICS, bool), Xw[ok][:, 2 + 2 * HARMONICS:]
                     .any(axis=0)]
        Xk = Xw[ok][:, keep]
        beta, *_ = np.linalg.lstsq(Xk, yw[ok], rcond=None)
        f = X[t, keep] @ beta
        if ar:
            fitted = Xw[:, keep] @ beta
            r = yw - fitted
            r_prev, r_now = r[:-1], r[1:]
            both = ~np.isnan(r_prev) & ~np.isnan(r_now)
            if both.sum() >= 20:
                phi = float(r_prev[both] @ r_now[both] / (r_prev[both] @ r_prev[both]))
                f += phi * r[-1] if not np.isnan(r[-1]) else 0.0
        out[t] = f
    return pd.Series(out, index=y.index, name="seasonal_ar" if ar else "seasonal")


def expectations(y: pd.Series) -> pd.DataFrame:
    """Forecasts of ``y_t`` from all three models, each using only weeks before ``t``."""
    return pd.concat([forecast_five_year(y), _forecast_regression(y, ar=False),
                      _forecast_regression(y, ar=True)], axis=1)


def standardize(surprise: pd.Series, min_periods: int = 52) -> pd.Series:
    """s_t / std(s_{<t}): divide by the expanding std of *past* surprises only."""
    sd = surprise.shift(1).expanding(min_periods=min_periods).std(ddof=1)
    return surprise / sd


def surprise_table(level: pd.Series, kind: str, first_release: pd.Series | None = None
                   ) -> pd.DataFrame:
    """Actual, forecasts, raw and standardized surprises for every model.

    ``first_release`` (optional) holds the values as first published (archived WPSR
    editions); where present they replace the current history, so both the actual and
    the model inputs are the numbers the market saw rather than later restatements.
    """
    y = target_series(level, kind)
    if first_release is not None:
        fr = first_release.reindex(y.index)
        y = fr.where(fr.notna(), y)
    f = expectations(y)
    out = pd.DataFrame({"actual": y})
    for m in MODELS:
        out[f"f_{m}"] = f[m]
        out[f"s_{m}"] = y - f[m]
        out[f"z_{m}"] = standardize(out[f"s_{m}"])
    return out
