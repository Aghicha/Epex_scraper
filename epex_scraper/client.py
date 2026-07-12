"""HTTP client for the EPEX market-results endpoint."""

from __future__ import annotations

import logging
import time
from datetime import date

import requests

from . import config
from .config import QuerySpec

logger = logging.getLogger(__name__)


class AccessForbidden(Exception):
    """Raised when EPEX responds 403 (bot / WAF block).

    Retrying does not help, so it is surfaced distinctly from transient
    network errors and never retried.
    """


def build_params(spec: QuerySpec, market_area: str, delivery_date: date,
                 product: int) -> dict[str, str]:
    """Build the query-string parameters for a single market-results request.

    Only the parameters an instrument actually uses are sent: continuous has no
    ``sub_modality`` or ``auction`` (sending ``sub_modality`` makes EPEX return
    a "no data" page), and the auction code is omitted when empty.
    """
    params: dict[str, str] = {
        "market_area": market_area,
        "modality": spec.modality,
        "product": str(product),
        "data_mode": "table",
        "delivery_date": delivery_date.isoformat(),
    }
    if spec.sub_modality:
        params["sub_modality"] = spec.sub_modality
    if spec.auction:
        params["auction"] = spec.auction
    return params


def _browser_headers() -> dict[str, str]:
    """Headers that make requests look like a real Chrome navigation.

    A browser User-Agent avoids the WAF 403 that non-browser clients get.
    We deliberately keep the set minimal: sending the full Sec-Fetch / UA-hint
    navigation headers, or warming up a session cookie, makes EPEX return a
    475 KB JavaScript shell whose table is loaded by a later AJAX call instead
    of the server-rendered page that actually contains the results table.
    """
    return {
        "User-Agent": config.USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # Only advertise encodings requests can decode without extra packages.
        # (Including "br" makes EPEX send brotli, which requests can't inflate
        # unless the brotli package is present — yielding garbled, table-less
        # text.)
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def make_session() -> requests.Session:
    """Create a browser-like session.

    No landing-page "warm-up": a session cookie causes EPEX to serve the
    table-less JS shell. Honours ``HTTP(S)_PROXY`` environment variables
    automatically when no :class:`ProxyRotator` pool is configured (useful
    for a single proxy, e.g. if EPEX blocks datacenter IPs).
    """
    session = requests.Session()
    session.headers.update(_browser_headers())
    return session


class ProxyRotator:
    """Round-robins through a pool of proxy URLs, one per request.

    Spreads requests across many egress IPs so no single one accumulates
    enough traffic to trip EPEX's per-IP rate limit — a stronger fix than
    just waiting, since waiting can't help an IP that's genuinely capped.
    With an empty pool (the default), ``next()`` always returns ``None`` and
    callers fall back to whatever ``HTTP(S)_PROXY`` environment variables (or
    no proxy) ``requests`` already uses.
    """

    def __init__(self, proxy_urls: list[str] | None = None):
        self._urls = list(config.EPEX_PROXIES if proxy_urls is None else proxy_urls)
        self._i = 0

    def __len__(self) -> int:
        return len(self._urls)

    def next(self) -> dict[str, str] | None:
        if not self._urls:
            return None
        url = self._urls[self._i % len(self._urls)]
        self._i += 1
        return {"http": url, "https": url}


class ThrottledResponse(Exception):
    """A 200 response that is neither a results page nor a real 'no data' page.

    EPEX intermittently returns a tiny throttle page or a table-less JS shell
    under load; these get a couple of quick retries (see
    ``config.THROTTLE_RETRIES``) here, then are surfaced to the caller — the
    pacer decides whether a longer wait-and-retry of the whole combo is
    worthwhile, so this layer must not itself spend tens of seconds on it.
    """


def is_valid_page(html: str) -> bool:
    """True if the page is a usable result (has the table *or* says 'no data').

    A throttle page / JS shell contains neither the server-rendered results
    markup nor the explicit no-data message, so it is not valid.
    """
    return (
        "js-table-values" in html
        or "js-table-times" in html
        or "no-data" in html
    )


def fetch(session: requests.Session, spec: QuerySpec, market_area: str,
          delivery_date: date, product: int,
          proxies: dict[str, str] | None = None) -> str | None:
    """Fetch one market-results page.

    Returns the HTML body (results *or* a genuine no-data page), ``None`` if the
    combination does not exist (HTTP 404), and raises :class:`AccessForbidden`
    on 403. Network errors (429 / 5xx / timeout) are retried with exponential
    backoff; throttle/shell responses get a couple of quick, fixed-pause
    retries (see ``config.THROTTLE_RETRIES``/``THROTTLE_PAUSE``) since a
    sustained rate limit won't clear from backoff alone. The final failure is
    raised either way.

    ``proxies`` (typically from a :class:`ProxyRotator`) overrides the
    session/environment proxy for just this call, e.g. ``{"http": url,
    "https": url}``. ``None`` (the default) falls back to the session's own
    proxy configuration (env vars or none).
    """
    params = build_params(spec, market_area, delivery_date, product)
    # NB: do NOT send X-Requested-With here — that makes EPEX return a
    # table-less AJAX fragment. A plain navigation GET (with a Referer) returns
    # the full page with the results table embedded.
    headers = {"Referer": config.BASE_URL}
    last_exc: Exception | None = None
    for attempt in range(1, config.REQUEST_RETRIES + 1):
        try:
            resp = session.get(
                config.BASE_URL, params=params, headers=headers,
                timeout=config.REQUEST_TIMEOUT, proxies=proxies,
            )
            if resp.status_code == 404:
                logger.debug("404 (no such combination) for %s", resp.url)
                return None
            if resp.status_code == 403:
                # Bot/WAF block — retrying is futile and only hammers the WAF.
                raise AccessForbidden(resp.url)
            resp.raise_for_status()
            if not is_valid_page(resp.text):
                raise ThrottledResponse(
                    f"throttle/shell response ({len(resp.text)} bytes) for {resp.url}"
                )
            return resp.text
        except AccessForbidden:
            raise
        except ThrottledResponse as exc:
            last_exc = exc
            if attempt < config.THROTTLE_RETRIES:
                logger.warning(
                    "throttled (attempt %d/%d): %s — retrying in %.0fs",
                    attempt, config.THROTTLE_RETRIES, exc, config.THROTTLE_PAUSE,
                )
                time.sleep(config.THROTTLE_PAUSE)
            else:
                logger.warning(
                    "throttled (attempt %d/%d): %s — giving up on this "
                    "request; the pacer decides whether to wait and retry "
                    "the whole combo",
                    attempt, config.THROTTLE_RETRIES, exc,
                )
                raise
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < config.REQUEST_RETRIES:
                backoff = min(2 ** attempt, 30)
                logger.warning(
                    "request failed (attempt %d/%d): %s — retrying in %ds",
                    attempt, config.REQUEST_RETRIES, exc, backoff,
                )
                time.sleep(backoff)
            else:
                logger.warning(
                    "request failed (attempt %d/%d): %s — giving up",
                    attempt, config.REQUEST_RETRIES, exc,
                )
    assert last_exc is not None
    raise last_exc
