"""Assemble available generation assets into a merit-order supply curve."""

from __future__ import annotations

from ..assets.models import GenerationAsset
from .supply_curve import SupplyCurve, SupplyCurvePoint


def build_supply_curve(
    assets: list[GenerationAsset],
    marginal_costs: dict[str, float],
    available_mw: dict[str, float] | None = None,
) -> SupplyCurve:
    """Sort available capacity by estimated marginal cost into a step supply curve.

    ``available_mw`` is keyed by asset id; an asset missing from it is
    treated as fully available at nameplate capacity, and an asset with
    ``available_mw <= 0`` (full outage) is excluded entirely. Every asset
    passed in must have an entry in ``marginal_costs`` — computing that
    dict (technology cost model -> float) is the caller's job, since it
    depends on live fuel/CO2 prices the builder itself has no opinion on.
    """
    available_mw = available_mw or {}
    entries: list[tuple[GenerationAsset, float, float]] = []

    for asset in assets:
        capacity = min(available_mw.get(asset.id, asset.capacity_mw), asset.capacity_mw)
        if capacity <= 0:
            continue
        if asset.id not in marginal_costs:
            raise KeyError(f"missing marginal cost for asset {asset.id!r}")
        entries.append((asset, capacity, marginal_costs[asset.id]))

    # Stable tie-break on asset id keeps the curve deterministic across runs.
    entries.sort(key=lambda entry: (entry[2], entry[0].id))

    points: list[SupplyCurvePoint] = []
    cumulative = 0.0
    for asset, capacity, cost in entries:
        cumulative += capacity
        points.append(
            SupplyCurvePoint(
                asset_id=asset.id,
                technology=asset.technology,
                owner=asset.owner,
                country=asset.zone,
                marginal_cost_eur_mwh=cost,
                capacity_mw=capacity,
                cumulative_mw=cumulative,
            )
        )

    return SupplyCurve(points=tuple(points))
