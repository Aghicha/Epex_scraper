"""Common contract all technology-specific cost models satisfy.

Every model's ``marginal_cost`` returns EUR/MWh_el for one asset at one
snapshot and accepts a calibration ``offset_eur_mwh`` (Step 7) that the
calibration engine fits and the merit-order builder applies uniformly — cost
models never fit their own offsets.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CostModel(Protocol):
    technology: str

    def marginal_cost(self, *, offset_eur_mwh: float = 0.0) -> float: ...
