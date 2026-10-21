"""Load the YAML research configuration so parameters live in one place, not in code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_config(name: str, root: Path = REPO_ROOT) -> dict[str, Any]:
    """Return ``configs/<name>.yaml`` as a dict (e.g. ``load_config("research")``)."""
    with open(root / "configs" / f"{name}.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
