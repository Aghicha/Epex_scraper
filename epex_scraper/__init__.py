"""EPEX SPOT market-results scraper.

A small, dependency-light toolkit that pulls the public market-results tables
from https://www.epexspot.com/en/market-results for every market area, trading
product and instrument, normalises them to a long/tidy format and stores them
as deduplicated, per-delivery-date CSV files that are committed to git.
"""

__version__ = "0.1.0"
