"""Shared fixtures. All data here is synthetic and exists only to test code paths."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pandas as pd
import pytest

ET = "America/New_York"


def weekday_calendar(start: str, end: str, holidays: Iterable[str] = ()) -> pd.DatetimeIndex:
    days = pd.bdate_range(start, end)
    return days.difference(pd.DatetimeIndex(list(holidays)))


@pytest.fixture
def make_calendar() -> Callable[..., pd.DatetimeIndex]:
    return weekday_calendar


@pytest.fixture
def et() -> str:
    return ET
