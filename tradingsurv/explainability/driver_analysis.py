"""Per-action counterfactual price-impact decomposition (Step 10).

Each action's contribution is estimated by applying it *alone* to the base
snapshot — cheap (each is its own full clear(), still well under a
millisecond) and directly explainable, at the cost of isolated impacts not
always summing exactly to the full scenario's price delta when actions
interact (e.g. two removals that each individually would have set the
price). ``interaction_residual`` makes that gap explicit rather than
letting the numbers silently not add up.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..simulation.actions import (
    AddOutage,
    IncreaseDemand,
    LimitInterconnector,
    ReduceCapacity,
    ReduceSolar,
    ReduceWind,
    RemoveGenerator,
    ScenarioAction,
    apply_action,
)
from ..simulation.snapshot import AuctionSnapshot


@dataclass(frozen=True)
class DriverImpact:
    action: ScenarioAction
    description: str
    price_impact_eur_mwh: float


def describe_action(action: ScenarioAction, base: AuctionSnapshot) -> str:
    if isinstance(action, RemoveGenerator):
        asset = base.asset(action.asset_id)
        label = f"{asset.name} ({asset.capacity_mw:.0f} MW {asset.technology})" if asset else action.asset_id
        return f"{label} removed"
    if isinstance(action, ReduceCapacity):
        asset = base.asset(action.asset_id)
        label = asset.name if asset else action.asset_id
        return f"{action.reduce_by_mw:.0f} MW capacity reduction at {label}"
    if isinstance(action, AddOutage):
        asset = base.asset(action.asset_id)
        label = asset.name if asset else action.asset_id
        return f"{action.unavailable_mw:.0f} MW outage at {label}"
    if isinstance(action, IncreaseDemand):
        return f"Demand increased by {action.delta_mw:.0f} MW"
    if isinstance(action, ReduceWind):
        return f"Wind availability reduced by {action.delta_mw:.0f} MW"
    if isinstance(action, ReduceSolar):
        return f"Solar availability reduced by {action.delta_mw:.0f} MW"
    if isinstance(action, LimitInterconnector):
        return f"Interconnector import capped at {action.new_limit_mw:.0f} MW"
    return str(action)


def decompose_drivers(base: AuctionSnapshot, actions: list[ScenarioAction]) -> list[DriverImpact]:
    """Each action's isolated price impact vs ``base``, ranked by magnitude."""
    base_price = base.clear().price_eur_mwh
    impacts = []
    for action in actions:
        isolated_price = apply_action(base, action).clear().price_eur_mwh
        impacts.append(DriverImpact(
            action=action,
            description=describe_action(action, base),
            price_impact_eur_mwh=isolated_price - base_price,
        ))
    impacts.sort(key=lambda d: abs(d.price_impact_eur_mwh), reverse=True)
    return impacts


def interaction_residual(full_price_diff_eur_mwh: float, drivers: list[DriverImpact]) -> float:
    return full_price_diff_eur_mwh - sum(d.price_impact_eur_mwh for d in drivers)
