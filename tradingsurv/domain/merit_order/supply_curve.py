"""The reconstructed merit-order supply curve (Step 3 / db.supply_curve_point)."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass


@dataclass(frozen=True)
class SupplyCurvePoint:
    asset_id: str
    technology: str
    owner: str | None
    country: str
    marginal_cost_eur_mwh: float
    capacity_mw: float
    cumulative_mw: float


@dataclass(frozen=True)
class SupplyCurve:
    """Points ordered ascending by ``cumulative_mw`` (and thus by cost)."""

    points: tuple[SupplyCurvePoint, ...]

    @property
    def total_capacity_mw(self) -> float:
        return self.points[-1].cumulative_mw if self.points else 0.0

    def marginal_point_at(self, cumulative_mw: float) -> SupplyCurvePoint:
        """The point whose unit would be needed to serve up to ``cumulative_mw``.

        Returns the cheapest point once ``cumulative_mw`` is at or below the
        curve's start, and the most expensive (last) point once demand
        exceeds total capacity — callers that care about a genuine shortage
        should compare against ``total_capacity_mw`` themselves.
        """
        if not self.points:
            raise ValueError("cannot query an empty supply curve")
        cumulative_values = [p.cumulative_mw for p in self.points]
        index = bisect_left(cumulative_values, cumulative_mw)
        index = min(index, len(self.points) - 1)
        return self.points[index]
