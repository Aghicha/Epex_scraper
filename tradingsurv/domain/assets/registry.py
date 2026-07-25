"""Build a technology-pooled asset registry from ENTSO-E's aggregated installed capacity.

ENTSO-E's per-unit capacity disclosure (``EntsoeClient.installed_capacity_per_unit``)
only names larger/individually-tracked plants — for AT it covers roughly 40%
of actual installed hydro run-of-river capacity and omits wind/solar/biomass
entirely, since those are disclosed only in aggregate. Rather than silently
under-count supply, Phase 0 builds one pooled ``GenerationAsset`` per
(zone, technology) from the aggregated total instead. Real per-unit,
per-owner granularity (needed for the compliance withholding indicators) is
a documented Phase 5/6 upgrade, not a Phase 0 claim — see
docs/tradingsurv/ARCHITECTURE.md.
"""

from __future__ import annotations

import re

import pandas as pd

from ..costs.hydro import PUMPED_STORAGE, RESERVOIR, RUN_OF_RIVER
from .models import GenerationAsset

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_NON_ALNUM.sub("-", text.lower()).strip("-")

# ENTSO-E "Production Type" -> tradingsurv technology id. Fossil Gas/Coal-derived
# gas collapse to one "gas" bucket, and Hard coal/Lignite/Oil shale to their
# nearest tradingsurv technology, because the aggregated endpoint doesn't
# split further (e.g. no CCGT/OCGT breakdown) — see costs/estimate.py for how
# that coarser bucket gets a single blended efficiency assumption.
TECHNOLOGY_MAP: dict[str, str] = {
    "Hydro Run-of-river and poundage": RUN_OF_RIVER,
    "Hydro Water Reservoir": RESERVOIR,
    "Hydro Pumped Storage": PUMPED_STORAGE,
    "Fossil Gas": "gas",
    "Fossil Coal-derived gas": "gas",
    "Fossil Hard coal": "coal",
    "Fossil Brown coal/Lignite": "lignite",
    "Fossil Oil": "oil",
    "Fossil Oil shale": "oil",
    "Fossil Peat": "other",
    "Nuclear": "nuclear",
    "Wind Onshore": "wind_onshore",
    "Wind Offshore": "wind_offshore",
    "Solar": "solar",
    "Biomass": "biomass",
    "Waste": "other",
    "Geothermal": "other",
    "Marine": "other",
    "Other renewable": "other",
    "Other": "other",
    "Energy storage": "battery",
}


def build_pooled_fleet(zone: str, aggregated_capacity: pd.Series) -> list[GenerationAsset]:
    """One ``GenerationAsset`` per non-zero ENTSO-E production type.

    ``aggregated_capacity`` is what ``EntsoeClient.installed_capacity_aggregated``
    returns: an index of ENTSO-E production-type labels to installed MW.

    ``id`` is keyed off the raw production type, not the collapsed
    ``technology`` bucket — several production types map to the same
    tradingsurv technology (e.g. "Other" and "Waste" both -> "other"; "Fossil
    Gas" and "Fossil Coal-derived gas" both -> "gas"), and a technology-keyed
    id would collide between them, silently merging two distinct assets
    under simulation actions like ``RemoveGenerator``/``without_asset``
    (which matches by id).
    """
    assets = []
    for production_type, capacity_mw in aggregated_capacity.items():
        capacity_mw = float(capacity_mw)
        if capacity_mw <= 0:
            continue
        technology = TECHNOLOGY_MAP.get(production_type, "other")
        assets.append(
            GenerationAsset(
                id=f"{zone}:{_slugify(production_type)}",
                zone=zone,
                name=f"{zone} {production_type} fleet",
                technology=technology,
                capacity_mw=capacity_mw,
                source="entsoe_aggregated",
            )
        )
    return assets
