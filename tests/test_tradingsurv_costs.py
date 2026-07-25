import pytest

from tradingsurv.domain.costs.battery import BatteryCostModel
from tradingsurv.domain.costs.hydro import PUMPED_STORAGE, RUN_OF_RIVER, HydroCostModel
from tradingsurv.domain.costs.nuclear import NuclearCostModel
from tradingsurv.domain.costs.renewables import ZeroMarginalCostModel
from tradingsurv.domain.costs.thermal import ThermalCostModel


def test_thermal_gas_marginal_cost_matches_formula():
    model = ThermalCostModel(
        technology="gas_ccgt", fuel="natural_gas",
        fuel_price_eur_mwh_th=30.0, efficiency=0.5,
        co2_price_eur_t=70.0, variable_om_eur_mwh=2.0,
    )
    # 30/0.5 + (0.202/0.5)*70 + 2 = 60 + 28.28 + 2
    assert model.marginal_cost() == pytest.approx(90.28)


def test_thermal_offset_is_additive():
    model = ThermalCostModel(
        technology="coal", fuel="hard_coal",
        fuel_price_eur_mwh_th=15.0, efficiency=0.4, co2_price_eur_t=70.0,
    )
    base = model.marginal_cost()
    assert model.marginal_cost(offset_eur_mwh=5.0) == pytest.approx(base + 5.0)


def test_thermal_rejects_unknown_fuel():
    with pytest.raises(ValueError):
        ThermalCostModel(
            technology="x", fuel="unobtainium", fuel_price_eur_mwh_th=10.0,
            efficiency=0.5, co2_price_eur_t=70.0,
        )


def test_thermal_rejects_bad_efficiency():
    with pytest.raises(ValueError):
        ThermalCostModel(
            technology="gas", fuel="natural_gas", fuel_price_eur_mwh_th=10.0,
            efficiency=0.0, co2_price_eur_t=70.0,
        )


def test_nuclear_is_flat_low_cost():
    assert NuclearCostModel().marginal_cost() == pytest.approx(10.0)
    assert NuclearCostModel(base_cost_eur_mwh=12.0).marginal_cost(offset_eur_mwh=3.0) == pytest.approx(15.0)


def test_renewables_default_to_zero_with_negative_floor_supported():
    assert ZeroMarginalCostModel("wind_onshore").marginal_cost() == pytest.approx(0.0)
    assert ZeroMarginalCostModel("solar", price_floor_eur_mwh=-40.0).marginal_cost() == pytest.approx(-40.0)


def test_hydro_run_of_river_ignores_water_value():
    model = HydroCostModel(RUN_OF_RIVER, water_value_eur_mwh=25.0)
    assert model.marginal_cost() == pytest.approx(0.0)


def test_hydro_reservoir_uses_water_value():
    model = HydroCostModel(PUMPED_STORAGE, water_value_eur_mwh=45.0)
    assert model.marginal_cost() == pytest.approx(45.0)


def test_battery_opportunity_cost():
    model = BatteryCostModel(expected_charge_price_eur_mwh=20.0, degradation_cost_eur_mwh=5.0)
    assert model.marginal_cost() == pytest.approx(25.0)
