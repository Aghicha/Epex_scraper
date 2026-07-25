"""Scenario actions (Step 9) and how each mutates an AuctionSnapshot.

Every action is a frozen dataclass so a scenario (an ordered list of
actions) is itself hashable/comparable — useful for the cache key a
production API would use (``hash(base_auction_id, actions)``, per
docs/tradingsurv/ARCHITECTURE.md's Step 8). ``apply_action`` never mutates
its input snapshot; it returns a new one, so scenarios compose and a partial
prefix of actions is always a valid snapshot in its own right (what
explainability's per-action isolation, below, relies on).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from ..domain.demand.curve import DemandCurve
from ..domain.interconnectors.model import IMPORT_TECHNOLOGY
from .snapshot import AuctionSnapshot

WIND_TECHNOLOGIES = frozenset({"wind_onshore", "wind_offshore"})


@dataclass(frozen=True)
class RemoveGenerator:
    asset_id: str


@dataclass(frozen=True)
class ReduceCapacity:
    asset_id: str
    reduce_by_mw: float


@dataclass(frozen=True)
class AddOutage:
    """Same mechanical effect as ReduceCapacity, kept as a distinct action
    type because it means something different to a compliance user (an
    outage/UMM event, not a generic capacity trim) and Step 10's
    explanation text should say so."""

    asset_id: str
    unavailable_mw: float


@dataclass(frozen=True)
class IncreaseDemand:
    delta_mw: float


@dataclass(frozen=True)
class ReduceWind:
    delta_mw: float


@dataclass(frozen=True)
class ReduceSolar:
    delta_mw: float


@dataclass(frozen=True)
class LimitInterconnector:
    new_limit_mw: float


ScenarioAction = Union[
    RemoveGenerator, ReduceCapacity, AddOutage, IncreaseDemand, ReduceWind, ReduceSolar, LimitInterconnector,
]


def _current_available_mw(snapshot: AuctionSnapshot, asset_id: str) -> float:
    if asset_id in snapshot.available_mw:
        return snapshot.available_mw[asset_id]
    asset = snapshot.asset(asset_id)
    return asset.capacity_mw if asset is not None else 0.0


def _reduce_technology(snapshot: AuctionSnapshot, technologies: frozenset[str], delta_mw: float) -> AuctionSnapshot:
    remaining = delta_mw
    for asset in snapshot.assets:
        if remaining <= 0:
            break
        if asset.technology not in technologies:
            continue
        current = _current_available_mw(snapshot, asset.id)
        cut = min(current, remaining)
        snapshot = snapshot.with_available_mw(asset.id, current - cut)
        remaining -= cut
    return snapshot


def apply_action(snapshot: AuctionSnapshot, action: ScenarioAction) -> AuctionSnapshot:
    if isinstance(action, RemoveGenerator):
        return snapshot.without_asset(action.asset_id)

    if isinstance(action, ReduceCapacity):
        current = _current_available_mw(snapshot, action.asset_id)
        return snapshot.with_available_mw(action.asset_id, current - action.reduce_by_mw)

    if isinstance(action, AddOutage):
        current = _current_available_mw(snapshot, action.asset_id)
        return snapshot.with_available_mw(action.asset_id, current - action.unavailable_mw)

    if isinstance(action, IncreaseDemand):
        d = snapshot.demand
        return snapshot.with_demand(DemandCurve(
            base_mw=d.base_mw + action.delta_mw, reference_price_eur_mwh=d.reference_price_eur_mwh,
            elasticity_mw_per_eur=d.elasticity_mw_per_eur,
        ))

    if isinstance(action, ReduceWind):
        return _reduce_technology(snapshot, WIND_TECHNOLOGIES, action.delta_mw)

    if isinstance(action, ReduceSolar):
        return _reduce_technology(snapshot, frozenset({"solar"}), action.delta_mw)

    if isinstance(action, LimitInterconnector):
        import_assets = [a for a in snapshot.assets if a.technology == IMPORT_TECHNOLOGY]
        for asset in import_assets:
            current = _current_available_mw(snapshot, asset.id)
            snapshot = snapshot.with_available_mw(asset.id, min(current, action.new_limit_mw))
        return snapshot

    raise TypeError(f"unknown scenario action type: {type(action)!r}")


def apply_actions(snapshot: AuctionSnapshot, actions: list[ScenarioAction]) -> AuctionSnapshot:
    for action in actions:
        snapshot = apply_action(snapshot, action)
    return snapshot
