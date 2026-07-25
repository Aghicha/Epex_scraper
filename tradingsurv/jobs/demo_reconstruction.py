"""Phase 0/1: reconstruct a zone's day-ahead auction from real ENTSO-E data
and compare to the actual settled price.

Real public data feeds this, no synthetic placeholders left for the fleet,
demand, gas/CO2 price, or interconnection:
  - ENTSO-E aggregated installed capacity -> pooled fleet per technology
  - ENTSO-E day-ahead load forecast       -> hourly demand
  - ENTSO-E wind/solar generation forecast -> hourly wind/solar availability
  - ENTSO-E actual generation             -> hourly hydro run-of-river availability
  - ENTSO-E net position                  -> hourly net import/export (Step 5)
  - Yahoo Finance TTF gas / EUA carbon proxies -> gas_eur_mwh_th / co2_eur_t
    (see ingestion/fuel_co2/prices.py for why these specific tickers)
  - epex_scraper's own archive            -> actual price for both `zone` and
    REFERENCE_ZONE (the neighbor whose price stands in for imports, see
    domain/interconnectors/model.py), and for comparison

Hydro run-of-river gets *actual* (ex-post) generation as its availability
cap, not a forecast — ENTSO-E doesn't publish a per-technology day-ahead
hydro forecast the way it does for wind/solar. Justified because RoR output
is overwhelmingly flow-constrained (whatever the river allows, run
near-continuously) rather than a price-responsive economic dispatch
decision, so actual generation is a reasonable physical-availability proxy
even though it's ex-post — a documented MVP simplification, not something
Step 9's forward-looking simulator could use as-is. Reservoir/pumped storage
deliberately do *not* get this treatment: their real constraint is
economic (a water value/opportunity cost), not physical availability, so
capping them by past output would hide exactly what Step 7 calibration
(tradingsurv/jobs/calibrate.py) is supposed to fit.

What's still a placeholder: coal/lignite/oil prices (flat constants below —
no free reliable source found, see ingestion/fuel_co2/prices.py). Hydro
reservoir/pumped-storage water values and per-technology offsets default to
0/uncalibrated here — pass ``offsets``/``water_values`` (as fitted by
calibrate.py) to ``clear_day`` to apply them.

Requires ENTSOE_API_TOKEN (see .env.example).

Run: python -m tradingsurv.jobs.demo_reconstruction --zone AT --date 2026-07-24
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from ..domain.assets.models import GenerationAsset
from ..domain.assets.registry import build_pooled_fleet
from ..domain.clearing.solver import clear
from ..domain.costs.estimate import FuelPrices, estimate_marginal_costs
from ..domain.costs.hydro import RUN_OF_RIVER
from ..domain.demand.curve import DemandCurve
from ..domain.interconnectors.model import export_demand_mw, import_supply_asset
from ..domain.merit_order.builder import build_supply_curve
from ..ingestion.entsoe.client import EntsoeClient
from ..ingestion.fuel_co2 import prices as fuel_co2_prices
from ..ingestion.market_prices.epex_reader import read_actual_day_ahead_prices

# Coal/lignite/oil have no free reliable price source yet (see
# ingestion/fuel_co2/prices.py) — kept flat until one is identified.
PLACEHOLDER_COAL_EUR_MWH_TH = 15.0
PLACEHOLDER_LIGNITE_EUR_MWH_TH = 8.0
PLACEHOLDER_OIL_EUR_MWH_TH = 45.0

# AT's dominant coupling partner by flow volume (see
# domain/interconnectors/model.py for why one reference zone, not per-border
# ATC). Only meaningful when reconstructing a zone other than this one.
REFERENCE_ZONE = "DE-LU"

# tradingsurv technology id -> the column name ENTSO-E's wind/solar forecast uses.
WEATHER_DRIVEN_COLUMNS = {"wind_onshore": "Wind Onshore", "wind_offshore": "Wind Offshore", "solar": "Solar"}

# The (production type, metric) column ENTSO-E's actual-generation endpoint
# uses for hydro run-of-river — see module docstring for why actual (not
# forecast) is used here specifically.
RUN_OF_RIVER_ACTUAL_COLUMN = ("Hydro Run-of-river and poundage", "Actual Aggregated")


def _current_fuel_prices() -> FuelPrices:
    return FuelPrices(
        gas_eur_mwh_th=fuel_co2_prices.gas_price_eur_mwh_th(),
        coal_eur_mwh_th=PLACEHOLDER_COAL_EUR_MWH_TH,
        lignite_eur_mwh_th=PLACEHOLDER_LIGNITE_EUR_MWH_TH,
        oil_eur_mwh_th=PLACEHOLDER_OIL_EUR_MWH_TH,
        co2_eur_t=fuel_co2_prices.co2_price_eur_t(),
    )


def _nearest(series: pd.Series, timestamp: pd.Timestamp) -> float:
    """Nearest-in-time lookup — forecast series resolution (15/30/60 min)
    doesn't always line up exactly with the hour boundary being priced."""
    idx = series.index.get_indexer([timestamp], method="nearest")[0]
    return float(series.iloc[idx])


@dataclass(frozen=True)
class DayContext:
    """Everything fetched over the network for one (zone, day) — separated
    from ``clear_day``'s pure computation so a caller that needs multiple
    passes (e.g. calibrate.py's uncalibrated-then-calibrated comparison)
    fetches once and clears twice, instead of hitting ENTSO-E redundantly.
    """

    zone: str
    actual: dict
    assets: list[GenerationAsset]
    fuel_prices: FuelPrices
    load_series: pd.Series
    wind_solar: pd.DataFrame
    ror_actual: pd.Series | None
    net_position: pd.Series
    reference_prices: dict


def fetch_day_context(zone: str, delivery_date: date, data_root: Path) -> DayContext:
    actual = read_actual_day_ahead_prices(data_root, zone, delivery_date, resolution=60)
    if not actual:
        raise SystemExit(
            f"no actual prices found for {zone} {delivery_date} under {data_root} — "
            "has epex_scraper archived that day?"
        )

    client = EntsoeClient()
    day_start = pd.Timestamp(delivery_date, tz="Europe/Vienna")
    day_end = day_start + pd.Timedelta(days=1)

    capacity = client.installed_capacity_aggregated(zone, day_start, day_end)
    assets = build_pooled_fleet(zone, capacity)
    fuel_prices = _current_fuel_prices()

    load_series = client.load_forecast(zone, day_start, day_end).iloc[:, 0]  # "Forecasted Load"
    wind_solar = client.wind_and_solar_forecast(zone, day_start, day_end)

    generation_actual = client.generation_actual(zone, day_start, day_end)
    ror_actual = (
        generation_actual[RUN_OF_RIVER_ACTUAL_COLUMN]
        if RUN_OF_RIVER_ACTUAL_COLUMN in generation_actual.columns
        else None
    )

    net_position = client.net_position(zone, day_start, day_end)
    reference_prices = (
        read_actual_day_ahead_prices(data_root, REFERENCE_ZONE, delivery_date, resolution=60)
        if zone != REFERENCE_ZONE
        else {}
    )

    return DayContext(
        zone=zone, actual=actual, assets=assets, fuel_prices=fuel_prices,
        load_series=load_series, wind_solar=wind_solar, ror_actual=ror_actual,
        net_position=net_position, reference_prices=reference_prices,
    )


def clear_day(
    context: DayContext,
    offsets: dict[str, float] | None = None,
    water_values: dict[str, float] | None = None,
) -> list[dict]:
    """Pure: clear every hour of an already-fetched day. No network calls."""
    costs = estimate_marginal_costs(context.assets, context.fuel_prices, water_value_eur_mwh=water_values, offsets=offsets)

    rows = []
    for period_start in sorted(context.actual):
        ts = pd.Timestamp(period_start, tz="Europe/Vienna")

        available_mw = {}
        for asset in context.assets:
            column = WEATHER_DRIVEN_COLUMNS.get(asset.technology)
            if column is not None and column in context.wind_solar.columns:
                available_mw[asset.id] = _nearest(context.wind_solar[column], ts)
            elif asset.technology == RUN_OF_RIVER and context.ror_actual is not None:
                available_mw[asset.id] = _nearest(context.ror_actual, ts)

        hour_assets = list(context.assets)
        hour_costs = dict(costs)
        net_position_mw = _nearest(context.net_position, ts)
        reference_price = context.reference_prices.get(period_start)

        if reference_price is not None:
            import_asset = import_supply_asset(context.zone, net_position_mw)
            if import_asset is not None:
                hour_assets.append(import_asset)
                hour_costs[import_asset.id] = reference_price
        # Missing reference price for this hour -> interconnector effect is
        # skipped for it rather than guessed; net_position_mw is still
        # reported below so the gap is visible, not silently absorbed.

        demand_mw = _nearest(context.load_series, ts) + export_demand_mw(net_position_mw)
        supply = build_supply_curve(hour_assets, hour_costs, available_mw=available_mw)
        demand = DemandCurve(base_mw=demand_mw, reference_price_eur_mwh=context.actual[period_start])
        result = clear(supply, demand)

        rows.append({
            "hour": period_start.hour,
            "period_start": period_start,
            "estimated_price": result.price_eur_mwh,
            "actual_price": context.actual[period_start],
            "price_error": result.price_eur_mwh - context.actual[period_start],
            "marginal_technology": result.marginal_technology,
            "demand_mw": demand.base_mw,
            "net_position_mw": net_position_mw,
        })
    return rows


def reconstruct_day(zone: str, delivery_date: date, data_root: Path) -> list[dict]:
    context = fetch_day_context(zone, delivery_date, data_root)
    print(f"gas: {context.fuel_prices.gas_eur_mwh_th:.2f} EUR/MWh_th, CO2: {context.fuel_prices.co2_eur_t:.2f} EUR/t (live)\n")
    return clear_day(context)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", default="AT")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD delivery date")
    parser.add_argument("--data-dir", default=Path(__file__).resolve().parent.parent.parent / "data")
    args = parser.parse_args()

    rows = reconstruct_day(args.zone, date.fromisoformat(args.date), Path(args.data_dir))

    errors = [r["price_error"] for r in rows]
    mae = sum(abs(e) for e in errors) / len(errors)

    print(f"{'hour':>4}  {'estimated':>10}  {'actual':>8}  {'error':>8}  {'demand_mw':>10}  {'net_pos':>8}  marginal")
    for r in rows:
        print(
            f"{r['hour']:>4}  {r['estimated_price']:>10.2f}  {r['actual_price']:>8.2f}  "
            f"{r['price_error']:>8.2f}  {r['demand_mw']:>10.0f}  {r['net_position_mw']:>8.0f}  {r['marginal_technology']}"
        )
    print(f"\nMAE: {mae:.2f} EUR/MWh over {len(rows)} hours (uncalibrated baseline, real ENTSO-E fleet/demand)")


if __name__ == "__main__":
    main()
