"""Step 7: walk-forward calibration against epex_scraper's actual-price archive.

Fits technology offsets (domain/calibration/engine.py) and hydro water
values on a chronological *train* window of archived days, then applies
them to a held-out *validation* window and reports MAE before vs after —
out-of-sample, not fit-then-graded-on-the-same-data, to avoid the
look-ahead bias a single-window fit would have.

Each archived day is fetched from ENTSO-E once and cleared twice
(uncalibrated baseline, then with fitted parameters) via
demo_reconstruction.py's fetch/compute split, rather than hitting ENTSO-E
redundantly per pass.

Small-sample caveat: this repo currently has a handful of archived AT days
(epex_scraper's rolling 3-day window turned into an archive by the cron
job — see README.md). A walk-forward split over ~5-10 days is a real
demonstration of the method, not a statistically robust calibration; MAE
should keep improving as the archive grows and this is re-run.

Requires ENTSOE_API_TOKEN (see .env.example).

Run: python -m tradingsurv.jobs.calibrate --zone AT --validation-days 2
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from ..domain.calibration.engine import (
    CalibrationObservation,
    fit_technology_offsets,
    fit_water_values,
)
from ..domain.calibration.metrics import bias, mae, rmse
from ..domain.costs.hydro import PUMPED_STORAGE, RESERVOIR
from ..ingestion.market_prices.epex_reader import read_actual_day_ahead_prices
from .demo_reconstruction import clear_day, fetch_day_context

# Reservoir is more baseload-like (runs whenever it's above-median
# profitable), pumped storage is more peaking/arbitrage-oriented (only
# discharges in the higher-price hours) — see domain/calibration/engine.py.
WATER_VALUE_QUANTILES = {RESERVOIR: 0.5, PUMPED_STORAGE: 0.75}

MIN_OFFSET_SAMPLES = 3


def _archived_dates(data_root: Path, zone: str) -> list[date]:
    """Dates with a *usable* archived file — some AT/CH/SE2/SE4/GB days
    record the wrong price schema (README.md's known scraper caveat); those
    files exist but read_actual_day_ahead_prices correctly returns {} for
    them, so they're excluded here rather than crashing fetch_day_context
    later."""
    day_ahead_dir = data_root / "day-ahead" / zone
    candidate_dates = []
    for path in day_ahead_dir.glob("*_60min.csv"):
        try:
            candidate_dates.append(date.fromisoformat(path.name.removesuffix("_60min.csv")))
        except ValueError:
            continue

    return sorted(
        d for d in candidate_dates
        if read_actual_day_ahead_prices(data_root, zone, d, resolution=60)
    )


def run_calibration(zone: str, data_root: Path, validation_days: int) -> None:
    dates = _archived_dates(data_root, zone)
    if len(dates) <= validation_days:
        raise SystemExit(
            f"only {len(dates)} archived day(s) for {zone} under {data_root} — "
            f"need more than --validation-days ({validation_days}) to hold any out for training"
        )

    train_dates, validation_dates = dates[:-validation_days], dates[-validation_days:]
    print(f"train days ({len(train_dates)}): {[d.isoformat() for d in train_dates]}")
    print(f"validation days ({len(validation_dates)}): {[d.isoformat() for d in validation_dates]}\n")

    observations: list[CalibrationObservation] = []
    train_actual_prices: list[float] = []
    for delivery_date in train_dates:
        context = fetch_day_context(zone, delivery_date, data_root)
        for row in clear_day(context):
            observations.append(CalibrationObservation(
                timestamp=row["period_start"], actual_price=row["actual_price"],
                estimated_price=row["estimated_price"], marginal_technology=row["marginal_technology"],
            ))
            train_actual_prices.append(row["actual_price"])

    offsets = fit_technology_offsets(observations, min_samples=MIN_OFFSET_SAMPLES)
    water_values = fit_water_values(train_actual_prices, WATER_VALUE_QUANTILES)
    # The cost dispatcher applies water_value + offset additively for hydro
    # storage (domain/costs/estimate.py) — an offset fit on top of a water
    # value would double-correct the same technology, so each technology
    # gets exactly one calibration mechanism: water value wins for the
    # technologies it covers.
    offsets = {technology: value for technology, value in offsets.items() if technology not in water_values}

    print("fitted technology offsets (EUR/MWh):")
    for technology, offset in sorted(offsets.items()):
        print(f"  {technology:>15}: {offset:+.2f}")
    print("\nfitted hydro water values (EUR/MWh):")
    for technology, value in sorted(water_values.items()):
        print(f"  {technology:>15}: {value:.2f}")

    baseline_errors: list[float] = []
    calibrated_errors: list[float] = []
    for delivery_date in validation_dates:
        context = fetch_day_context(zone, delivery_date, data_root)
        baseline_errors += [r["price_error"] for r in clear_day(context)]
        calibrated_errors += [
            r["price_error"] for r in clear_day(context, offsets=offsets, water_values=water_values)
        ]

    print(f"\nvalidation ({len(validation_dates)} day(s), {len(baseline_errors)} hours), out-of-sample:")
    print(f"  {'':>10} {'MAE':>8} {'RMSE':>8} {'bias':>8}")
    print(f"  {'baseline':>10} {mae(baseline_errors):>8.2f} {rmse(baseline_errors):>8.2f} {bias(baseline_errors):>8.2f}")
    print(f"  {'calibrated':>10} {mae(calibrated_errors):>8.2f} {rmse(calibrated_errors):>8.2f} {bias(calibrated_errors):>8.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", default="AT")
    parser.add_argument("--validation-days", type=int, default=2)
    parser.add_argument("--data-dir", default=Path(__file__).resolve().parent.parent.parent / "data")
    args = parser.parse_args()

    run_calibration(args.zone, Path(args.data_dir), args.validation_days)


if __name__ == "__main__":
    main()
