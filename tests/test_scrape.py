import argparse
from collections import Counter
from datetime import date
from pathlib import Path

from epex_scraper import scrape, storage
from epex_scraper.config import QuerySpec


def _args(tmp_path, **overrides):
    base = dict(
        data_dir=str(tmp_path), days_back=1, days_forward=1, settle_days=2,
        market_areas=["AT", "BE"], products=[60], specs=["day-ahead"],
        sleep=0, burst=0, cooldown=0, throttle_wait=0, throttle_retries=0,
        max_forbidden=20, user_agent=None, save_raw=None,
        today=date(2026, 7, 9), log_level="INFO", proxies=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _run(monkeypatch, args, outcomes):
    calls = []

    def fake_scrape_one(session, spec, market_area, product, delivery_date,
                        data_dir, raw_dir, sleep_s, proxy_pool):
        calls.append((spec.slug, market_area, product, delivery_date))
        return outcomes[len(calls) - 1] if len(calls) <= len(outcomes) else outcomes[-1]

    monkeypatch.setattr(scrape, "_scrape_one", fake_scrape_one)
    monkeypatch.setattr(scrape.time, "sleep", lambda s: None)
    rc = scrape.run(args)
    return rc, calls


def test_never_fetched_combos_are_scraped_before_refresh(monkeypatch, tmp_path):
    # Seed an already-stored, unsettled file for AT/2026-07-09 (today). If the
    # run retreads it first, the limited "budget" below never reaches BE.
    path = storage.partition_path(tmp_path, "day-ahead", "AT", 60, date(2026, 7, 9))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("delivery_date,market_area,hours\n2026-07-09,AT,00-01\n")

    args = _args(tmp_path)
    rc, calls = _run(monkeypatch, args, outcomes=["written"] * 20)

    assert rc == 0
    # The pre-existing AT/2026-07-09 combo must be scraped *after* every
    # never-fetched combo, not first.
    seeded_index = calls.index(("day-ahead", "AT", 60, date(2026, 7, 9)))
    assert seeded_index == len(calls) - 1
    assert calls[0] != ("day-ahead", "AT", 60, date(2026, 7, 9))


def test_never_fetched_combos_are_interleaved_across_specs(monkeypatch, tmp_path):
    # day-ahead alone offers many area/product/date combos; grouped instead of
    # interleaved, a budget-limited run would exhaust it before ever touching
    # the other two instruments below (this previously left data/day-ahead/ as
    # the only populated folder, no matter how many runs executed).
    day_ahead = QuerySpec("Auction", "DayAhead", "MRC", "day-ahead",
                         ["AT", "BE", "FR"], [60])
    intraday = QuerySpec("Auction", "Intraday", "IDA1", "intraday-ida1",
                        ["AT", "BE", "FR"], [15])
    continuous = QuerySpec("Continuous", None, "", "continuous",
                           ["AT", "BE", "FR"], [60])

    new_tasks, refresh_tasks = scrape._build_tasks(
        specs=[day_ahead, intraday, continuous],
        area_filter=None, product_filter=None,
        delivery_dates=[date(2026, 7, 9)],
        data_dir=tmp_path, today=date(2026, 7, 9), settle_days=2,
        stats=Counter(),
    )

    assert not refresh_tasks
    slugs_in_order = [task[0].slug for task in new_tasks]
    # Round-robin: the first instrument-cycle touches all three specs before
    # any spec repeats.
    assert slugs_in_order[:3] == ["day-ahead", "intraday-ida1", "continuous"]


def test_throttled_combo_is_retried_until_it_succeeds_not_skipped(monkeypatch, tmp_path):
    # First combo (AT, 2026-07-08) throttles twice before succeeding; the run
    # must keep retrying *that* combo rather than moving on to AT/07-09 (or
    # anywhere else) while it's stuck.
    args = _args(tmp_path)
    outcomes = ["throttled", "throttled"] + ["written"] * 6
    rc, calls = _run(monkeypatch, args, outcomes)

    assert rc == 0
    combo = ("day-ahead", "AT", 60, date(2026, 7, 8))
    assert calls[0] == calls[1] == calls[2] == combo
    # Only advances to the next combo once the stuck one finally succeeds.
    assert calls[3] == ("day-ahead", "AT", 60, date(2026, 7, 9))
    assert len(calls) == 8  # 3 attempts on the stuck combo + 5 more combos


def test_persistent_forbidden_fails_run(monkeypatch, tmp_path):
    args = _args(tmp_path, max_forbidden=3)
    rc, calls = _run(monkeypatch, args, outcomes=["forbidden"] * 3)

    assert rc == 2
    assert len(calls) == 3
