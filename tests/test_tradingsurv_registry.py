import pandas as pd

from tradingsurv.domain.assets.registry import build_pooled_fleet
from tradingsurv.domain.costs.hydro import RESERVOIR, RUN_OF_RIVER


def _capacity_series():
    return pd.Series(
        {
            "Hydro Run-of-river and poundage": 5937.0,
            "Hydro Water Reservoir": 2547.0,
            "Nuclear": 0.0,
            "Fossil Hard coal": 0.0,
            "Solar": 9766.0,
            "Wind Onshore": 4140.0,
            "Geothermal": 0.0,
        }
    )


def test_zero_capacity_technologies_are_excluded():
    assets = build_pooled_fleet("AT", _capacity_series())
    technologies = {a.technology for a in assets}
    assert "nuclear" not in technologies
    assert "coal" not in technologies
    assert "other" not in technologies  # Geothermal was 0 MW


def test_known_technologies_map_correctly():
    assets = build_pooled_fleet("AT", _capacity_series())
    by_technology = {a.technology: a for a in assets}
    assert by_technology[RUN_OF_RIVER].capacity_mw == 5937.0
    assert by_technology[RESERVOIR].capacity_mw == 2547.0
    assert by_technology["solar"].capacity_mw == 9766.0
    assert by_technology["wind_onshore"].capacity_mw == 4140.0


def test_asset_ids_are_stable_and_zone_scoped():
    assets = build_pooled_fleet("AT", _capacity_series())
    ids = [a.id for a in assets]
    assert all(i.startswith("AT:") for i in ids)
    assert len(ids) == len(set(ids))


def test_unknown_production_type_falls_back_to_other():
    series = pd.Series({"Some New Tech ENTSO-E Adds Later": 100.0})
    assets = build_pooled_fleet("AT", series)
    assert assets[0].technology == "other"


def test_distinct_production_types_mapping_to_same_technology_get_distinct_ids():
    # "Other" and "Waste" both collapse to technology "other" (TECHNOLOGY_MAP)
    # — a real collision found in production against real AT data, where an
    # id keyed off the collapsed technology merged two distinct assets.
    series = pd.Series({"Other": 851.0, "Waste": 124.0})
    assets = build_pooled_fleet("AT", series)
    ids = [a.id for a in assets]
    assert len(ids) == len(set(ids)) == 2
    assert all(a.technology == "other" for a in assets)
