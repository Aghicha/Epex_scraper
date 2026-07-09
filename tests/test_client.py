from datetime import date

import pytest
import requests

from epex_scraper import client
from epex_scraper.config import QUERY_SPECS

SPEC = QUERY_SPECS[0]  # dayahead-mrc
VALID = '<div class="js-table-values"><table></table></div>'
NODATA = '<div class="no-data-section">No data</div>'
THROTTLE = '<html><body>rate limited</body></html>'


class FakeResponse:
    def __init__(self, status_code, text=VALID, url="https://epex/test"):
        self.status_code = status_code
        self.text = text
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
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


def test_is_valid_page():
    assert client.is_valid_page(VALID)
    assert client.is_valid_page(NODATA)
    assert client.is_valid_page('<div class="js-table-times"></div>')
    assert not client.is_valid_page(THROTTLE)


def test_valid_page_returned():
    session = FakeSession([FakeResponse(200, VALID)])
    assert _fetch(session) == VALID
    assert session.calls == 1


def test_no_data_page_is_accepted():
    session = FakeSession([FakeResponse(200, NODATA)])
    assert _fetch(session) == NODATA  # parser will yield [] for it


def test_403_raises_forbidden_and_does_not_retry():
    session = FakeSession([FakeResponse(403)])
    with pytest.raises(client.AccessForbidden):
        _fetch(session)
    assert session.calls == 1


def test_404_returns_none():
    session = FakeSession([FakeResponse(404)])
    assert _fetch(session) is None


def test_throttle_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
    session = FakeSession([FakeResponse(200, THROTTLE), FakeResponse(200, VALID)])
    assert _fetch(session) == VALID
    assert session.calls == 2


def test_persistent_throttle_raises(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
    session = FakeSession([FakeResponse(200, THROTTLE)] * client.config.REQUEST_RETRIES)
    with pytest.raises(client.ThrottledResponse):
        _fetch(session)


def test_transient_5xx_is_retried(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
    session = FakeSession([requests.ConnectionError("boom"), FakeResponse(200, VALID)])
    assert _fetch(session) == VALID
    assert session.calls == 2
