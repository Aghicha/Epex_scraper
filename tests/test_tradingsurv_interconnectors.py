import pytest

from tradingsurv.domain.interconnectors.model import export_demand_mw, import_supply_asset


def test_net_importer_produces_import_asset_sized_to_net_position():
    asset = import_supply_asset("AT", net_position_mw=500.0)
    assert asset is not None
    assert asset.capacity_mw == pytest.approx(500.0)
    assert asset.zone == "AT"
    assert asset.technology == "import"


def test_net_exporter_produces_no_import_asset():
    assert import_supply_asset("AT", net_position_mw=-500.0) is None


def test_zero_net_position_produces_no_import_asset():
    assert import_supply_asset("AT", net_position_mw=0.0) is None


def test_import_capacity_is_capped_by_limit_mw():
    asset = import_supply_asset("AT", net_position_mw=500.0, limit_mw=200.0)
    assert asset.capacity_mw == pytest.approx(200.0)


def test_limit_above_net_position_has_no_effect():
    asset = import_supply_asset("AT", net_position_mw=500.0, limit_mw=900.0)
    assert asset.capacity_mw == pytest.approx(500.0)


def test_net_exporter_produces_export_demand_matching_magnitude():
    assert export_demand_mw(net_position_mw=-500.0) == pytest.approx(500.0)


def test_net_importer_produces_zero_export_demand():
    assert export_demand_mw(net_position_mw=500.0) == pytest.approx(0.0)


def test_export_demand_is_capped_by_limit_mw():
    assert export_demand_mw(net_position_mw=-500.0, limit_mw=200.0) == pytest.approx(200.0)
