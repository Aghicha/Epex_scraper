from datetime import date

from epex_scraper.storage import is_settled, partition_path, write_partition


def _records():
    return [
        {
            "market_area": "FR", "modality": "Auction", "sub_modality": "DayAhead",
            "auction": "MRC", "product": 60, "delivery_date": date(2026, 7, 9),
            "trading_date": "2026-07-08", "period_index": 0, "period_label": "00 - 01",
            "period_start": "2026-07-09T00:00:00", "metric": "price", "unit": "€/MWh",
            "value": 45.67, "value_raw": "45.67", "source_url": "u",
            "scraped_at": "2026-07-09T00:00:00+00:00",
        }
    ]


def test_is_settled():
    today = date(2026, 7, 9)
    assert is_settled(date(2026, 7, 6), today) is True
    assert is_settled(date(2026, 7, 8), today) is False
    assert is_settled(date(2026, 7, 9), today) is False


def test_write_is_idempotent(tmp_path):
    dd = date(2026, 7, 9)
    first = write_partition(tmp_path, "dayahead-mrc", "FR", 60, dd, _records())
    assert first == "written"
    path = partition_path(tmp_path, "dayahead-mrc", "FR", 60, dd)
    assert path.exists()

    # Re-writing identical data (new scraped_at) must not rewrite the file.
    recs = _records()
    recs[0]["scraped_at"] = "2026-07-09T12:00:00+00:00"
    second = write_partition(tmp_path, "dayahead-mrc", "FR", 60, dd, recs)
    assert second == "unchanged"

    # Changed data does get written.
    recs2 = _records()
    recs2[0]["value"] = 50.0
    recs2[0]["value_raw"] = "50.00"
    third = write_partition(tmp_path, "dayahead-mrc", "FR", 60, dd, recs2)
    assert third == "written"


def test_write_empty():
    assert write_partition("/nonexistent", "s", "FR", 60, date(2026, 7, 9), []) == "empty"
