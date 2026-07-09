"""Deduplicated, git-friendly storage of scraped records.

Layout (one file is the atomic dedup unit)::

    data/<spec-slug>/<market_area>/p<product>/<delivery_date>.csv

Because each file is keyed by delivery date, re-scraping the same delivery day
just rewrites the same file.  Writes are *idempotent*: if the freshly scraped
data is identical to what's already on disk (ignoring the ``scraped_at``
timestamp) the file is left untouched, so unchanged days produce no git diff
and therefore no noisy commits.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Stable column order for every output file.
COLUMNS = [
    "market_area",
    "modality",
    "sub_modality",
    "auction",
    "product",
    "delivery_date",
    "trading_date",
    "period_index",
    "period_label",
    "period_start",
    "metric",
    "unit",
    "value",
    "value_raw",
    "source_url",
    "scraped_at",
]

# Columns that legitimately change between runs without meaning "new data".
_VOLATILE = ["scraped_at"]


def partition_path(root: Path, slug: str, market_area: str, product: int,
                   delivery_date: date) -> Path:
    """Return the CSV path for one (spec, area, product, delivery_date)."""
    return root / slug / market_area / f"p{product}" / f"{delivery_date.isoformat()}.csv"


def is_settled(delivery_date: date, today: date, settle_days: int = 2) -> bool:
    """Whether a delivery day is old enough that its data won't change again.

    Day-ahead results are final once published; intraday keeps updating during
    the delivery day. Anything at least ``settle_days`` in the past is treated
    as final, so we can skip re-fetching it once stored.
    """
    return (today - delivery_date).days >= settle_days


def _frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS]
    return df.sort_values(["period_index", "metric"]).reset_index(drop=True)


def _same_data(new: pd.DataFrame, path: Path) -> bool:
    """True if ``new`` matches the existing file ignoring volatile columns."""
    try:
        old = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return False
    a = new.drop(columns=_VOLATILE).astype(str).reset_index(drop=True)
    b = old.drop(columns=[c for c in _VOLATILE if c in old.columns],
                 errors="ignore")
    b = b[[c for c in a.columns if c in b.columns]].astype(str).reset_index(drop=True)
    return a.equals(b)


def write_partition(root: Path, slug: str, market_area: str, product: int,
                    delivery_date: date, records: list[dict]) -> str:
    """Write one partition file.

    Returns one of ``"written"``, ``"unchanged"`` or ``"empty"`` describing
    what happened, for run reporting.
    """
    if not records:
        return "empty"

    path = partition_path(root, slug, market_area, product, delivery_date)
    df = _frame(records)
    if path.exists() and _same_data(df, path):
        return "unchanged"

    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("wrote %d rows -> %s", len(df), path)
    return "written"
