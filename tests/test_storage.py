from datetime import date

import pandas as pd

from epex_scraper.storage import is_settled, partition_path, write_partition


def _records():
    common = {
        "market_area": "FR", "modality": "Auction", "sub_modality": "DayAhead",
        "auction": "MRC", "product": 15, "delivery_date": date(2026, 7, 9),
        "trading_date": "2026-07-08", "source_url": "u",
        "scraped_at": "2026-07-09T00:00:00+00:00",
    }
    recs = []
    for pi, (label, buy, sell, vol, price) in enumerate([
        ("00:00 - 00:15", 0.0, 9.2, 9.2, 131.92),
        ("00:15 - 00:30", 0.0, 5.3, 5.3, 133.53),
    ]):
        start = f"2026-07-09T00:{pi*15:02d}:00"
        for metric, unit, value in [
            ("buy_volume", "MWh", buy), ("sell_volume", "MWh", sell),
            ("volume", "MWh", vol), ("price", "€/MWh", price),
        ]:
            recs.append({**common, "period_index": pi, "period_label": label,
                         "period_start": start, "metric": metric, "unit": unit,
                         "value": value, "value_raw": str(value)})
    return recs


def test_partition_path_layout(tmp_path):
    path = partition_path(tmp_path, "dayahead-mrc", "FR", 15, date(2026, 7, 9))
    # product / market / <day>_<res>min.csv
    assert path.parent == tmp_path / "dayahead-mrc" / "FR"
    assert path.name == "2026-07-09_15min.csv"


def test_is_settled():
    today = date(2026, 7, 9)
    assert is_settled(date(2026, 7, 6), today) is True
    assert is_settled(date(2026, 7, 8), today) is False


def test_write_wide_layout_and_idempotency(tmp_path):
    dd = date(2026, 7, 9)
    assert write_partition(tmp_path, "dayahead-mrc", "FR", 15, dd, _records()) == "written"
    path = partition_path(tmp_path, "dayahead-mrc", "FR", 15, dd)

    df = pd.read_csv(path)
    # One row per period (wide), EPEX-like columns.
    assert len(df) == 2
    assert list(df.columns) == [
        "delivery_date", "market_area", "hours",
        "Buy Volume (MWh)", "Sell Volume (MWh)", "Volume (MWh)", "Price (€/MWh)",
        "period_start",
    ]
    assert df.loc[0, "hours"] == "00:00 - 00:15"
    assert df.loc[0, "Price (€/MWh)"] == 131.92

    # Re-writing identical data is a no-op (no scraped_at churn).
    assert write_partition(tmp_path, "dayahead-mrc", "FR", 15, dd, _records()) == "unchanged"


def test_write_empty(tmp_path):
    assert write_partition(tmp_path, "s", "FR", 15, date(2026, 7, 9), []) == "empty"
