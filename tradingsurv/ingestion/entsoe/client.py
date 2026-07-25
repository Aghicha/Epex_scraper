"""Thin wrapper over ENTSO-E Transparency Platform data (entsoe-py).

Requires a free registered security token in ``ENTSOE_API_TOKEN`` (see
tradingsurv/config.py). Each method returns whatever pandas
Series/DataFrame entsoe-py itself returns — this wrapper's only job is
zone-code translation (TradingSurv's ``AT``/``DE-LU``/... vocabulary, shared
with epex_scraper, to ENTSO-E's EIC domain codes) and a clear error when the
token is missing, not reshaping.
"""

from __future__ import annotations

import pandas as pd
from entsoe import EntsoePandasClient

from ... import config


class EntsoeClient:
    def __init__(self, api_token: str | None = None) -> None:
        token = api_token or config.ENTSOE_API_TOKEN
        if not token:
            raise ValueError(
                "ENTSO-E API token missing. Register for free at "
                "https://transparency.entsoe.eu/ and set ENTSOE_API_TOKEN."
            )
        self._client = EntsoePandasClient(api_key=token)

    @staticmethod
    def _resolve_zone(zone: str) -> str:
        try:
            return config.ENTSOE_ZONE_EIC[zone]
        except KeyError as exc:
            raise ValueError(
                f"unknown zone {zone!r}; add it to config.ENTSOE_ZONE_EIC first"
            ) from exc

    def load_forecast(self, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        return self._client.query_load_forecast(self._resolve_zone(zone), start=start, end=end)

    def load_actual(self, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        return self._client.query_load(self._resolve_zone(zone), start=start, end=end)

    def generation_forecast(self, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        return self._client.query_generation_forecast(self._resolve_zone(zone), start=start, end=end)

    def generation_actual(
        self, zone: str, start: pd.Timestamp, end: pd.Timestamp, psr_type: str | None = None
    ) -> pd.DataFrame:
        return self._client.query_generation(self._resolve_zone(zone), start=start, end=end, psr_type=psr_type)

    def installed_capacity_per_unit(
        self, zone: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.DataFrame:
        """Per-unit installed capacity. Only covers larger/individually-tracked
        plants (for AT: hydro + gas) — wind/solar/biomass are disclosed only
        in aggregate, see :meth:`installed_capacity_aggregated`."""
        return self._client.query_installed_generation_capacity_per_unit(
            self._resolve_zone(zone), start=start, end=end
        )

    def installed_capacity_aggregated(
        self, zone: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.Series:
        """Installed capacity per technology (Production Type), zone-wide total.

        The primary asset-registry source for Phase 0 (see
        ``domain/assets/registry.py``) — complete across all technologies,
        unlike the per-unit endpoint above.
        """
        df = self._client.query_installed_generation_capacity(self._resolve_zone(zone), start=start, end=end)
        return df.iloc[0]

    def wind_and_solar_forecast(self, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Day-ahead wind/solar generation forecast — the public-data proxy for
        those technologies' available capacity in the merit order (Step 6.1:
        their marginal cost is ~0, so forecast output *is* their supply
        offer, not nameplate capacity)."""
        return self._client.query_wind_and_solar_forecast(self._resolve_zone(zone), start=start, end=end)

    def unavailability_of_generation_units(
        self, zone: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.DataFrame:
        """Planned/unplanned outages — feeds asset_availability and umm_message."""
        return self._client.query_unavailability_of_generation_units(
            self._resolve_zone(zone), start=start, end=end
        )

    def crossborder_flows(
        self, zone_from: str, zone_to: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.Series:
        return self._client.query_crossborder_flows(
            self._resolve_zone(zone_from), self._resolve_zone(zone_to), start=start, end=end
        )

    def net_position(self, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
        return self._client.query_net_position(self._resolve_zone(zone), start=start, end=end)
