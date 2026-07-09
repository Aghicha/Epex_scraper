"""Parse EPEX market-results HTML into long records.

The market-results page renders its data as HTML ``<table>`` elements, and the
exact DOM varies by product (day-ahead vs. continuous, hourly vs.
quarter-hourly). The parser therefore identifies the *results* table by the one
signal every product shares: a **time column** whose cells look like
``00:00 - 00:15`` / ``00 - 01``.

* Among all tables on the page, it prefers the richest one that has such a time
  column (or time-like row index / sibling label table). This both selects the
  correct table and yields the ``Hours`` labels.
* Every cell is emitted as the original ``value_raw`` string *and* a best-effort
  parsed ``value`` float, so nothing is lost if a number-format assumption is
  wrong.

Output is a list of flat long records (one per period × metric); the storage
layer pivots them into the wide, EPEX-like table.
"""

from __future__ import annotations

import logging
import re
from io import StringIO

import pandas as pd

logger = logging.getLogger(__name__)

_MISSING = {"", "-", "–", "—", "n/a", "na", "n.a.", "null", "none", "nan"}
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_HOUR_RE = re.compile(r"^\s*(\d{1,2})\b")
# A time label: "00:00 - 00:15", "00 - 01", or a bare clock time "00:00".
# Deliberately does NOT match bare integers like "0"/"1" (row indices).
_LABEL_RE = re.compile(
    r"^\s*\d{1,2}(:\d{2})?\s*[-–—]\s*\d{1,2}(:\d{2})?\s*$"
    r"|^\s*\d{1,2}:\d{2}\s*$"
)


def _clean_number(raw: object) -> float | None:
    """Convert an EPEX cell string to a float (``.`` decimal, ``,`` thousands)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() in _MISSING:
        return None
    s = s.replace(",", "").replace("\xa0", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _flatten_columns(df: pd.DataFrame) -> list[str]:
    """Flatten (possibly multi-level) column headers to unique, clean strings."""
    raw: list[str] = []
    for col in df.columns:
        if isinstance(col, tuple):
            parts = [str(p) for p in col if p and not str(p).startswith("Unnamed")]
            name = " ".join(dict.fromkeys(parts))
        else:
            name = "" if str(col).startswith("Unnamed") else str(col)
        raw.append(name.strip())

    cols: list[str] = []
    seen: dict[str, int] = {}
    for i, name in enumerate(raw):
        base = name or f"col_{i}"
        if base in seen:
            seen[base] += 1
            base = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
        cols.append(base)
    return cols


def _split_unit(header: str) -> tuple[str, str | None]:
    """Split ``"Price (€/MWh)"`` -> ``("price", "€/MWh")``."""
    unit = None
    m = re.search(r"\(([^)]+)\)", header)
    if m:
        unit = m.group(1).strip()
        header = header[: m.start()].strip()
    metric = re.sub(r"[^0-9a-zA-Z]+", "_", header).strip("_").lower()
    return metric or "value", unit


def _period_start(label: str, delivery_date) -> str | None:
    """Derive an ISO ``delivery_date`` + start-time from a period label."""
    s = str(label)
    m = _TIME_RE.search(s)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
    else:
        h = _HOUR_RE.match(s)
        if not h:
            return None
        hour, minute = int(h.group(1)), 0
    if hour > 24 or minute >= 60:
        return None
    hour %= 24
    return f"{delivery_date.isoformat()}T{hour:02d}:{minute:02d}:00"


def _label_score(values) -> int:
    """How many entries look like time labels."""
    vals = [str(v) for v in values if not _is_blank(v)]
    return sum(1 for v in vals if _LABEL_RE.match(v))


def _numeric_score(df: pd.DataFrame) -> int:
    """Number of columns that are mostly numeric."""
    n = 0
    for col in df.columns:
        parsed = df[col].map(_clean_number)
        if parsed.notna().sum() >= max(2, len(df) // 2):
            n += 1
    return n


def _find_time_labels(df: pd.DataFrame):
    """Return (labels, metric_columns) if this table has a time column/index.

    Looks at each column and the row index; returns ``None`` if nothing in the
    table looks like a series of time labels.
    """
    threshold = max(2, len(df) // 2)
    for col in df.columns:
        if _label_score(df[col].tolist()) >= threshold:
            labels = df[col].tolist()
            metrics = [c for c in df.columns if c != col]
            return labels, metrics
    # Fall back to the row index (EPEX sometimes puts Hours in the index).
    if _label_score(list(df.index)) >= threshold:
        return list(df.index), list(df.columns)
    return None


def parse_market_results(html: str, meta: dict) -> list[dict]:
    """Extract long-format records from a market-results HTML page."""
    try:
        tables = [t for t in pd.read_html(StringIO(html)) if not t.empty]
    except ValueError:
        logger.debug("no <table> elements for %s", meta.get("source_url"))
        return []
    if not tables:
        return []

    flat = []
    for df in tables:
        df = df.copy()
        df.columns = _flatten_columns(df)
        flat.append(df)

    # Prefer the richest table that carries a time column (the results table).
    candidates = []
    for df in flat:
        found = _find_time_labels(df)
        if found:
            labels, metrics = found
            candidates.append((_numeric_score(df), df, labels, metrics))

    if candidates:
        candidates.sort(key=lambda t: t[0], reverse=True)
        _, values, labels, metric_cols = candidates[0]
    else:
        # No time column anywhere: try a sibling label table, else give up
        # rather than emit a meaningless integer-indexed table.
        best = max(flat, key=_numeric_score)
        if _numeric_score(best) == 0:
            return []
        labels = _sibling_labels(flat, len(best))
        if labels is None:
            logger.debug("no time labels found for %s", meta.get("source_url"))
            return []
        values, metric_cols = best, list(best.columns)

    delivery_date = meta["delivery_date"]
    records: list[dict] = []
    for i, (_, row) in enumerate(values.reset_index(drop=True).iterrows()):
        label = labels[i] if i < len(labels) else i
        if _is_blank(label):
            continue
        period_label = str(label).strip()
        # Skip aggregate rows (Baseload / Peakload / totals) that lack a time.
        if not _LABEL_RE.match(period_label):
            continue
        period_start = _period_start(period_label, delivery_date)
        for col in metric_cols:
            metric, unit = _split_unit(str(col))
            raw = row[col]
            if _is_blank(raw):
                continue
            records.append(
                {
                    **meta,
                    "period_index": i,
                    "period_label": period_label,
                    "period_start": period_start,
                    "metric": metric,
                    "unit": unit,
                    "value_raw": str(raw).strip(),
                    "value": _clean_number(raw),
                }
            )
    return records


def _sibling_labels(tables: list[pd.DataFrame], n_rows: int):
    for df in tables:
        if len(df) != n_rows:
            continue
        for col in df.columns:
            if _label_score(df[col].tolist()) >= max(2, n_rows // 2):
                return df[col].tolist()
    return None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip().lower() in _MISSING
