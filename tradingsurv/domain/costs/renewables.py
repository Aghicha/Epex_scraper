"""Wind/solar marginal cost: ~zero, with a configurable floor.

The floor is negative under negative-price/must-run-subsidy regimes (some
zones/technologies keep bidding at the negative price floor rather than
curtail, to keep collecting a per-MWh subsidy) and zero otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ZeroMarginalCostModel:
    technology: str
    price_floor_eur_mwh: float = 0.0

    def marginal_cost(self, *, offset_eur_mwh: float = 0.0) -> float:
        return self.price_floor_eur_mwh + offset_eur_mwh
