import pytest

from tradingsurv.domain.calibration.metrics import bias, mae, rmse


def test_mae_averages_absolute_errors():
    assert mae([10.0, -10.0, 5.0]) == pytest.approx((10 + 10 + 5) / 3)


def test_rmse_penalizes_large_errors_more_than_mae():
    errors = [1.0, 1.0, 10.0]
    assert rmse(errors) > mae(errors)


def test_bias_is_signed_mean():
    assert bias([10.0, -4.0]) == pytest.approx(3.0)


def test_zero_errors_give_zero_metrics():
    assert mae([0.0, 0.0]) == 0.0
    assert rmse([0.0, 0.0]) == 0.0
    assert bias([0.0, 0.0]) == 0.0


@pytest.mark.parametrize("fn", [mae, rmse, bias])
def test_empty_sequence_raises(fn):
    with pytest.raises(ValueError):
        fn([])
