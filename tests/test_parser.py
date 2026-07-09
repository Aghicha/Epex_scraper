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
        "product": 15,
        "delivery_date": date(2026, 7, 9),
        "trading_date": "2026-07-08",
        "source_url": "https://example/test",
        "scraped_at": "2026-07-09T00:00:00+00:00",
    }


def test_clean_number_variants():
    assert _clean_number("1,234.5") == 1234.5
    assert _clean_number("-5.20") == -5.2
    assert _clean_number("131.92") == 131.92
    assert _clean_number("-") is None
    assert _clean_number("") is None
    assert _clean_number(None) is None


def test_parses_correct_table_and_hours():
    html = (FIXTURES / "dayahead_sample.html").read_text(encoding="utf-8")
    records = parse_market_results(html, _meta())

    # 4 quarter-hour periods with data x 4 metrics = 16.
    # The 'Baseload' aggregate row and the all-"-" 01:00 row are excluded, and
    # the decoy nav table (no time column) is ignored.
    assert len(records) == 16

    # Hours are extracted as clock ranges, not integer indices.
    labels = sorted({r["period_label"] for r in records})
    assert labels[0] == "00:00 - 00:15"
    assert "Baseload" not in labels

    first = next(r for r in records if r["period_label"] == "00:00 - 00:15")
    assert first["period_start"] == "2026-07-09T00:00:00"

    prices = {r["period_label"]: r["value"] for r in records if r["metric"] == "price"}
    assert prices["00:00 - 00:15"] == 131.92
    assert prices["00:15 - 00:30"] == 133.53

    metrics = {r["metric"] for r in records}
    assert {"buy_volume", "sell_volume", "volume", "price"} == metrics
    price_rec = next(r for r in records if r["metric"] == "price")
    assert price_rec["unit"] == "€/MWh"


def test_parse_no_table_returns_empty():
    assert parse_market_results("<html><body>No data</body></html>", _meta()) == []


def test_ignores_table_without_time_column():
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    assert parse_market_results(html, _meta()) == []
