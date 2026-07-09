from datetime import date

import pytest
import requests

from epex_scraper import client
from epex_scraper.config import QUERY_SPECS


SPEC = QUERY_SPECS[0]  # dayahead-mrc


class FakeResponse:
    def __init__(self, status_code, text="<html></html>", url="https://epex/test"):
        self.status_code = status_code
        self.text = text
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    """Records calls and returns queued responses (or raises queued excs)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _fetch(session):
    return client.fetch(session, SPEC, "DE-LU", date(2026, 7, 9), 60)


def test_403_raises_forbidden_and_does_not_retry():
    session = FakeSession([FakeResponse(403)])
    with pytest.raises(client.AccessForbidden):
        _fetch(session)
    assert session.calls == 1  # no retry on a bot/WAF block


def test_404_returns_none():
    session = FakeSession([FakeResponse(404)])
    assert _fetch(session) is None
    assert session.calls == 1


def test_200_returns_body():
    session = FakeSession([FakeResponse(200, text="<html>ok</html>")])
    assert _fetch(session) == "<html>ok</html>"


def test_transient_5xx_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)  # no real backoff
    session = FakeSession([
        requests.ConnectionError("boom"),
        FakeResponse(200, text="<html>recovered</html>"),
    ])
    assert _fetch(session) == "<html>recovered</html>"
    assert session.calls == 2
