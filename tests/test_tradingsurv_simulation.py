import pytest

from tradingsurv.domain.assets.models import GenerationAsset
from tradingsurv.domain.demand.curve import DemandCurve
from tradingsurv.domain.interconnectors.model import IMPORT_TECHNOLOGY
from tradingsurv.simulation.actions import (
    AddOutage,
    IncreaseDemand,
    LimitInterconnector,
    ReduceCapacity,
    ReduceSolar,
    ReduceWind,
    RemoveGenerator,
    apply_action,
    apply_actions,
)
from tradingsurv.simulation.engine import simulate
from tradingsurv.simulation.snapshot import AuctionSnapshot


def _base_snapshot() -> AuctionSnapshot:
    assets = (
        GenerationAsset(id="wind1", zone="AT", name="Wind 1", technology="wind_onshore", capacity_mw=100),
        GenerationAsset(id="solar1", zone="AT", name="Solar 1", technology="solar", capacity_mw=100),
        GenerationAsset(id="hydro1", zone="AT", name="Hydro 1", technology="hydro_ror", capacity_mw=200),
        GenerationAsset(id="gas1", zone="AT", name="Gas 1", technology="gas", capacity_mw=150),
        GenerationAsset(id="import1", zone="AT", name="AT imports", technology=IMPORT_TECHNOLOGY, capacity_mw=300),
    )
    costs = {"wind1": 0.0, "solar1": 0.0, "hydro1": 0.0, "gas1": 80.0, "import1": 50.0}
    # 0-cost block totals 400 MW (hydro1+solar1+wind1); demand=350 lands
    # inside it (wind1 is marginal, alphabetically last among the 0-cost
    # tie-break), so removing any one 0-cost asset pushes the clearing
    # point into the 50 EUR/MWh import block.
    demand = DemandCurve(base_mw=350, reference_price_eur_mwh=50.0)
    return AuctionSnapshot(zone="AT", assets=assets, costs=costs, demand=demand)


def test_remove_generator_drops_asset_from_supply():
    base = _base_snapshot()
    new = apply_action(base, RemoveGenerator(asset_id="gas1"))
    assert new.asset("gas1") is None
    assert base.asset("gas1") is not None  # base untouched


def test_reduce_capacity_lowers_available_mw():
    base = _base_snapshot()
    new = apply_action(base, ReduceCapacity(asset_id="hydro1", reduce_by_mw=50.0))
    assert new.available_mw["hydro1"] == pytest.approx(150.0)
    assert "hydro1" not in base.available_mw  # base untouched


def test_reduce_capacity_cannot_go_negative():
    base = _base_snapshot()
    new = apply_action(base, ReduceCapacity(asset_id="hydro1", reduce_by_mw=999.0))
    assert new.available_mw["hydro1"] == pytest.approx(0.0)


def test_add_outage_has_same_mechanical_effect_as_reduce_capacity():
    base = _base_snapshot()
    via_outage = apply_action(base, AddOutage(asset_id="gas1", unavailable_mw=60.0))
    via_reduce = apply_action(base, ReduceCapacity(asset_id="gas1", reduce_by_mw=60.0))
    assert via_outage.available_mw["gas1"] == pytest.approx(via_reduce.available_mw["gas1"])


def test_increase_demand_shifts_base_mw():
    base = _base_snapshot()
    new = apply_action(base, IncreaseDemand(delta_mw=100.0))
    assert new.demand.base_mw == pytest.approx(450.0)
    assert base.demand.base_mw == pytest.approx(350.0)


def test_reduce_wind_targets_wind_assets_only():
    base = _base_snapshot()
    new = apply_action(base, ReduceWind(delta_mw=30.0))
    assert new.available_mw["wind1"] == pytest.approx(70.0)
    assert "solar1" not in new.available_mw


def test_reduce_wind_spreads_across_multiple_wind_assets():
    assets = (
        GenerationAsset(id="w1", zone="AT", name="W1", technology="wind_onshore", capacity_mw=50),
        GenerationAsset(id="w2", zone="AT", name="W2", technology="wind_onshore", capacity_mw=50),
    )
    snapshot = AuctionSnapshot(
        zone="AT", assets=assets, costs={"w1": 0.0, "w2": 0.0},
        demand=DemandCurve(base_mw=50, reference_price_eur_mwh=10.0),
    )
    new = apply_action(snapshot, ReduceWind(delta_mw=60.0))
    assert new.available_mw["w1"] == pytest.approx(0.0)
    assert new.available_mw["w2"] == pytest.approx(40.0)


def test_reduce_solar_targets_solar_assets_only():
    base = _base_snapshot()
    new = apply_action(base, ReduceSolar(delta_mw=40.0))
    assert new.available_mw["solar1"] == pytest.approx(60.0)
    assert "wind1" not in new.available_mw


def test_limit_interconnector_caps_import_asset():
    base = _base_snapshot()
    new = apply_action(base, LimitInterconnector(new_limit_mw=100.0))
    assert new.available_mw["import1"] == pytest.approx(100.0)


def test_limit_interconnector_above_capacity_has_no_effect():
    base = _base_snapshot()
    new = apply_action(base, LimitInterconnector(new_limit_mw=999.0))
    assert new.available_mw.get("import1", base.asset("import1").capacity_mw) == pytest.approx(300.0)


def test_apply_actions_composes_in_order():
    base = _base_snapshot()
    new = apply_actions(base, [ReduceCapacity(asset_id="hydro1", reduce_by_mw=50.0), IncreaseDemand(delta_mw=20.0)])
    assert new.available_mw["hydro1"] == pytest.approx(150.0)
    assert new.demand.base_mw == pytest.approx(370.0)


def test_simulate_removing_cheap_capacity_raises_price_and_changes_marginal():
    base = _base_snapshot()
    result = simulate(base, [RemoveGenerator(asset_id="hydro1")])
    assert result.old_price_eur_mwh == pytest.approx(0.0)  # wind/solar/hydro cover 350 MW before removal
    assert result.new_price_eur_mwh == pytest.approx(50.0)  # falls through to the import block
    assert result.price_diff_eur_mwh > 0
    assert result.old_marginal_technology != result.new_marginal_technology


def test_simulate_no_actions_is_a_no_op():
    base = _base_snapshot()
    result = simulate(base, [])
    assert result.price_diff_eur_mwh == pytest.approx(0.0)
    assert result.old_price_eur_mwh == pytest.approx(result.new_price_eur_mwh)
