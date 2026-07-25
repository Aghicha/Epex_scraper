import pytest

from tradingsurv.domain.assets.models import GenerationAsset
from tradingsurv.domain.demand.curve import DemandCurve
from tradingsurv.explainability.driver_analysis import decompose_drivers, interaction_residual
from tradingsurv.explainability.templates import render_explanation
from tradingsurv.simulation.actions import IncreaseDemand, RemoveGenerator
from tradingsurv.simulation.engine import simulate
from tradingsurv.simulation.snapshot import AuctionSnapshot


def _base_snapshot() -> AuctionSnapshot:
    assets = (
        GenerationAsset(id="hydro1", zone="AT", name="Hydro 1", technology="hydro_ror", capacity_mw=200),
        GenerationAsset(id="wind1", zone="AT", name="Wind 1", technology="wind_onshore", capacity_mw=100),
        GenerationAsset(id="gas1", zone="AT", name="Gas 1", technology="gas", capacity_mw=150),
    )
    costs = {"hydro1": 0.0, "wind1": 0.0, "gas1": 80.0}
    demand = DemandCurve(base_mw=250, reference_price_eur_mwh=0.0)
    return AuctionSnapshot(zone="AT", assets=assets, costs=costs, demand=demand)


def test_single_action_impact_matches_full_scenario_delta():
    base = _base_snapshot()
    actions = [RemoveGenerator(asset_id="hydro1")]
    result = simulate(base, actions)
    drivers = decompose_drivers(base, actions)
    assert len(drivers) == 1
    assert drivers[0].price_impact_eur_mwh == pytest.approx(result.price_diff_eur_mwh)
    residual = interaction_residual(result.price_diff_eur_mwh, drivers)
    assert residual == pytest.approx(0.0)


def test_drivers_are_ranked_by_magnitude_descending():
    base = _base_snapshot()
    actions = [RemoveGenerator(asset_id="hydro1"), IncreaseDemand(delta_mw=1.0)]
    drivers = decompose_drivers(base, actions)
    magnitudes = [abs(d.price_impact_eur_mwh) for d in drivers]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert drivers[0].action == actions[0]  # removing 200 MW dominates a 1 MW demand tick


def test_describe_action_includes_asset_name():
    base = _base_snapshot()
    drivers = decompose_drivers(base, [RemoveGenerator(asset_id="hydro1")])
    assert "Hydro 1" in drivers[0].description


def test_render_explanation_reports_price_increase_and_marginal_change():
    base = _base_snapshot()
    actions = [RemoveGenerator(asset_id="hydro1")]
    result = simulate(base, actions)
    drivers = decompose_drivers(base, actions)
    text = render_explanation(result, drivers)

    assert "increased" in text
    assert f"{result.old_price_eur_mwh:.0f}" in text
    assert f"{result.new_price_eur_mwh:.0f}" in text
    assert "became marginal" in text
    assert "Hydro 1" in text


def test_render_explanation_no_op_scenario_says_unchanged_and_lists_no_drivers():
    base = _base_snapshot()
    result = simulate(base, [])
    drivers = decompose_drivers(base, [])
    text = render_explanation(result, drivers)
    assert "unchanged" in text
    assert "Primary drivers" not in text
