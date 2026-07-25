"""Read epex_scraper's own archive as TradingSurv's actual-price ground truth.

epex_scraper already maintains a deduplicated, per-delivery-day CSV archive
of settled EPEX prices at ``data/day-ahead/<zone>/<date>_<resolution>min.csv``
(see epex_scraper/storage.py). This module is the *only* piece of ingestion
TradingSurv needs for Step 7 calibration and ex-post validation — no
separate "get actual prices" integration.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from epex_scraper.storage import partition_path

DAY_AHEAD_SLUG = "day-ahead"


def read_actual_day_ahead_prices(
    data_root: Path,
    zone: str,
    delivery_date: date,
    resolution: int = 60,
) -> dict[datetime, float]:
    """Return {period_start: price_eur_mwh} for one zone/day, or {} if unscraped.

    Mirrors epex_scraper's own "no data -> empty, not an error" convention:
    a delivery day that hasn't been scraped yet (or never trades in this
    zone/resolution) yields an empty dict rather than raising.
    """
    path = partition_path(Path(data_root), DAY_AHEAD_SLUG, zone, resolution, delivery_date)
    if not path.exists():
        return {}

    df = pd.read_csv(path)
    price_column = next((c for c in df.columns if c.startswith("Price")), None)
    if price_column is None:
        return {}

    prices: dict[datetime, float] = {}
    for period_start, price in zip(df["period_start"], df[price_column]):
        if pd.isna(price):
            continue
        prices[pd.Timestamp(period_start).to_pydatetime()] = float(price)
    return prices
