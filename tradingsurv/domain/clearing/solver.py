"""Intersect the estimated supply and demand curves (Step 6.4).

Both curves are monotonic in price (supply non-decreasing, demand
non-increasing), so the intersection is found by a short fixed-point sweep:
guess a price, read off the demand it implies, find the supply curve's
marginal point at that volume, take its cost as the next price guess, repeat
until stable. For zero elasticity (the common case) this converges in two
iterations; for a mildly elastic curve, in a handful.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..demand.curve import DemandCurve
from ..merit_order.supply_curve import SupplyCurve


@dataclass(frozen=True)
class ClearingResult:
    price_eur_mwh: float
    volume_mw: float
    marginal_asset_id: str
    marginal_technology: str
    shortage_mw: float = 0.0
    """> 0 when demand at the cleared price exceeds total available supply —
    a genuine scarcity condition the curve intersection can't resolve, since
    there's no more capacity to clear against. The reported price is then
    the top of the supply stack, not a true scarcity price."""


def clear(
    supply: SupplyCurve,
    demand: DemandCurve,
    max_iterations: int = 10,
    price_tolerance_eur_mwh: float = 1e-6,
) -> ClearingResult:
    if not supply.points:
        raise ValueError("cannot clear an empty supply curve")

    price = demand.reference_price_eur_mwh
    for _ in range(max_iterations):
        required_mw = demand.demand_at(price)
        marginal_point = supply.marginal_point_at(required_mw)
        next_price = marginal_point.marginal_cost_eur_mwh
        if abs(next_price - price) < price_tolerance_eur_mwh:
            price = next_price
            break
        price = next_price
    else:
        marginal_point = supply.marginal_point_at(demand.demand_at(price))

    required_mw = demand.demand_at(price)
    shortage = max(required_mw - supply.total_capacity_mw, 0.0)
    volume = min(required_mw, supply.total_capacity_mw)

    return ClearingResult(
        price_eur_mwh=marginal_point.marginal_cost_eur_mwh,
        volume_mw=volume,
        marginal_asset_id=marginal_point.asset_id,
        marginal_technology=marginal_point.technology,
        shortage_mw=shortage,
    )
