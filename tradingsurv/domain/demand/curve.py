"""Hourly demand curve (Step 4 / 6.2).

Primary signal is the zone's own ENTSO-E day-ahead load forecast
(``base_mw``); ``elasticity_mw_per_eur`` gives it a slight downward slope
instead of being perfectly vertical, calibrated per zone from the historical
(actual price, actual demand) relationship. Zero elasticity is a valid,
purely-inelastic default and is what most zones start with pre-calibration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DemandCurve:
    base_mw: float
    reference_price_eur_mwh: float
    elasticity_mw_per_eur: float = 0.0

    def __post_init__(self) -> None:
        if self.base_mw < 0:
            raise ValueError(f"base_mw must be >= 0, got {self.base_mw}")
        if self.elasticity_mw_per_eur < 0:
            raise ValueError(
                f"elasticity_mw_per_eur must be >= 0 (demand falls as price rises), "
                f"got {self.elasticity_mw_per_eur}"
            )

    def demand_at(self, price_eur_mwh: float) -> float:
        demand = self.base_mw - self.elasticity_mw_per_eur * (price_eur_mwh - self.reference_price_eur_mwh)
        return max(demand, 0.0)
