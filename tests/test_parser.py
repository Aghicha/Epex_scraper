from datetime import date
from pathlib import Path

from epex_scraper.parser import _clean_number, parse_market_results

FIXTURES = Path(__file__).parent / "fixtures"


def _meta(**overrides):
    meta = {
        "market_area": "DE-LU", "modality": "Auction", "sub_modality": "DayAhead",
        "auction": "MRC", "product": 60, "delivery_date": date(2026, 7, 8),
        "trading_date": "2026-07-07", "source_url": "https://example/test",
        "scraped_at": "2026-07-08T00:00:00+00:00",
    }
    meta.update(overrides)
    return meta


def test_clean_number_variants():
    assert _clean_number("1,234.5") == 1234.5
    assert _clean_number("25,670.2") == 25670.2
    assert _clean_number("-5.20") == -5.2
    assert _clean_number("114.92") == 114.92
    assert _clean_number("-") is None
    assert _clean_number("") is None
    assert _clean_number(None) is None


def test_parses_real_dom_structure():
    html = (FIXTURES / "dayahead_sample.html").read_text(encoding="utf-8")
    records = parse_market_results(html, _meta())

    # periods 0 and 1 have 4 metrics; period 2 has only price (others are "-").
    assert len(records) == 9

    # Hours come from the <ul>, not integer indices, and the Baseload/Peakload
    # summary block is ignored.
    labels = [r["period_label"] for r in records]
    assert "00 - 01" in labels
    assert "Baseload" not in labels and "Peakload" not in labels

    first = next(r for r in records if r["period_label"] == "00 - 01")
    assert first["period_start"] == "2026-07-08T00:00:00"

    p0 = {r["metric"]: r["value"] for r in records if r["period_index"] == 0}
    assert p0 == {"buy_volume": 25670.2, "sell_volume": 28398.7,
                  "volume": 28398.7, "price": 114.92}

    price = next(r for r in records if r["metric"] == "price")
    assert price["unit"] == "€/MWh"


def test_continuous_resolution_filtering():
    html = (FIXTURES / "continuous_sample.html").read_text(encoding="utf-8")
    # The page embeds all resolutions; the parser keeps only the requested one.
    counts = {}
    for product in (60, 30, 15):
        meta = {**_meta(), "modality": "Continuous", "sub_modality": None,
                "auction": "", "product": product}
        recs = parse_market_results(html, meta)
        counts[product] = len({r["period_index"] for r in recs})
    assert counts == {60: 1, 30: 2, 15: 4}

    # 60min keeps the hourly row; metrics include the continuous-only columns.
    meta = {**_meta(), "modality": "Continuous", "sub_modality": None,
            "auction": "", "product": 60}
    recs = parse_market_results(html, meta)
    assert {r["period_label"] for r in recs} == {"00 - 01"}
    assert {"low", "high", "buy_volume"} == {r["metric"] for r in recs}


def test_page_date_mismatch_is_discarded():
    # EPEX can silently fall back to a nearby day's page for delivery dates
    # outside its published window; the page heading still says which day it
    # actually rendered ("08 July 2026"), so a request for a different day
    # must be rejected rather than mislabeled with the requested date.
    html = (FIXTURES / "dayahead_sample.html").read_text(encoding="utf-8")
    records = parse_market_results(html, _meta(delivery_date=date(2026, 7, 12)))
    assert records == []


def test_no_data_page_returns_empty():
    html = '<div class="no-data-section"><p class="no-data-text">No data</p></div>'
    assert parse_market_results(html, _meta()) == []


def test_empty_page_returns_empty():
    assert parse_market_results("<html><body>nothing</body></html>", _meta()) == []
