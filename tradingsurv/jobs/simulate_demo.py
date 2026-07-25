"""Step 9/10 smoke test: simulate a scenario against a real, calibrated
AT auction and generate its explanation.

Wires together everything built so far: real ENTSO-E data + Step 7
calibration (via calibrate.py's fitted parameters) produces the base
AuctionSnapshot for one real hour, then a scenario (remove a generator,
add an outage, cut wind, ...) is applied and explained — the actual
headline feature this whole module exists for: "simulate how outages or
withheld capacity would have changed the auction clearing price."

Calibration here is fit fresh against all available archived days (no
train/validation split — this script is about the simulation/explanation
mechanics, not re-demonstrating Step 7's out-of-sample accuracy, which is
calibrate.py's job).

Requires ENTSOE_API_TOKEN (see .env.example).

Run:
  python -m tradingsurv.jobs.simulate_demo --zone AT --date 2026-07-24 --hour 20 \\
      --remove-technology gas
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from ..domain.calibration.engine import CalibrationObservation, fit_technology_offsets, fit_water_values
from ..explainability.driver_analysis import decompose_drivers
from ..explainability.templates import render_explanation
from ..simulation.actions import ReduceSolar, ReduceWind, RemoveGenerator, ScenarioAction
from ..simulation.engine import simulate
from .calibrate import WATER_VALUE_QUANTILES, archived_dates
from .demo_reconstruction import build_hour_snapshot, clear_day, fetch_day_context


def _fit_calibration(zone: str, data_root: Path):
    observations: list[CalibrationObservation] = []
    actual_prices: list[float] = []
    for delivery_date in archived_dates(data_root, zone):
        context = fetch_day_context(zone, delivery_date, data_root)
        for row in clear_day(context):
            observations.append(CalibrationObservation(
                timestamp=row["period_start"], actual_price=row["actual_price"],
                estimated_price=row["estimated_price"], marginal_technology=row["marginal_technology"],
            ))
            actual_prices.append(row["actual_price"])

    offsets = fit_technology_offsets(observations)
    water_values = fit_water_values(actual_prices, WATER_VALUE_QUANTILES)
    offsets = {t: v for t, v in offsets.items() if t not in water_values}
    return offsets, water_values


def _build_scenario(snapshot, remove_technology: str | None, reduce_wind_mw: float, reduce_solar_mw: float) -> list[ScenarioAction]:
    actions: list[ScenarioAction] = []
    if remove_technology is not None:
        target = next((a for a in snapshot.assets if a.technology == remove_technology), None)
        if target is None:
            raise SystemExit(f"no asset with technology {remove_technology!r} in this hour's snapshot")
        actions.append(RemoveGenerator(asset_id=target.id))
    if reduce_wind_mw:
        actions.append(ReduceWind(delta_mw=reduce_wind_mw))
    if reduce_solar_mw:
        actions.append(ReduceSolar(delta_mw=reduce_solar_mw))
    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", default="AT")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD delivery date")
    parser.add_argument("--hour", type=int, required=True, help="hour of day, 0-23")
    parser.add_argument("--remove-technology", default=None, help="e.g. gas, hydro_reservoir, wind_onshore")
    parser.add_argument("--reduce-wind-mw", type=float, default=0.0)
    parser.add_argument("--reduce-solar-mw", type=float, default=0.0)
    parser.add_argument("--data-dir", default=Path(__file__).resolve().parent.parent.parent / "data")
    args = parser.parse_args()

    data_root = Path(args.data_dir)
    delivery_date = date.fromisoformat(args.date)

    print("fitting calibration against all archived days...")
    offsets, water_values = _fit_calibration(args.zone, data_root)

    context = fetch_day_context(args.zone, delivery_date, data_root)
    period_start = datetime.combine(delivery_date, datetime.min.time()).replace(hour=args.hour)
    if period_start not in context.actual:
        raise SystemExit(f"no actual price for {args.zone} {period_start} — check --hour is in this day's data")

    base = build_hour_snapshot(context, period_start, offsets=offsets, water_values=water_values)
    baseline = base.clear()
    print(
        f"\nbase auction: {args.zone} {period_start} — calibrated estimate "
        f"€{baseline.price_eur_mwh:.2f}/MWh (actual: €{context.actual[period_start]:.2f}/MWh), "
        f"marginal: {baseline.marginal_technology}\n"
    )

    actions = _build_scenario(base, args.remove_technology, args.reduce_wind_mw, args.reduce_solar_mw)
    if not actions:
        raise SystemExit("no scenario actions given — pass --remove-technology / --reduce-wind-mw / --reduce-solar-mw")

    result = simulate(base, actions)
    drivers = decompose_drivers(base, actions)

    print(render_explanation(result, drivers))
    print(
        f"\nvolume: {result.old_volume_mw:.0f} MW -> {result.new_volume_mw:.0f} MW"
    )


if __name__ == "__main__":
    main()
