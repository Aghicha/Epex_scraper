import pytest

from tradingsurv.domain.assets.models import GenerationAsset
from tradingsurv.domain.clearing.solver import clear
from tradingsurv.domain.demand.curve import DemandCurve
from tradingsurv.domain.merit_order.builder import build_supply_curve


def _curve():
    assets = [
        GenerationAsset(id="wind1", zone="AT", name="Wind 1", technology="wind_onshore", capacity_mw=100),
        GenerationAsset(id="nuke1", zone="AT", name="Nuke 1", technology="nuclear", capacity_mw=200),
        GenerationAsset(id="gas1", zone="AT", name="Gas 1", technology="gas_ccgt", capacity_mw=150),
        GenerationAsset(id="coal1", zone="AT", name="Coal 1", technology="coal", capacity_mw=120),
    ]
    costs = {"wind1": 0.0, "nuke1": 10.0, "gas1": 80.0, "coal1": 60.0}
    return build_supply_curve(assets, costs)


def test_clears_at_marginal_unit_covering_inelastic_demand():
    supply = _curve()
    demand = DemandCurve(base_mw=250, reference_price_eur_mwh=10.0)  # falls inside nuke's 300 MW block
    result = clear(supply, demand)
    assert result.marginal_asset_id == "nuke1"
    assert result.price_eur_mwh == pytest.approx(10.0)
    assert result.volume_mw == pytest.approx(250.0)
    assert result.shortage_mw == pytest.approx(0.0)


def test_higher_demand_pushes_more_expensive_unit_to_the_margin():
    supply = _curve()
    demand = DemandCurve(base_mw=500, reference_price_eur_mwh=10.0)  # wind+nuke+coal = 420, needs gas
    result = clear(supply, demand)
    assert result.marginal_asset_id == "gas1"
    assert result.price_eur_mwh == pytest.approx(80.0)


def test_demand_exceeding_total_capacity_reports_shortage():
    supply = _curve()
    demand = DemandCurve(base_mw=10_000, reference_price_eur_mwh=10.0)
    result = clear(supply, demand)
    assert result.marginal_asset_id == "gas1"  # top of the stack
    assert result.shortage_mw == pytest.approx(10_000 - supply.total_capacity_mw)
    assert result.volume_mw == pytest.approx(supply.total_capacity_mw)


def test_elastic_demand_converges_to_a_stable_price():
    supply = _curve()
    # Elastic demand: as price rises above the coal band, demand should
    # shrink back toward a level the curve can actually clear.
    demand = DemandCurve(base_mw=500, reference_price_eur_mwh=10.0, elasticity_mw_per_eur=2.0)
    result = clear(supply, demand)
    implied_demand = demand.demand_at(result.price_eur_mwh)
    assert implied_demand == pytest.approx(result.volume_mw, abs=1.0)


def test_empty_supply_curve_raises():
    from tradingsurv.domain.merit_order.supply_curve import SupplyCurve

    with pytest.raises(ValueError):
        clear(SupplyCurve(points=()), DemandCurve(base_mw=100, reference_price_eur_mwh=10.0))
