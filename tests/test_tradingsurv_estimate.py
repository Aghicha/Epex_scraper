import pytest

from tradingsurv.domain.assets.models import GenerationAsset
from tradingsurv.domain.costs.estimate import FuelPrices, estimate_marginal_costs
from tradingsurv.domain.costs.hydro import RESERVOIR, RUN_OF_RIVER


def _fuel_prices():
    return FuelPrices(
        gas_eur_mwh_th=30.0, coal_eur_mwh_th=15.0, lignite_eur_mwh_th=8.0,
        oil_eur_mwh_th=45.0, co2_eur_t=70.0,
    )


def test_dispatches_each_technology_to_its_own_model():
    assets = [
        GenerationAsset(id="a", zone="AT", name="ror", technology=RUN_OF_RIVER, capacity_mw=100),
        GenerationAsset(id="b", zone="AT", name="res", technology=RESERVOIR, capacity_mw=100),
        GenerationAsset(id="c", zone="AT", name="wind", technology="wind_onshore", capacity_mw=100),
        GenerationAsset(id="d", zone="AT", name="solar", technology="solar", capacity_mw=100),
        GenerationAsset(id="e", zone="AT", name="gas", technology="gas", capacity_mw=100),
        GenerationAsset(id="f", zone="AT", name="battery", technology="battery", capacity_mw=100),
        GenerationAsset(id="g", zone="AT", name="biomass", technology="biomass", capacity_mw=100),
    ]
    costs = estimate_marginal_costs(assets, _fuel_prices(), water_value_eur_mwh={RESERVOIR: 40.0})

    assert costs["a"] == pytest.approx(0.0)  # run-of-river, must-run
    assert costs["c"] == pytest.approx(0.0)  # wind
    assert costs["d"] == pytest.approx(0.0)  # solar
    assert costs["b"] > costs["a"]  # reservoir has a water value, ROR doesn't
    assert costs["e"] > costs["b"]  # gas more expensive than hydro at these prices
    assert costs["g"] > 0  # biomass flat placeholder, not zero
    assert all(asset.id in costs for asset in assets)


def test_water_value_and_offsets_are_keyed_by_technology_not_asset_id():
    assets = [
        GenerationAsset(id="res1", zone="AT", name="res1", technology=RESERVOIR, capacity_mw=100),
        GenerationAsset(id="res2", zone="DE-LU", name="res2", technology=RESERVOIR, capacity_mw=100),
    ]
    costs = estimate_marginal_costs(
        assets, _fuel_prices(), water_value_eur_mwh={RESERVOIR: 42.0}, offsets={RESERVOIR: 3.0},
    )
    assert costs["res1"] == pytest.approx(45.0)
    assert costs["res2"] == pytest.approx(45.0)


def test_gas_efficiency_falls_back_to_default_when_asset_has_none():
    asset = GenerationAsset(id="gas1", zone="AT", name="gas", technology="gas", capacity_mw=100)
    costs = estimate_marginal_costs([asset], _fuel_prices())
    # 30/0.50 + (0.202/0.50)*70 + 2 = 60 + 28.28 + 2
    assert costs["gas1"] == pytest.approx(90.28)


def test_explicit_asset_efficiency_overrides_default():
    asset = GenerationAsset(id="gas1", zone="AT", name="gas", technology="gas", capacity_mw=100, efficiency=0.6)
    costs = estimate_marginal_costs([asset], _fuel_prices())
    default_costs = estimate_marginal_costs(
        [GenerationAsset(id="gas1", zone="AT", name="gas", technology="gas", capacity_mw=100)], _fuel_prices()
    )
    assert costs["gas1"] != default_costs["gas1"]
