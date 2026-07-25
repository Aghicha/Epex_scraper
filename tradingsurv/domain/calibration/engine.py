"""Calibration engine (Step 7): fit technology offsets and hydro water
values against epex_scraper's actual-price archive.

Two mechanisms, both deliberately simple and both feeding parameters the
cost models already accept (``domain/costs/estimate.py``'s ``offsets`` and
``water_value_eur_mwh``) rather than introducing a separate calibrated-model
type:

- **Technology offsets**: an uncalibrated reconstruction's marginal cost
  model is additive (``marginal_cost = ... + offset``), so when technology
  T was the estimated-marginal one at some hour, the ideal offset for that
  hour is exactly ``actual_price - estimated_price``. Taking the *median*
  of that quantity across every hour T was marginal (rather than a full
  regression) is already outlier-robust and needs no extra dependency.
  Single-pass: fits against one uncalibrated baseline reconstruction, not
  iterated to convergence — a documented simplification (Phase 0/1), not
  full walk-forward re-optimization.

- **Hydro water values**: reservoir/pumped storage default to a EUR 0
  water value (Step 6.1), which is what actually broke AT's reconstruction
  (see tradingsurv/jobs/demo_reconstruction.py's docstring). Fitting them
  from "hours they were marginal" is circular — they're *never* marginal
  while priced at 0. Instead this uses the standard opportunity-cost
  approximation: a storage technology's water value ≈ a quantile of
  *actual* settled prices over the calibration window (a more
  peaking/arbitrage-oriented technology gets a higher quantile — see
  ``fit_water_values``'s ``quantiles`` argument).

What this does *not* implement yet: scarcity premium (isotonic regression
against reserve margin) and seasonal/calendar adjustment — real Step 7
pieces, deferred rather than half-built alongside these two.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CalibrationObservation:
    timestamp: datetime
    actual_price: float
    estimated_price: float
    marginal_technology: str


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute a quantile of an empty sequence")
    if not 0 <= q <= 1:
        raise ValueError(f"q must be in [0, 1], got {q}")
    index = q * (len(sorted_values) - 1)
    lower, upper = int(index), min(int(index) + 1, len(sorted_values) - 1)
    fraction = index - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def fit_technology_offsets(
    observations: list[CalibrationObservation], min_samples: int = 3
) -> dict[str, float]:
    """{technology: offset_eur_mwh}, technologies with fewer than
    ``min_samples`` marginal-hour observations are skipped — not enough
    signal to trust a median from a handful of points."""
    errors_by_technology: dict[str, list[float]] = defaultdict(list)
    for obs in observations:
        errors_by_technology[obs.marginal_technology].append(obs.actual_price - obs.estimated_price)

    return {
        technology: _median(errors)
        for technology, errors in errors_by_technology.items()
        if len(errors) >= min_samples
    }


def _median(values: list[float]) -> float:
    sorted_values = sorted(values)
    return _quantile(sorted_values, 0.5)


def fit_water_values(
    actual_prices: list[float], quantiles: dict[str, float]
) -> dict[str, float]:
    """{technology: water_value_eur_mwh} — a quantile of actual settled
    prices over the calibration window, one quantile per technology (e.g.
    a lower quantile for baseload-like reservoir, higher for
    peaking/arbitrage-oriented pumped storage)."""
    sorted_prices = sorted(actual_prices)
    return {technology: _quantile(sorted_prices, q) for technology, q in quantiles.items()}
