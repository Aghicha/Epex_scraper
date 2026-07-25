from datetime import datetime

import pytest

from tradingsurv.domain.calibration.engine import (
    CalibrationObservation,
    fit_technology_offsets,
    fit_water_values,
)


def _obs(hour: int, actual: float, estimated: float, marginal: str) -> CalibrationObservation:
    return CalibrationObservation(
        timestamp=datetime(2026, 7, 24, hour), actual_price=actual, estimated_price=estimated,
        marginal_technology=marginal,
    )


def test_offset_equals_median_gap_when_technology_is_marginal():
    observations = [
        _obs(0, actual=100.0, estimated=80.0, marginal="gas"),
        _obs(1, actual=110.0, estimated=80.0, marginal="gas"),
        _obs(2, actual=90.0, estimated=80.0, marginal="gas"),
    ]
    offsets = fit_technology_offsets(observations, min_samples=3)
    # gaps: 20, 30, 10 -> median 20
    assert offsets["gas"] == pytest.approx(20.0)


def test_technologies_below_min_samples_are_skipped():
    observations = [
        _obs(0, actual=100.0, estimated=80.0, marginal="gas"),
        _obs(1, actual=90.0, estimated=0.0, marginal="hydro_ror"),  # only 1 sample
    ]
    offsets = fit_technology_offsets(observations, min_samples=2)
    assert "hydro_ror" not in offsets
    assert "gas" not in offsets  # gas also only has 1 sample here


def test_offset_is_robust_to_a_single_outlier():
    observations = [
        _obs(0, actual=100.0, estimated=80.0, marginal="gas"),
        _obs(1, actual=101.0, estimated=80.0, marginal="gas"),
        _obs(2, actual=1000.0, estimated=80.0, marginal="gas"),  # outlier
    ]
    offsets = fit_technology_offsets(observations, min_samples=3)
    # median of (20, 21, 920) = 21, not pulled toward the outlier the way a mean would be
    assert offsets["gas"] == pytest.approx(21.0)


def test_different_technologies_get_independent_offsets():
    observations = [
        _obs(0, actual=100.0, estimated=80.0, marginal="gas"),
        _obs(1, actual=100.0, estimated=80.0, marginal="gas"),
        _obs(2, actual=50.0, estimated=0.0, marginal="hydro_ror"),
        _obs(3, actual=60.0, estimated=0.0, marginal="hydro_ror"),
    ]
    offsets = fit_technology_offsets(observations, min_samples=2)
    assert offsets["gas"] == pytest.approx(20.0)
    assert offsets["hydro_ror"] == pytest.approx(55.0)


def test_water_values_use_per_technology_quantile_of_actual_prices():
    prices = [10.0, 20.0, 30.0, 40.0, 50.0]
    water_values = fit_water_values(prices, quantiles={"hydro_reservoir": 0.5, "hydro_pumped": 1.0})
    assert water_values["hydro_reservoir"] == pytest.approx(30.0)  # median
    assert water_values["hydro_pumped"] == pytest.approx(50.0)  # max


def test_water_values_empty_prices_raises():
    with pytest.raises(ValueError):
        fit_water_values([], quantiles={"hydro_reservoir": 0.5})
