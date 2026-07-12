"""Static configuration describing *what* to scrape.

EPEX exposes its public market results at::

    https://www.epexspot.com/en/market-results?market_area=...&modality=...&...

The available filter values are **context-dependent** (the market areas and
auction codes offered depend on the chosen modality), and were read directly
from the site's own filter form. A single request is scoped to one
``(market_area, modality[, sub_modality][, auction], product, delivery_date)``
tuple and returns an HTML page with a results table.

To "capture all products, countries and instruments" we enumerate, per
instrument (:class:`QuerySpec`), only the market areas and products that
instrument actually offers.  Any combination without data still returns a
"no data" page and is skipped, so the lists can stay broad.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

BASE_URL = "https://www.epexspot.com/en/market-results"

# ---------------------------------------------------------------------------
# Market-area groups ("countries" / bidding zones), per the site's filters.
# ---------------------------------------------------------------------------
# Single Day-Ahead Coupling zones (modality=Auction, sub_modality=DayAhead/MRC
# and the intraday auctions IDA1/2/3).
SDAC_ZONES: list[str] = [
    "AT", "BE", "DE-LU", "DK1", "DK2", "FI", "FR", "NL",
    "NO1", "NO2", "NO3", "NO4", "NO5", "PL", "SE1", "SE2", "SE3", "SE4",
]

# Continuous intraday (SIDC) zones — note "DE" (not "DE-LU") plus CH/EE/LT/LV.
CONTINUOUS_ZONES: list[str] = [
    "AT", "BE", "CH", "DE", "DK1", "DK2", "EE", "FI", "FR", "LT", "LV", "NL",
    "NO1", "NO2", "NO3", "NO4", "NO5", "PL", "SE1", "SE2", "SE3", "SE4",
]

# Default contract resolutions to try (minutes). Per-spec overrides below.
PRODUCTS: list[int] = [60, 15]


@dataclass(frozen=True)
class QuerySpec:
    """One tradable instrument variant on the market-results page.

    EPEX needs a different ``auction`` filter code per market area even
    within the same conceptual instrument (e.g. day-ahead is ``MRC`` for the
    SDAC-coupled zones but ``GB``/``CH`` for their standalone auctions), so
    each variant is still its own ``QuerySpec`` for fetching. ``slug`` is the
    *output* grouping instead: every variant of the same instrument shares
    one slug so all of its market areas land under one ``data/<slug>/`` tree
    (see :mod:`epex_scraper.storage`), rather than being split across
    per-market-area folders that all mean "day-ahead" or "IDA1" underneath.

    Attributes:
        modality: ``Auction`` or ``Continuous``.
        sub_modality: ``DayAhead`` / ``Intraday`` for auctions, or ``None`` for
            continuous (sending it makes EPEX return a "no data" page).
        auction: Auction / coupling code (``MRC``, ``GB``, ``CH``, ``IDA1`` …).
            Empty string for continuous (no auction).
        slug: Output grouping — filesystem-safe folder name shared by every
            variant of the same instrument (``day-ahead``, ``intraday-ida1``,
            ``continuous``, …).
        market_areas: Market areas this variant offers.
        products: Contract resolutions to request for this variant.
    """

    modality: str
    sub_modality: str | None
    auction: str
    slug: str
    market_areas: list[str]
    products: list[int]


# The instruments to enumerate. Codes/areas taken from the live filter form.
# Grouped by output slug: every variant below that shares a slug writes into
# the same data/<slug>/ tree, split further only by market area (which never
# collides across a group's variants — GB/CH are never also SDAC zones).
QUERY_SPECS: list[QuerySpec] = [
    # --- Day-ahead auctions: SDAC coupling + standalone GB/CH auctions -----
    QuerySpec("Auction", "DayAhead", "MRC", "day-ahead", SDAC_ZONES, [60, 15]),
    QuerySpec("Auction", "DayAhead", "GB", "day-ahead", ["GB"], [60]),
    QuerySpec("Auction", "DayAhead", "30-call-GB", "day-ahead", ["GB"], [30]),
    QuerySpec("Auction", "DayAhead", "CH", "day-ahead", ["CH"], [60, 15]),
    # --- Intraday auction 1 (IDA1, quarter-hourly) -------------------------
    QuerySpec("Auction", "Intraday", "IDA1", "intraday-ida1", SDAC_ZONES, [15]),
    QuerySpec("Auction", "Intraday", "CH-IDA1", "intraday-ida1", ["CH"], [15]),
    QuerySpec("Auction", "Intraday", "GB-IDA1", "intraday-ida1", ["GB"], [60]),
    # --- Intraday auction 2 (IDA2, quarter-hourly) -------------------------
    QuerySpec("Auction", "Intraday", "IDA2", "intraday-ida2", SDAC_ZONES, [15]),
    QuerySpec("Auction", "Intraday", "CH-IDA2", "intraday-ida2", ["CH"], [15]),
    QuerySpec("Auction", "Intraday", "GB-IDA2", "intraday-ida2", ["GB"], [60]),
    # --- Intraday auction 3 (IDA3, quarter-hourly, SDAC only) --------------
    QuerySpec("Auction", "Intraday", "IDA3", "intraday-ida3", SDAC_ZONES, [15]),
    # --- Continuous intraday (SIDC) — no sub_modality, no auction ----------
    QuerySpec("Continuous", None, "", "continuous", CONTINUOUS_ZONES, [60, 30, 15]),
]

# All market areas across instruments (for CLI filtering / display).
MARKET_AREAS: list[str] = sorted(
    {a for spec in QUERY_SPECS for a in spec.market_areas}
)


# ---------------------------------------------------------------------------
# HTTP behaviour
# ---------------------------------------------------------------------------
# A browser User-Agent avoids the WAF 403 that non-browser clients get. Keep it
# roughly current.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30  # seconds
REQUEST_RETRIES = 4
# Throttle/shell responses get their own, much smaller retry budget than
# network errors: a sustained per-IP limit doesn't clear in seconds, so
# spending REQUEST_RETRIES' worth of growing backoff (tens of seconds) on it
# just delays the pacer, which is the layer that actually decides whether a
# longer wait-and-retry of the whole combo is worthwhile. This only smooths a
# one-off blip.
THROTTLE_RETRIES = 2
THROTTLE_PAUSE = 3.0  # seconds between those quick attempts

# Optional pool of proxy URLs to round-robin through, one per request, so no
# single egress IP ever sees enough traffic to trip EPEX's per-IP rate limit.
# Comma-separated, e.g. "http://user:pass@host1:port,http://user:pass@host2:port".
# Empty by default: requests then falls back to its normal HTTP(S)_PROXY env
# var behaviour (one static proxy, or a direct connection).
EPEX_PROXIES: list[str] = [
    p.strip() for p in os.environ.get("EPEX_PROXIES", "").split(",") if p.strip()
]
# Seconds to sleep between requests. Be a good citizen — EPEX is a shared,
# public resource and its terms restrict usage to internal purposes — and it
# throttles bursts, returning tiny placeholder pages, so don't go too fast.
REQUEST_SLEEP = 2.0
