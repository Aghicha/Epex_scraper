"""Static configuration for TradingSurv: zone mapping and environment-driven secrets."""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Loads .env from the current/parent directories if present; a no-op (and
# harmless) if it's missing, e.g. in CI where secrets come from the
# environment directly.
load_dotenv()

# ENTSO-E Transparency Platform requires a free registered security token.
# https://transparency.entsoe.eu/ -> account settings -> "Web Api Security Token".
# Set it in a local .env (see .env.example) or export it directly.
ENTSOE_API_TOKEN = os.environ.get("ENTSOE_API_TOKEN")

# EIC bidding-zone codes for ENTSO-E, keyed by the same market_area codes
# epex_scraper already uses (see epex_scraper/config.py) so the two modules
# share one zone vocabulary.
ENTSOE_ZONE_EIC: dict[str, str] = {
    "AT": "10YAT-APG------L",
    "DE-LU": "10Y1001A1001A82H",
    "BE": "10YBE----------2",
    "FR": "10YFR-RTE------C",
    "NL": "10YNL----------L",
    "CH": "10YCH-SWISSGRIDZ",
    "GB": "10YGB----------A",
    "PL": "10YPL-AREA-----S",
    "FI": "10YFI-1--------U",
    "DK1": "10YDK-1--------W",
    "DK2": "10YDK-2--------M",
    "NO1": "10YNO-1--------2",
    "NO2": "10YNO-2--------T",
    "NO3": "10YNO-3--------J",
    "NO4": "10YNO-4--------9",
    "NO5": "10Y1001A1001A48H",
    "SE1": "10Y1001A1001A44P",
    "SE2": "10Y1001A1001A45N",
    "SE3": "10Y1001A1001A46L",
    "SE4": "10Y1001A1001A47J",
}

# Pilot zones for the Phase 0/1 MVP (both already have deep history under
# data/day-ahead/ from epex_scraper).
PILOT_ZONES: list[str] = ["AT", "DE-LU"]

DEFAULT_CO2_PRICE_EUR_T = 70.0
DEFAULT_VARIABLE_OM_EUR_MWH = 2.0
