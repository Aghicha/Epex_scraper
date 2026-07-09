from datetime import date
from pathlib import Path

from epex_scraper.parser import _clean_number, parse_market_results

FIXTURES = Path(__file__).parent / "fixtures"


def _meta():
    return {
        "market_area": "DE-LU",
        "modality": "Auction",
        "sub_modality": "DayAhead",
        "auction": "MRC",
        "product": 60,
        "delivery_date": date(2026, 7, 9),
        "trading_date": "2026-07-08",
        "source_url": "https://example/test",
        "scraped_at": "2026-07-09T00:00:00+00:00",
    }


def test_clean_number_variants():
    assert _clean_number("1,234.5") == 1234.5
    assert _clean_number("-5.20") == -5.2
    assert _clean_number("45.67") == 45.67
    assert _clean_number("-") is None
    assert _clean_number("") is None
    assert _clean_number(None) is None


def test_parse_dayahead_table():
    html = (FIXTURES / "dayahead_sample.html").read_text(encoding="utf-8")
    records = parse_market_results(html, _meta())

    # 3 populated periods x 4 metrics = 12 (4th period is all "-", skipped).
    assert len(records) == 12

    first = records[0]
    assert first["market_area"] == "DE-LU"
    assert first["period_index"] == 0
    assert first["period_label"] == "00 - 01"
    assert first["period_start"] == "2026-07-09T00:00:00"

    prices = {r["period_index"]: r["value"] for r in records if r["metric"] == "price"}
    assert prices[0] == 45.67
    assert prices[2] == -5.20  # negative prices preserved

    # Units and metric names are extracted from the headers.
    metrics = {r["metric"] for r in records}
    assert {"buy_volume", "sell_volume", "volume", "price"} <= metrics
    price_rec = next(r for r in records if r["metric"] == "price")
    assert price_rec["unit"] in ("€/MWh", "€/MWh")


def test_parse_no_table_returns_empty():
    assert parse_market_results("<html><body>No data</body></html>", _meta()) == []
