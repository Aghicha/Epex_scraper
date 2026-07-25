import pytest

from tradingsurv.domain.assets.models import GenerationAsset
from tradingsurv.domain.merit_order.builder import build_supply_curve


def _assets():
    return [
        GenerationAsset(id="wind1", zone="AT", name="Wind 1", technology="wind_onshore", capacity_mw=100),
        GenerationAsset(id="nuke1", zone="AT", name="Nuke 1", technology="nuclear", capacity_mw=200),
        GenerationAsset(id="gas1", zone="AT", name="Gas 1", technology="gas_ccgt", capacity_mw=150),
        GenerationAsset(id="coal1", zone="AT", name="Coal 1", technology="coal", capacity_mw=120),
    ]


def _costs():
    return {"wind1": 0.0, "nuke1": 10.0, "gas1": 80.0, "coal1": 60.0}


def test_curve_is_sorted_by_marginal_cost_ascending():
    curve = build_supply_curve(_assets(), _costs())
    costs = [p.marginal_cost_eur_mwh for p in curve.points]
    assert costs == sorted(costs)
    assert [p.asset_id for p in curve.points] == ["wind1", "nuke1", "coal1", "gas1"]


def test_cumulative_capacity_accumulates_correctly():
    curve = build_supply_curve(_assets(), _costs())
    assert curve.total_capacity_mw == pytest.approx(100 + 200 + 150 + 120)
    cumulative = [p.cumulative_mw for p in curve.points]
    assert cumulative == sorted(cumulative)


def test_full_outage_excludes_asset_from_curve():
    curve = build_supply_curve(_assets(), _costs(), available_mw={"gas1": 0.0})
    assert "gas1" not in [p.asset_id for p in curve.points]
    assert curve.total_capacity_mw == pytest.approx(100 + 200 + 120)


def test_partial_derate_caps_at_available_capacity():
    curve = build_supply_curve(_assets(), _costs(), available_mw={"coal1": 50.0})
    coal_point = next(p for p in curve.points if p.asset_id == "coal1")
    assert coal_point.capacity_mw == pytest.approx(50.0)


def test_available_mw_cannot_exceed_nameplate_capacity():
    curve = build_supply_curve(_assets(), _costs(), available_mw={"coal1": 999.0})
    coal_point = next(p for p in curve.points if p.asset_id == "coal1")
    assert coal_point.capacity_mw == pytest.approx(120.0)


def test_missing_marginal_cost_raises():
    with pytest.raises(KeyError):
        build_supply_curve(_assets(), {"wind1": 0.0})


def test_marginal_point_at_finds_cheapest_unit_covering_target_volume():
    curve = build_supply_curve(_assets(), _costs())
    # wind(100) + nuke(200) = 300 cumulative; 250 MW still falls inside nuke.
    point = curve.marginal_point_at(250)
    assert point.asset_id == "nuke1"


def test_marginal_point_at_saturates_at_last_point_beyond_total_capacity():
    curve = build_supply_curve(_assets(), _costs())
    point = curve.marginal_point_at(curve.total_capacity_mw + 1000)
    assert point.asset_id == "gas1"
