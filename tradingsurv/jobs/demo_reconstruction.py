"""Phase 0/1 smoke test: reconstruct an AT day-ahead auction and compare to actual.

This wires the whole domain engine (assets -> costs -> merit order -> demand
-> clearing) end to end against real data for one thing only: the actual
price, read straight from epex_scraper's own archive via ``epex_reader`` — no
ENTSO-E token needed to run this.

The generation fleet below is a **hand-built placeholder**, not real
unit-level ENTSO-E data (that's Phase 0's ``installed_capacity_per_unit``
ingestion, gated on a registered ``ENTSOE_API_TOKEN``). It's deliberately
Austria-shaped — hydro-dominated, no nuclear or coal, since Austria has
neither — so the reconstruction is directionally sane, not so it's accurate.
Its only job is to prove the pipeline runs end to end and to produce a first
(expectedly large) MAE baseline that Step 7 calibration would then chip away
at once real assets/generation data are wired in.

Run: python -m tradingsurv.jobs.demo_reconstruction --date 2026-07-24
"""

from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

from ..domain.assets.models import GenerationAsset
from ..domain.clearing.solver import clear
from ..domain.costs.hydro import PUMPED_STORAGE, RESERVOIR, RUN_OF_RIVER, HydroCostModel
from ..domain.costs.renewables import ZeroMarginalCostModel
from ..domain.costs.thermal import ThermalCostModel
from ..domain.demand.curve import DemandCurve
from ..domain.merit_order.builder import build_supply_curve
from ..ingestion.market_prices.epex_reader import read_actual_day_ahead_prices

GAS_PRICE_EUR_MWH_TH = 30.0
CO2_PRICE_EUR_T = 70.0

ASSETS = [
    GenerationAsset(id="hydro_ror", zone="AT", name="Run-of-river fleet", technology=RUN_OF_RIVER, capacity_mw=5000),
    GenerationAsset(id="hydro_res", zone="AT", name="Reservoir fleet", technology=RESERVOIR, capacity_mw=3000),
    GenerationAsset(id="hydro_pump", zone="AT", name="Pumped storage fleet", technology=PUMPED_STORAGE, capacity_mw=3000),
    GenerationAsset(id="wind", zone="AT", name="Wind fleet", technology="wind_onshore", capacity_mw=3200),
    GenerationAsset(id="solar", zone="AT", name="Solar fleet", technology="solar", capacity_mw=3000),
    GenerationAsset(id="gas_ccgt", zone="AT", name="CCGT fleet", technology="gas_ccgt", capacity_mw=2000, efficiency=0.55, fuel="natural_gas"),
    GenerationAsset(id="gas_ocgt", zone="AT", name="OCGT peakers", technology="gas_ocgt", capacity_mw=1000, efficiency=0.35, fuel="natural_gas"),
]


def _solar_capacity_factor(hour: int) -> float:
    if 6 <= hour <= 20:
        return max(0.0, math.sin(math.pi * (hour - 6) / 14))
    return 0.0


def _wind_capacity_factor(hour: int) -> float:
    return 0.30  # flat placeholder; real value comes from ENTSO-E generation forecast


def _marginal_costs() -> dict[str, float]:
    return {
        "hydro_ror": HydroCostModel(RUN_OF_RIVER).marginal_cost(),
        "hydro_res": HydroCostModel(RESERVOIR, water_value_eur_mwh=40.0).marginal_cost(),
        "hydro_pump": HydroCostModel(PUMPED_STORAGE, water_value_eur_mwh=60.0).marginal_cost(),
        "wind": ZeroMarginalCostModel("wind_onshore").marginal_cost(),
        "solar": ZeroMarginalCostModel("solar").marginal_cost(),
        "gas_ccgt": ThermalCostModel(
            "gas_ccgt", "natural_gas", GAS_PRICE_EUR_MWH_TH, 0.55, CO2_PRICE_EUR_T
        ).marginal_cost(),
        "gas_ocgt": ThermalCostModel(
            "gas_ocgt", "natural_gas", GAS_PRICE_EUR_MWH_TH, 0.35, CO2_PRICE_EUR_T
        ).marginal_cost(),
    }


def _available_mw(hour: int) -> dict[str, float]:
    return {
        "wind": ASSETS[3].capacity_mw * _wind_capacity_factor(hour),
        "solar": ASSETS[4].capacity_mw * _solar_capacity_factor(hour),
    }


def reconstruct_hour(hour: int, actual_price: float, demand_mw: float = 7000.0) -> dict:
    costs = _marginal_costs()
    supply = build_supply_curve(ASSETS, costs, available_mw=_available_mw(hour))
    demand = DemandCurve(base_mw=demand_mw, reference_price_eur_mwh=actual_price)
    result = clear(supply, demand)
    return {
        "hour": hour,
        "estimated_price": result.price_eur_mwh,
        "actual_price": actual_price,
        "price_error": result.price_eur_mwh - actual_price,
        "marginal_technology": result.marginal_technology,
        "marginal_asset_id": result.marginal_asset_id,
    }


def run_demo(zone: str, delivery_date: date, data_root: Path) -> list[dict]:
    actual = read_actual_day_ahead_prices(data_root, zone, delivery_date, resolution=60)
    if not actual:
        raise SystemExit(
            f"no actual prices found for {zone} {delivery_date} under {data_root} — "
            "has epex_scraper archived that day?"
        )

    rows = []
    for period_start in sorted(actual):
        rows.append(reconstruct_hour(period_start.hour, actual[period_start]))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zone", default="AT")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD delivery date")
    parser.add_argument("--data-dir", default=Path(__file__).resolve().parent.parent.parent / "data")
    args = parser.parse_args()

    rows = run_demo(args.zone, date.fromisoformat(args.date), Path(args.data_dir))

    errors = [r["price_error"] for r in rows]
    mae = sum(abs(e) for e in errors) / len(errors)

    print(f"{'hour':>4}  {'estimated':>10}  {'actual':>8}  {'error':>8}  marginal")
    for r in rows:
        print(
            f"{r['hour']:>4}  {r['estimated_price']:>10.2f}  {r['actual_price']:>8.2f}  "
            f"{r['price_error']:>8.2f}  {r['marginal_technology']}"
        )
    print(f"\nMAE: {mae:.2f} EUR/MWh over {len(rows)} hours (uncalibrated baseline)")


if __name__ == "__main__":
    main()
