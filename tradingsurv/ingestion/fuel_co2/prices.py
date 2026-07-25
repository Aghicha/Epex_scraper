"""Fuel and carbon price ingestion.

Unlike ENTSO-E, there's no single free official API publishing daily TTF gas
or EUA carbon prices with a stable, documented endpoint. This module uses
Yahoo Finance's public quote data (via ``yfinance``, no API key) as a
pragmatic free proxy:

  - Gas: ``TTF=F`` — Dutch TTF natural gas futures, already EUR/MWh (TTF's
    standard quoting convention, so no unit conversion needed).
  - CO2: ``CO2.L`` — SparkChange Physical Carbon EUA ETC, a EUR-denominated,
    physically-EUA-backed exchange-traded commodity on the LSE. Tracks the
    EUA spot price closely but isn't the raw auction/spot price itself (ETC
    fee + minor tracking difference) — treat as directional pending Step 7
    calibration against actual settled prices, not authoritative.

No equivalent free, reliable ARA/API2 coal price ticker was found on Yahoo
Finance (nor a documented free official source, unlike EEX's paid data
products) — ``coal_price_eur_mwh_th`` is deliberately not implemented here;
callers must supply a coal price explicitly (see ``FuelPrices`` in
``domain/costs/estimate.py``) until a real source is identified. Same for
oil, which is a small share of most zones' fleets.
"""

from __future__ import annotations

import yfinance as yf

GAS_TICKER = "TTF=F"
CO2_TICKER = "CO2.L"


def _latest_close(ticker: str) -> float:
    history = yf.Ticker(ticker).history(period="5d")
    closes = history["Close"].dropna() if not history.empty else history
    if closes.empty:
        raise RuntimeError(f"no recent price data for {ticker!r} from Yahoo Finance")
    return float(closes.iloc[-1])


def gas_price_eur_mwh_th() -> float:
    """Latest Dutch TTF gas price, EUR/MWh_th."""
    return _latest_close(GAS_TICKER)


def co2_price_eur_t() -> float:
    """Latest EUA carbon price proxy, EUR/tCO2."""
    return _latest_close(CO2_TICKER)
