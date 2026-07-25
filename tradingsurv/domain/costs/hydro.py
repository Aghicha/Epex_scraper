"""Hydro marginal cost: an opportunity-cost model, not a fuel-cost model.

Run-of-river is must-run and priced at ~0. Reservoir/pumped storage is priced
at a *water value* — this class only applies whatever water value it is
given; estimating that value (e.g. as a calibrated quantile of recent
day-ahead prices, conditioned on season/reservoir level) is the calibration
engine's job (Step 7), kept out of this model so the two concerns stay
separately testable.
"""

from __future__ import annotations

from dataclasses import dataclass

RUN_OF_RIVER = "hydro_ror"
RESERVOIR = "hydro_reservoir"
PUMPED_STORAGE = "hydro_pumped"


@dataclass(frozen=True)
class HydroCostModel:
    technology: str
    water_value_eur_mwh: float = 0.0

    def marginal_cost(self, *, offset_eur_mwh: float = 0.0) -> float:
        base = 0.0 if self.technology == RUN_OF_RIVER else self.water_value_eur_mwh
        return base + offset_eur_mwh
