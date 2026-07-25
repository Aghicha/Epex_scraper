"""Phase 0/1: reconstruct a zone's day-ahead auction from real ENTSO-E data
and compare to the actual settled price.

Real public data feeds this, no synthetic placeholders left for the fleet,
demand, or gas/CO2 price:
  - ENTSO-E aggregated installed capacity -> pooled fleet per technology
  - ENTSO-E day-ahead load forecast       -> hourly demand
  - ENTSO-E wind/solar generation forecast -> hourly wind/solar availability
  - Yahoo Finance TTF gas / EUA carbon proxies -> gas_eur_mwh_th / co2_eur_t
    (see ingestion/fuel_co2/prices.py for why these specific tickers)
  - epex_scraper's own archive            -> actual price, for comparison

What's still a placeholder: coal/lignite/oil prices (flat constants below —
no free reliable source found, see ingestion/fuel_co2/prices.py) and
hydro/battery water values (default to 0, i.e. uncalibrated — Step 7 fits
these from history). AT's own fleet has no coal/lignite/nuclear, so the coal
placeholder specifically doesn't affect this zone's reconstruction.

Requires ENTSOE_API_TOKEN (see .env.example).

Run: python -m tradingsurv.jobs.demo_reconstruction --zone AT --date 2026-07-24
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from ..domain.assets.registry import build_pooled_fleet
from ..domain.clearing.solver import clear
from ..domain.costs.estimate import FuelPrices, estimate_marginal_costs
from ..domain.demand.curve import DemandCurve
from ..domain.merit_order.builder import build_supply_curve
from ..ingestion.entsoe.client import EntsoeClient
from ..ingestion.fuel_co2 import prices as fuel_co2_prices
from ..ingestion.market_prices.epex_reader import read_actual_day_ahead_prices

# Coal/lignite/oil have no free reliable price source yet (see
# ingestion/fuel_co2/prices.py) — kept flat until one is identified.
PLACEHOLDER_COAL_EUR_MWH_TH = 15.0
PLACEHOLDER_LIGNITE_EUR_MWH_TH = 8.0
PLACEHOLDER_OIL_EUR_MWH_TH = 45.0


def _current_fuel_prices() -> FuelPrices:
    return FuelPrices(
        gas_eur_mwh_th=fuel_co2_prices.gas_price_eur_mwh_th(),
        coal_eur_mwh_th=PLACEHOLDER_COAL_EUR_MWH_TH,
        lignite_eur_mwh_th=PLACEHOLDER_LIGNITE_EUR_MWH_TH,
        oil_eur_mwh_th=PLACEHOLDER_OIL_EUR_MWH_TH,
        co2_eur_t=fuel_co2_prices.co2_price_eur_t(),
    )

# tradingsurv technology id -> the column name ENTSO-E's wind/solar forecast uses.
WEATHER_DRIVEN_COLUMNS = {"wind_onshore": "Wind Onshore", "wind_offshore": "Wind Offshore", "solar": "Solar"}


def _nearest(series: pd.Series, timestamp: pd.Timestamp) -> float:
    """Nearest-in-time lookup — forecast series resolution (15/30/60 min)
    doesn't always line up exactly with the hour boundary being priced."""
    idx = series.index.get_indexer([timestamp], method="nearest")[0]
    return float(series.iloc[idx])


def reconstruct_day(zone: str, delivery_date: date, data_root: Path) -> list[dict]:
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
    print(f"gas: {fuel_prices.gas_eur_mwh_th:.2f} EUR/MWh_th, CO2: {fuel_prices.co2_eur_t:.2f} EUR/t (live)\n")
    costs = estimate_marginal_costs(assets, fuel_prices)

    load_forecast = client.load_forecast(zone, day_start, day_end)
    load_series = load_forecast.iloc[:, 0]  # "Forecasted Load"

    wind_solar = client.wind_and_solar_forecast(zone, day_start, day_end)

    rows = []
    for period_start in sorted(actual):
        ts = pd.Timestamp(period_start, tz="Europe/Vienna")

        available_mw = {}
        for asset in assets:
            column = WEATHER_DRIVEN_COLUMNS.get(asset.technology)
            if column is not None and column in wind_solar.columns:
                available_mw[asset.id] = _nearest(wind_solar[column], ts)

        supply = build_supply_curve(assets, costs, available_mw=available_mw)
        demand = DemandCurve(base_mw=_nearest(load_series, ts), reference_price_eur_mwh=actual[period_start])
        result = clear(supply, demand)

        rows.append({
            "hour": period_start.hour,
            "estimated_price": result.price_eur_mwh,
            "actual_price": actual[period_start],
            "price_error": result.price_eur_mwh - actual[period_start],
            "marginal_technology": result.marginal_technology,
            "demand_mw": demand.base_mw,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", default="AT")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD delivery date")
    parser.add_argument("--data-dir", default=Path(__file__).resolve().parent.parent.parent / "data")
    args = parser.parse_args()

    rows = reconstruct_day(args.zone, date.fromisoformat(args.date), Path(args.data_dir))

    errors = [r["price_error"] for r in rows]
    mae = sum(abs(e) for e in errors) / len(errors)

    print(f"{'hour':>4}  {'estimated':>10}  {'actual':>8}  {'error':>8}  {'demand_mw':>10}  marginal")
    for r in rows:
        print(
            f"{r['hour']:>4}  {r['estimated_price']:>10.2f}  {r['actual_price']:>8.2f}  "
            f"{r['price_error']:>8.2f}  {r['demand_mw']:>10.0f}  {r['marginal_technology']}"
        )
    print(f"\nMAE: {mae:.2f} EUR/MWh over {len(rows)} hours (uncalibrated baseline, real ENTSO-E fleet/demand)")


if __name__ == "__main__":
    main()
