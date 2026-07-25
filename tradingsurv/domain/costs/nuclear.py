"""Nuclear marginal cost: a low fixed constant, not fuel-driven.

Real nuclear bidding reflects must-run/opportunity-cost behavior rather than
the (tiny) fuel cost, so this is deliberately a flat calibrated value instead
of a fuel-price formula — the calibration engine (Step 7) fits
``base_cost_eur_mwh`` per zone from observed prices at hours nuclear is
estimated-marginal.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_BASE_COST_EUR_MWH = 10.0


@dataclass(frozen=True)
class NuclearCostModel:
    technology: str = "nuclear"
    base_cost_eur_mwh: float = DEFAULT_BASE_COST_EUR_MWH

    def marginal_cost(self, *, offset_eur_mwh: float = 0.0) -> float:
        return self.base_cost_eur_mwh + offset_eur_mwh
