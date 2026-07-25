"""Battery discharge marginal cost: an opportunity-cost model.

    MC_discharge = expected_charge_price + degradation_cost + offset

``expected_charge_price_eur_mwh`` is supplied by the caller — the
calibration engine derives it from a rolling percentile of the zone's
realized intraday price spread (epex_scraper's continuous/IDA data). This
model only covers the discharge (supply-side) bid; the symmetric charge-side
demand bid belongs to the demand curve, not the supply curve.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_DEGRADATION_COST_EUR_MWH = 5.0


@dataclass(frozen=True)
class BatteryCostModel:
    technology: str = "battery"
    expected_charge_price_eur_mwh: float = 0.0
    degradation_cost_eur_mwh: float = DEFAULT_DEGRADATION_COST_EUR_MWH

    def marginal_cost(self, *, offset_eur_mwh: float = 0.0) -> float:
        return self.expected_charge_price_eur_mwh + self.degradation_cost_eur_mwh + offset_eur_mwh
