from datetime import date

from tradingsurv.ingestion.market_prices.epex_reader import read_actual_day_ahead_prices


def _write_sample(tmp_path, market_area="FR"):
    day_dir = tmp_path / "day-ahead" / market_area
    day_dir.mkdir(parents=True)
    (day_dir / "2026-07-09_60min.csv").write_text(
        "delivery_date,market_area,hours,Buy Volume (MWh),Sell Volume (MWh),"
        "Volume (MWh),Price (€/MWh),period_start\n"
        "2026-07-09,FR,00 - 01,1500.0,1200.0,1500.0,80.5,2026-07-09T00:00:00\n"
        "2026-07-09,FR,01 - 02,1400.0,1100.0,1400.0,75.2,2026-07-09T01:00:00\n"
    )


def test_reads_actual_prices_keyed_by_period_start(tmp_path):
    _write_sample(tmp_path)
    prices = read_actual_day_ahead_prices(tmp_path, "FR", date(2026, 7, 9), resolution=60)
    assert len(prices) == 2
    from datetime import datetime

    assert prices[datetime(2026, 7, 9, 0, 0)] == 80.5
    assert prices[datetime(2026, 7, 9, 1, 0)] == 75.2


def test_missing_file_returns_empty_dict_not_error(tmp_path):
    prices = read_actual_day_ahead_prices(tmp_path, "FR", date(2026, 7, 9), resolution=60)
    assert prices == {}


def test_reads_real_committed_scraper_archive():
    """Sanity check against the actual epex_scraper archive already in this repo."""
    from pathlib import Path

    data_root = Path(__file__).resolve().parent.parent / "data"
    prices = read_actual_day_ahead_prices(data_root, "AT", date(2026, 7, 24), resolution=60)
    assert len(prices) > 0
    assert all(isinstance(v, float) for v in prices.values())
