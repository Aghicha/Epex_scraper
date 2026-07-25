"""Dispatch each asset's technology to its cost model (Step 2/6.1) and return
a marginal-cost dict ready for ``merit_order.builder.build_supply_curve``.

Default efficiency assumptions are placeholders pending calibration (Step
7). Technologies ENTSO-E only discloses in aggregate (``gas``, ``coal``,
``lignite``, ``oil`` — see ``assets/registry.py``) get one blended
efficiency instead of a CCGT/OCGT-level split the public data doesn't
support.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..assets.models import GenerationAsset
from .battery import BatteryCostModel
from .hydro import PUMPED_STORAGE, RESERVOIR, RUN_OF_RIVER, HydroCostModel
from .nuclear import NuclearCostModel
from .renewables import ZeroMarginalCostModel
from .thermal import ThermalCostModel

DEFAULT_EFFICIENCY: dict[str, float] = {
    "gas": 0.50,
    "coal": 0.38,
    "lignite": 0.36,
    "oil": 0.35,
}

FUEL_BY_TECHNOLOGY: dict[str, str] = {
    "gas": "natural_gas",
    "coal": "hard_coal",
    "lignite": "lignite",
    "oil": "oil",
}

# Flat placeholder for technologies with no dedicated cost model yet
# (biomass, waste, geothermal, ...) — refined by calibration (Step 7).
OTHER_FLAT_COST_EUR_MWH = 80.0


@dataclass(frozen=True)
class FuelPrices:
    gas_eur_mwh_th: float
    coal_eur_mwh_th: float
    lignite_eur_mwh_th: float
    oil_eur_mwh_th: float
    co2_eur_t: float

    def price_for(self, fuel: str) -> float:
        return {
            "natural_gas": self.gas_eur_mwh_th,
            "hard_coal": self.coal_eur_mwh_th,
            "lignite": self.lignite_eur_mwh_th,
            "oil": self.oil_eur_mwh_th,
        }[fuel]


def estimate_marginal_costs(
    assets: list[GenerationAsset],
    fuel_prices: FuelPrices,
    water_value_eur_mwh: dict[str, float] | None = None,
    offsets: dict[str, float] | None = None,
) -> dict[str, float]:
    """Return {asset_id: marginal_cost_eur_mwh} for every asset passed in.

    ``water_value_eur_mwh`` and ``offsets`` are keyed by *technology*
    (``hydro_reservoir``, ``gas``, ...), not asset id — appropriate for a
    pooled fleet registry where one asset already represents a whole
    technology bucket.
    """
    water_value_eur_mwh = water_value_eur_mwh or {}
    offsets = offsets or {}
    costs: dict[str, float] = {}

    for asset in assets:
        offset = offsets.get(asset.technology, 0.0)

        if asset.technology in (RUN_OF_RIVER, RESERVOIR, PUMPED_STORAGE):
            water_value = water_value_eur_mwh.get(asset.technology, 0.0)
            costs[asset.id] = HydroCostModel(asset.technology, water_value).marginal_cost(offset_eur_mwh=offset)
        elif asset.technology == "nuclear":
            costs[asset.id] = NuclearCostModel().marginal_cost(offset_eur_mwh=offset)
        elif asset.technology in ("wind_onshore", "wind_offshore", "solar"):
            costs[asset.id] = ZeroMarginalCostModel(asset.technology).marginal_cost(offset_eur_mwh=offset)
        elif asset.technology == "battery":
            costs[asset.id] = BatteryCostModel().marginal_cost(offset_eur_mwh=offset)
        elif asset.technology in FUEL_BY_TECHNOLOGY:
            fuel = FUEL_BY_TECHNOLOGY[asset.technology]
            efficiency = asset.efficiency or DEFAULT_EFFICIENCY[asset.technology]
            costs[asset.id] = ThermalCostModel(
                asset.technology, fuel, fuel_prices.price_for(fuel), efficiency, fuel_prices.co2_eur_t,
            ).marginal_cost(offset_eur_mwh=offset)
        else:
            costs[asset.id] = OTHER_FLAT_COST_EUR_MWH + offset

    return costs
