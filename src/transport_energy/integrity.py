"""Lock on the out-of-sample test period.

Any analysis that touches data on or after ``splits.test_start`` must call
:func:`guard_development` first. It raises unless the environment variable
``TEQ_UNLOCK_TEST`` names a ``spec-freeze-*`` git tag that actually exists, i.e.
unless the full specification has been frozen and committed. This turns "don't
peek at the test set" from a promise into a mechanism.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Mapping

import pandas as pd

from transport_energy.config import REPO_ROOT, load_config

UNLOCK_ENV_VAR = "TEQ_UNLOCK_TEST"
FREEZE_TAG_PREFIX = "spec-freeze"


class LockedTestPeriodError(RuntimeError):
    """Raised when code touches the locked test period before the spec is frozen."""


def default_test_start() -> pd.Timestamp:
    return pd.Timestamp(load_config("research")["splits"]["test_start"])


def _git_tags() -> set[str]:
    try:
        out = subprocess.run(
            ["git", "tag", "--list"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return set(out.split())


def is_test_unlocked(
    env: Mapping[str, str] | None = None, tags: Iterable[str] | None = None
) -> bool:
    """True only if ``TEQ_UNLOCK_TEST`` names an existing ``spec-freeze*`` git tag."""
    tag = (os.environ if env is None else env).get(UNLOCK_ENV_VAR, "")
    if not tag.startswith(FREEZE_TAG_PREFIX):
        return False
    return tag in set(_git_tags() if tags is None else tags)


def _as_index(obj: pd.Series | pd.DataFrame | pd.Index) -> pd.DatetimeIndex:
    index = obj if isinstance(obj, pd.Index) else obj.index
    return pd.DatetimeIndex(index)


def _comparable(ts: pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp:
    if index.tz is not None and ts.tzinfo is None:
        return ts.tz_localize(index.tz)
    return ts


def guard_development(
    obj: pd.Series | pd.DataFrame | pd.Index,
    test_start: pd.Timestamp | str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    tags: Iterable[str] | None = None,
) -> pd.Series | pd.DataFrame | pd.Index:
    """Return ``obj`` unchanged if it contains no test-period dates; otherwise raise.

    The check passes for test-period data only when the test has been unlocked
    via :func:`is_test_unlocked`.
    """
    index = _as_index(obj)
    if len(index) == 0:
        return obj
    start = _comparable(pd.Timestamp(test_start or default_test_start()), index)
    if index.max() >= start and not is_test_unlocked(env, tags):
        raise LockedTestPeriodError(
            f"Data extends to {index.max().date()}, past the locked test start {start.date()}. "
            f"Freeze the spec (git tag '{FREEZE_TAG_PREFIX}-...') and set {UNLOCK_ENV_VAR}."
        )
    return obj


def development_slice(
    obj: pd.Series | pd.DataFrame, test_start: pd.Timestamp | str | None = None
) -> pd.Series | pd.DataFrame:
    """Rows strictly before the test start. Safe to use without unlocking."""
    index = _as_index(obj)
    start = _comparable(pd.Timestamp(test_start or default_test_start()), index)
    return obj.loc[index < start]
