"""Deduplicated, git-friendly storage of scraped records as wide tables.

Layout — organised **per product, then per market, then per day**::

    data/<product>/<market_area>/<delivery_date>_<resolution>min.csv

Each file mirrors the EPEX market-results table: **one row per delivery
period**, with an ``hours`` column and one column per metric
(``Buy Volume (MWh)``, ``Sell Volume (MWh)``, ``Volume (MWh)``,
``Price (€/MWh)``, …).

Because each file is keyed by delivery date, re-scraping the same day just
rewrites the same file. Writes are **idempotent** — identical content is not
rewritten — so unchanged days produce no git diff and no commit.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Leading context columns, then hours, then metrics (appended in a stable order).
_LEAD_COLUMNS = ["delivery_date", "market_area", "hours", "period_start"]

# Preferred left-to-right metric order (matches EPEX's own column order:
# price metrics first for continuous, then volumes; day-ahead only has the
# volume/price tail). Anything unknown is appended alphabetically.
_METRIC_ORDER = [
    "low", "high", "last", "weight_avg", "id_full", "id_1", "id_3",
    "buy_volume", "sell_volume", "volume", "price",
]

# Human-readable column names, matching EPEX's own labels.
_METRIC_LABEL = {
    "low": "Low",
    "high": "High",
    "last": "Last",
    "weight_avg": "Weight Avg",
    "id_full": "ID Full",
    "id_1": "ID1",
    "id_3": "ID3",
    "buy_volume": "Buy Volume",
    "sell_volume": "Sell Volume",
    "volume": "Volume",
    "price": "Price",
}


def partition_path(root: Path, slug: str, market_area: str, product: int,
                   delivery_date: date) -> Path:
    """Return the CSV path for one (product, market, day, resolution)."""
    root = Path(root)
    return root / slug / market_area / f"{delivery_date.isoformat()}_{product}min.csv"


def is_settled(delivery_date: date, today: date, settle_days: int = 2) -> bool:
    """Whether a delivery day is old enough that its data won't change again."""
    return (today - delivery_date).days >= settle_days


def _metric_header(metric: str, unit: str | None) -> str:
    label = _METRIC_LABEL.get(metric, metric.replace("_", " ").title())
    return f"{label} ({unit})" if unit else label


def _wide_frame(records: list[dict]) -> pd.DataFrame:
    """Pivot long records into one row per period with metric columns."""
    first = records[0]
    units: dict[str, str | None] = {}
    order_seen: list[str] = []
    periods: dict[int, dict] = {}

    for r in records:
        metric = r["metric"]
        if metric not in units:
            units[metric] = r.get("unit")
            order_seen.append(metric)
        pi = r["period_index"]
        row = periods.setdefault(
            pi,
            {
                "delivery_date": first["delivery_date"],
                "market_area": first["market_area"],
                "hours": r["period_label"],
                "period_start": r["period_start"],
            },
        )
        row[_metric_header(metric, units[metric])] = r["value"]

    ordered_metrics = (
        [m for m in _METRIC_ORDER if m in units]
        + sorted(m for m in order_seen if m not in _METRIC_ORDER)
    )
    metric_headers = [_metric_header(m, units[m]) for m in ordered_metrics]
    columns = ["delivery_date", "market_area", "hours"] + metric_headers + ["period_start"]

    rows = [periods[pi] for pi in sorted(periods)]
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df[columns]


def write_partition(root: Path, slug: str, market_area: str, product: int,
                    delivery_date: date, records: list[dict]) -> str:
    """Write one partition file. Returns ``written`` / ``unchanged`` / ``empty``."""
    if not records:
        return "empty"

    path = partition_path(root, slug, market_area, product, delivery_date)
    df = _wide_frame(records)

    if path.exists():
        try:
            old = pd.read_csv(path, dtype=str, keep_default_na=False)
            if old.astype(str).reset_index(drop=True).equals(
                df.astype(str).reset_index(drop=True)
            ):
                return "unchanged"
        except (pd.errors.EmptyDataError, FileNotFoundError):
            pass

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("wrote %d periods -> %s", len(df), path)
    return "written"
