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

    EPEX sits behind a WAF that rejects non-browser clients (custom
    User-Agents, missing Sec-Fetch/UA hints) with 403.
    """
    return {
        "User-Agent": config.USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24", "Google Chrome";v="125"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Referer": config.BASE_URL,
    }


def make_session() -> requests.Session:
    """Create a browser-like session and warm it up to collect cookies.

    Loading the market-results landing page first lets the WAF set any
    cookies it expects on subsequent data requests. Honours ``HTTP(S)_PROXY``
    environment variables automatically (useful if EPEX blocks datacenter IPs
    and you need to route through a residential proxy).
    """
    session = requests.Session()
    session.headers.update(_browser_headers())
    try:
        warm = session.get(config.BASE_URL, timeout=config.REQUEST_TIMEOUT)
        logger.info("session warm-up: GET %s -> %s", config.BASE_URL, warm.status_code)
    except requests.RequestException as exc:
        logger.warning("session warm-up failed: %s", exc)
    return session


def fetch(session: requests.Session, spec: QuerySpec, market_area: str,
          delivery_date: date, product: int) -> str | None:
    """Fetch one market-results page.

    Returns the HTML body, ``None`` if the combination does not exist
    (HTTP 404), and raises :class:`AccessForbidden` on 403 (no retry).
    Transient errors (429 / 5xx / network) are retried with exponential
    backoff; the final failure is raised.
    """
    params = build_params(spec, market_area, delivery_date, product)
    # A same-page Referer for the AJAX-style data request.
    headers = {"Referer": config.BASE_URL, "X-Requested-With": "XMLHttpRequest"}
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
            return resp.text
        except AccessForbidden:
            raise
        except requests.RequestException as exc:  # network / 5xx / 429 / timeout
            last_exc = exc
            if attempt < config.REQUEST_RETRIES:
                backoff = 2 ** attempt
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
