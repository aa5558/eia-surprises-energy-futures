"""Transaction costs per contract per side: half-spread/slippage in ticks plus commission."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CostModel:
    ticks: float            # spread + slippage paid per side, in ticks
    tick_size: float        # price units per tick (USD/bbl or USD/gal)
    multiplier: float       # contract size (bbl or gal)
    commission_usd: float   # commission + exchange/clearing fees per side

    @property
    def per_contract_side(self) -> float:
        """USD cost of trading one contract once (one side)."""
        return self.ticks * self.tick_size * self.multiplier + self.commission_usd

    def cost(self, contracts_traded: float) -> float:
        return abs(contracts_traded) * self.per_contract_side

    @classmethod
    def from_config(cls, research_cfg: dict[str, Any], root: str, scenario: str) -> CostModel:
        spec = research_cfg["contracts"][root]
        sc = research_cfg["costs"]["scenarios"][scenario]
        return cls(sc["ticks"], spec["tick_size"], spec["multiplier"], sc["commission_usd"])
