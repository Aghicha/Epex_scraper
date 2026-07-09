"""Static configuration describing *what* to scrape.

EPEX exposes its public market results at::

    https://www.epexspot.com/en/market-results?market_area=...&modality=...&...

A single request is scoped to one
``(market_area, modality, sub_modality, auction, product, delivery_date)``
tuple and returns an HTML page containing a results table.

To "capture all products, countries and instruments" we enumerate the full
cartesian product of:

* ``MARKET_AREAS``   - the bidding / delivery zones ("countries")
* ``QUERY_SPECS``    - the trading products / instruments
  (Day-Ahead auction, Intraday auctions IDA1/2/3, continuous intraday, ...)
* ``PRODUCTS``       - the contract resolution (60 / 30 / 15 minutes)

Not every combination exists (e.g. GB has no MRC day-ahead, only GB-DAA).  The
scraper is deliberately *tolerant*: any combination that returns no table is
simply skipped, so the enumeration can stay broad without breaking runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Base endpoint for the public market results.
BASE_URL = "https://www.epexspot.com/en/market-results"

# ---------------------------------------------------------------------------
# Market areas ("countries" / bidding zones)
# ---------------------------------------------------------------------------
# Every delivery/bidding zone published on the market-results page. Invalid
# combinations for a given product are skipped automatically at runtime.
MARKET_AREAS: list[str] = [
    "AT",      # Austria
    "BE",      # Belgium
    "CH",      # Switzerland
    "DE-LU",   # Germany - Luxembourg
    "DK1",     # Denmark 1
    "DK2",     # Denmark 2
    "FI",      # Finland
    "FR",      # France
    "GB",      # Great Britain
    "NL",      # Netherlands
    "NO1",     # Norway 1
    "NO2",     # Norway 2
    "NO3",     # Norway 3
    "NO4",     # Norway 4
    "NO5",     # Norway 5
    "PL",      # Poland
    "SE1",     # Sweden 1
    "SE2",     # Sweden 2
    "SE3",     # Sweden 3
    "SE4",     # Sweden 4
]

# ---------------------------------------------------------------------------
# Contract resolution ("products" in EPEX URL terms)
# ---------------------------------------------------------------------------
# 60 = hourly, 30 = half-hourly, 15 = quarter-hourly. Not all areas trade all
# resolutions; unavailable ones return no table and are skipped.
PRODUCTS: list[int] = [60, 30, 15]


@dataclass(frozen=True)
class QuerySpec:
    """One tradable instrument on the market-results page.

    Attributes:
        modality: ``Auction`` or ``Continuous``.
        sub_modality: ``DayAhead`` or ``Intraday``.
        auction: The auction / coupling code (``MRC``, ``GB-DAA``, ``IDA1`` …).
            Empty string for continuous trading (no auction).
        slug: Short, filesystem-safe identifier used in output paths.
        trading_offset_days: If not ``None``, ``trading_date`` is sent as
            ``delivery_date - offset`` days. Day-ahead auctions clear on D-1.
            ``None`` omits ``trading_date`` and lets the site derive it
            (appropriate for intraday auctions / continuous).
    """

    modality: str
    sub_modality: str
    auction: str
    slug: str
    trading_offset_days: int | None = None
    market_areas: list[str] = field(default_factory=lambda: list(MARKET_AREAS))


# The instruments / products to enumerate. Kept broad on purpose — see module
# docstring. Extend this list to capture additional auctions as EPEX adds them.
QUERY_SPECS: list[QuerySpec] = [
    # --- Day-ahead auctions ------------------------------------------------
    QuerySpec("Auction", "DayAhead", "MRC", "dayahead-mrc", trading_offset_days=1),
    QuerySpec("Auction", "DayAhead", "GB-DAA", "dayahead-gb", trading_offset_days=1),
    QuerySpec("Auction", "DayAhead", "CH-DAA", "dayahead-ch", trading_offset_days=1),
    # --- Intraday auctions (IDA1 / IDA2 / IDA3) ---------------------------
    QuerySpec("Auction", "Intraday", "IDA1", "intraday-ida1"),
    QuerySpec("Auction", "Intraday", "IDA2", "intraday-ida2"),
    QuerySpec("Auction", "Intraday", "IDA3", "intraday-ida3"),
    # --- Continuous intraday ----------------------------------------------
    QuerySpec("Continuous", "Intraday", "", "intraday-continuous"),
]


# ---------------------------------------------------------------------------
# HTTP behaviour
# ---------------------------------------------------------------------------
# EPEX sits behind a WAF that 403s non-browser User-Agents, so we present a
# current Chrome UA. Keep it roughly in sync with the sec-ch-ua hints in
# client._browser_headers().
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30  # seconds
REQUEST_RETRIES = 3
# Seconds to sleep between requests. Be a good citizen — EPEX is a shared,
# public resource and its terms restrict usage to internal purposes.
REQUEST_SLEEP = 1.5
