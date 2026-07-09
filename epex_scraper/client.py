"""HTTP client for the EPEX market-results endpoint."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import requests

from . import config
from .config import QuerySpec

logger = logging.getLogger(__name__)


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


def make_session() -> requests.Session:
    """Create a configured :class:`requests.Session`."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-GB,en;q=0.9",
        }
    )
    return session


def fetch(session: requests.Session, spec: QuerySpec, market_area: str,
          delivery_date: date, product: int) -> str | None:
    """Fetch one market-results page.

    Returns the HTML body, or ``None`` if the combination does not exist
    (HTTP 404) so the caller can skip it silently.  Transient errors are
    retried with exponential backoff; the final failure is raised.
    """
    params = build_params(spec, market_area, delivery_date, product)
    last_exc: Exception | None = None
    for attempt in range(1, config.REQUEST_RETRIES + 1):
        try:
            resp = session.get(
                config.BASE_URL, params=params, timeout=config.REQUEST_TIMEOUT
            )
            if resp.status_code == 404:
                logger.debug("404 (no such combination) for %s", resp.url)
                return None
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:  # network / 5xx / timeout
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
