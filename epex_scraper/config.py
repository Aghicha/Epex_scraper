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
    """One tradable instrument on the market-results page.

    Attributes:
        modality: ``Auction`` or ``Continuous``.
        sub_modality: ``DayAhead`` / ``Intraday`` for auctions, or ``None`` for
            continuous (sending it makes EPEX return a "no data" page).
        auction: Auction / coupling code (``MRC``, ``GB``, ``CH``, ``IDA1`` …).
            Empty string for continuous (no auction).
        slug: Short, filesystem-safe identifier used in output paths.
        market_areas: Market areas this instrument offers.
        products: Contract resolutions to request for this instrument.
    """

    modality: str
    sub_modality: str | None
    auction: str
    slug: str
    market_areas: list[str]
    products: list[int]


# The instruments to enumerate. Codes/areas taken from the live filter form.
QUERY_SPECS: list[QuerySpec] = [
    # --- Day-ahead auctions ------------------------------------------------
    QuerySpec("Auction", "DayAhead", "MRC", "day-ahead", SDAC_ZONES, [60, 15]),
    QuerySpec("Auction", "DayAhead", "GB", "day-ahead-gb", ["GB"], [60]),
    QuerySpec("Auction", "DayAhead", "30-call-GB", "day-ahead-gb-30", ["GB"], [30]),
    QuerySpec("Auction", "DayAhead", "CH", "day-ahead-ch", ["CH"], [60, 15]),
    # --- Intraday auctions (IDA1 / IDA2 / IDA3, quarter-hourly) ------------
    QuerySpec("Auction", "Intraday", "IDA1", "intraday-ida1", SDAC_ZONES, [15]),
    QuerySpec("Auction", "Intraday", "IDA2", "intraday-ida2", SDAC_ZONES, [15]),
    QuerySpec("Auction", "Intraday", "IDA3", "intraday-ida3", SDAC_ZONES, [15]),
    QuerySpec("Auction", "Intraday", "CH-IDA1", "intraday-ch-ida1", ["CH"], [15]),
    QuerySpec("Auction", "Intraday", "CH-IDA2", "intraday-ch-ida2", ["CH"], [15]),
    QuerySpec("Auction", "Intraday", "GB-IDA1", "intraday-gb-ida1", ["GB"], [60]),
    QuerySpec("Auction", "Intraday", "GB-IDA2", "intraday-gb-ida2", ["GB"], [60]),
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
# Seconds to sleep between requests. Be a good citizen — EPEX is a shared,
# public resource and its terms restrict usage to internal purposes — and it
# throttles bursts, returning tiny placeholder pages, so don't go too fast.
REQUEST_SLEEP = 2.0
