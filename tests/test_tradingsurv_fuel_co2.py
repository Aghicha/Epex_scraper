from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tradingsurv.ingestion.fuel_co2 import prices


def _fake_history(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes})


@patch("tradingsurv.ingestion.fuel_co2.prices.yf.Ticker")
def test_gas_price_returns_latest_non_null_close(mock_ticker_cls):
    mock_ticker_cls.return_value = MagicMock(history=lambda period: _fake_history([60.1, 61.2, 62.5]))
    assert prices.gas_price_eur_mwh_th() == pytest.approx(62.5)
    mock_ticker_cls.assert_called_with(prices.GAS_TICKER)


@patch("tradingsurv.ingestion.fuel_co2.prices.yf.Ticker")
def test_co2_price_skips_trailing_nan(mock_ticker_cls):
    mock_ticker_cls.return_value = MagicMock(history=lambda period: _fake_history([78.0, 79.6, float("nan")]))
    assert prices.co2_price_eur_t() == pytest.approx(79.6)
    mock_ticker_cls.assert_called_with(prices.CO2_TICKER)


@patch("tradingsurv.ingestion.fuel_co2.prices.yf.Ticker")
def test_empty_history_raises_clear_error(mock_ticker_cls):
    mock_ticker_cls.return_value = MagicMock(history=lambda period: pd.DataFrame())
    with pytest.raises(RuntimeError, match="no recent price data"):
        prices.gas_price_eur_mwh_th()
