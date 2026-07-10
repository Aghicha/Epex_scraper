import argparse

from epex_scraper import scrape


def _args(**kw):
    base = dict(burst=4, cooldown=30.0, throttle_wait=60.0, throttle_retries=3)
    base.update(kw)
    return argparse.Namespace(**base)


def test_pacer_cools_down_every_burst(monkeypatch):
    sleeps = []
    monkeypatch.setattr(scrape.time, "sleep", lambda s: sleeps.append(s))
    pacer = scrape._Pacer(_args(burst=3, cooldown=30.0))
    for _ in range(7):
        pacer.run(lambda: "written")
    # cooldown triggers before requests 4 and 7 → two 30s pauses.
    assert sleeps == [30.0, 30.0]


def test_pacer_waits_and_retries_on_throttle(monkeypatch):
    sleeps = []
    monkeypatch.setattr(scrape.time, "sleep", lambda s: sleeps.append(s))
    outcomes = iter(["throttled", "throttled", "written"])
    pacer = scrape._Pacer(_args(burst=0, throttle_wait=60.0, throttle_retries=3))
    result = pacer.run(lambda: next(outcomes))
    assert result == "written"           # recovered after waiting
    assert sleeps == [60.0, 60.0]        # two throttle waits, no burst cooldown


def test_pacer_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(scrape.time, "sleep", lambda s: None)
    pacer = scrape._Pacer(_args(burst=0, throttle_retries=2))
    result = pacer.run(lambda: "throttled")
    assert result == "throttled"         # still throttled → left for next run
