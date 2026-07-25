"""AuctionSnapshot (Step 8/9): the materialized state one scenario mutates.

Deliberately holds the *inputs* to a clearing (assets, costs, availability,
demand), not a pre-built SupplyCurve — scenario actions (remove a
generator, cut availability, shift demand) mutate exactly these inputs, and
rebuilding the curve from them is cheap (see domain/merit_order/builder.py),
so there's no benefit to caching the built curve itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..domain.assets.models import GenerationAsset
from ..domain.clearing.solver import ClearingResult, clear
from ..domain.demand.curve import DemandCurve
from ..domain.merit_order.builder import build_supply_curve


@dataclass(frozen=True)
class AuctionSnapshot:
    zone: str
    assets: tuple[GenerationAsset, ...]
    costs: dict[str, float]
    demand: DemandCurve
    available_mw: dict[str, float] = field(default_factory=dict)

    def clear(self) -> ClearingResult:
        supply = build_supply_curve(list(self.assets), self.costs, available_mw=self.available_mw)
        return clear(supply, self.demand)

    def asset(self, asset_id: str) -> GenerationAsset | None:
        return next((a for a in self.assets if a.id == asset_id), None)

    def with_available_mw(self, asset_id: str, available_mw: float) -> AuctionSnapshot:
        return replace(self, available_mw={**self.available_mw, asset_id: max(available_mw, 0.0)})

    def without_asset(self, asset_id: str) -> AuctionSnapshot:
        return replace(self, assets=tuple(a for a in self.assets if a.id != asset_id))

    def with_demand(self, demand: DemandCurve) -> AuctionSnapshot:
        return replace(self, demand=demand)
