"""Marginal-cost model shared by all fuel-burning technologies.

    MC[EUR/MWh_el] = FuelPrice[EUR/MWh_th] / efficiency
                   + (EmissionFactor[tCO2/MWh_th] / efficiency) * CO2Price[EUR/tCO2]
                   + VariableOM[EUR/MWh_el]
                   + offset[EUR/MWh_el]

Emission factors are IPCC default values per unit of thermal fuel input
(tCO2 per MWh_th), not per MWh_el — dividing by efficiency converts to an
electrical-output basis, matching the fuel term.
"""

from __future__ import annotations

from dataclasses import dataclass

# tCO2 / MWh_th, IPCC default emission factors for the relevant fuels.
EMISSION_FACTOR_T_PER_MWH_TH: dict[str, float] = {
    "natural_gas": 0.202,
    "hard_coal": 0.341,
    "lignite": 0.364,
    "oil": 0.279,
}


@dataclass(frozen=True)
class ThermalCostModel:
    technology: str
    fuel: str
    fuel_price_eur_mwh_th: float
    efficiency: float
    co2_price_eur_t: float
    variable_om_eur_mwh: float = 2.0

    def __post_init__(self) -> None:
        if not (0 < self.efficiency <= 1):
            raise ValueError(f"efficiency must be in (0, 1], got {self.efficiency}")
        if self.fuel not in EMISSION_FACTOR_T_PER_MWH_TH:
            raise ValueError(f"unknown fuel {self.fuel!r}, expected one of {sorted(EMISSION_FACTOR_T_PER_MWH_TH)}")

    def marginal_cost(self, *, offset_eur_mwh: float = 0.0) -> float:
        emission_factor = EMISSION_FACTOR_T_PER_MWH_TH[self.fuel]
        fuel_component = self.fuel_price_eur_mwh_th / self.efficiency
        co2_component = (emission_factor / self.efficiency) * self.co2_price_eur_t
        return fuel_component + co2_component + self.variable_om_eur_mwh + offset_eur_mwh
