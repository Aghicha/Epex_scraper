"""HTTP client for the EPEX market-results endpoint."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

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
    """Build the query-string parameters for a single market-results request."""
    params: dict[str, str] = {
        "market_area": market_area,
        "auction": spec.auction,
        "modality": spec.modality,
        "sub_modality": spec.sub_modality,
        "product": str(product),
        "data_mode": "table",
        "delivery_date": delivery_date.isoformat(),
        # The remaining params exist in the canonical URL; sending them empty
        # keeps the request shape close to what a browser sends.
        "underlying_year": "",
        "technology": "",
        "period": "",
        "production_period": "",
    }
    if spec.trading_offset_days is not None:
        trading = delivery_date - timedelta(days=spec.trading_offset_days)
        params["trading_date"] = trading.isoformat()
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
    automatically (useful if EPEX blocks datacenter IPs and you need to route
    through a residential proxy).
    """
    session = requests.Session()
    session.headers.update(_browser_headers())
    return session


class ThrottledResponse(Exception):
    """A 200 response that is neither a results page nor a real 'no data' page.

    EPEX intermittently returns a tiny throttle page or a table-less JS shell
    under load; these are retried with a longer backoff.
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
          delivery_date: date, product: int) -> str | None:
    """Fetch one market-results page.

    Returns the HTML body (results *or* a genuine no-data page), ``None`` if the
    combination does not exist (HTTP 404), and raises :class:`AccessForbidden`
    on 403. Network errors (429 / 5xx / timeout) and throttle/shell responses
    are retried with exponential backoff; the final failure is raised.
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
                timeout=config.REQUEST_TIMEOUT,
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
        except (requests.RequestException, ThrottledResponse) as exc:
            last_exc = exc
            # Throttle/shell pages need a longer pause to clear than a network
            # blip does.
            base = 4 if isinstance(exc, ThrottledResponse) else 2
            if attempt < config.REQUEST_RETRIES:
                backoff = base ** attempt
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
