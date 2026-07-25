"""Interconnector modeling (Step 5) via net position, not per-border ATC.

The architecture doc's original sketch was a per-border NTC/ATC-capped
import/export block. Reality (checked directly against ENTSO-E for AT, its
real neighbors DE-LU/CH/CZ/HU/IT_NORD/SI): most of those borders stopped
publishing bilateral day-ahead NTC once the CORE region went flow-based in
June 2022 — only CH and IT_NORD still do. A per-border ATC model would
silently have no data for most of a zone's actual interconnection.

ENTSO-E's zone-wide ``net_position`` (Step 0's ``entsoe.net_position``),
by contrast, is one number that's always published and already nets out
every border — importing (>0) or exporting (<0) — regardless of whether the
underlying allocation is NTC-based or flow-based. That's the primary signal
used here.

The price attached to a net import is the actual settled price of the
zone's dominant coupling partner (for AT: DE-LU, by flow volume) — real
public settled-price data, the same category of input as the calibration
ground truth, not a violation of the "no participant bids" assumption. This
borrows the neighboring zone's price rather than independently estimating
it — a documented Phase 0/1 simplification. A genuine per-border,
ATC-capped multi-zone reconstruction (each neighbor running its own
estimation pipeline) is a real but substantially larger Phase 5+ upgrade,
not a Phase 0 claim.
"""

from __future__ import annotations

from ..assets.models import GenerationAsset

IMPORT_TECHNOLOGY = "import"


def import_supply_asset(
    zone: str, net_position_mw: float, limit_mw: float | None = None
) -> GenerationAsset | None:
    """A virtual generation asset representing net imports, sized off
    ENTSO-E's net_position (>0 = net importer). ``None`` when the zone is a
    net exporter at this timestamp — nothing to add to supply.

    ``limit_mw`` is the Step 9 "limit interconnector" scenario hook: caps
    the modeled import capacity below the observed net position.
    """
    if net_position_mw <= 0:
        return None
    capacity_mw = net_position_mw if limit_mw is None else min(net_position_mw, limit_mw)
    return GenerationAsset(
        id=f"{zone}:import",
        zone=zone,
        name=f"{zone} net imports",
        technology=IMPORT_TECHNOLOGY,
        capacity_mw=capacity_mw,
        source="entsoe_net_position",
    )


def export_demand_mw(net_position_mw: float, limit_mw: float | None = None) -> float:
    """Extra domestic demand from net exports — add directly to
    ``DemandCurve.base_mw``. 0.0 when the zone is a net importer at this
    timestamp (nothing exported to account for).

    Exports draw on domestic supply just like local load does, so they're
    modeled as additional inelastic demand rather than a separate curve —
    matches how day-ahead coupling actually clears (the neighboring zone is
    just another buyer of this zone's cheap capacity).
    """
    if net_position_mw >= 0:
        return 0.0
    magnitude = abs(net_position_mw)
    return magnitude if limit_mw is None else min(magnitude, limit_mw)
