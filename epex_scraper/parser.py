"""Parse EPEX market-results HTML into tidy/long records.

The market-results page renders its data as HTML ``<table>`` elements.  The
exact DOM varies by product (day-ahead vs. continuous, hourly vs.
quarter-hourly), so this parser is intentionally *heuristic and defensive*
rather than tied to fixed column indices:

* It picks the "values" table as the one carrying the most numeric data.
* It aligns each value row with a period/time label (from a sibling label
  column when present, otherwise the table's own first column / index).
* Every cell is emitted twice — as the original ``value_raw`` string *and* a
  best-effort parsed ``value`` float — so no information is lost even if the
  numeric-format assumptions are wrong for some locale.

Output is a list of flat dicts, one per (period, metric).
"""

from __future__ import annotations

import logging
import re
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MISSING = {"", "-", "–", "—", "n/a", "na", "n.a.", "null", "none"}
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?")
# A label column looks like a list of clock times / hour ranges.
_LABEL_RE = re.compile(r"^\s*\d{1,2}(:\d{2})?\s*[-–]\s*\d{1,2}(:\d{2})?")


def _clean_number(raw: object) -> float | None:
    """Best-effort conversion of an EPEX cell string to a float.

    Assumes the English site convention: ``.`` decimal separator and ``,``
    thousands separator. Returns ``None`` for blanks / missing markers.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s.lower() in _MISSING:
        return None
    # Drop thousands separators and any stray whitespace / unit suffixes.
    s = s.replace(",", "").replace("\xa0", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _flatten_columns(df: pd.DataFrame) -> list[str]:
    """Flatten (possibly multi-level) column headers to unique, clean strings.

    Blank / ``Unnamed`` headers and any collisions are given positional
    fallbacks so every column can be addressed unambiguously.
    """
    raw: list[str] = []
    for col in df.columns:
        if isinstance(col, tuple):
            parts = [str(p) for p in col if p and not str(p).startswith("Unnamed")]
            name = " ".join(dict.fromkeys(parts))  # de-dup, keep order
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
    m = _TIME_RE.search(str(label))
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if hour > 24 or minute >= 60:
        return None
    # Hour 24 rolls to 00 of the same delivery day for our purposes.
    hour = hour % 24
    return f"{delivery_date.isoformat()}T{hour:02d}:{minute:02d}:00"


def _looks_like_label_series(series: pd.Series) -> bool:
    """True if a column is mostly hour-range / clock-time labels."""
    vals = [str(v) for v in series.dropna().tolist()]
    if not vals:
        return False
    hits = sum(1 for v in vals if _LABEL_RE.match(v))
    return hits >= max(2, len(vals) // 2)


def _score_table(df: pd.DataFrame) -> int:
    """Heuristic score: rows x numeric-ish columns."""
    numeric_cols = 0
    for col in df.columns:
        parsed = df[col].map(_clean_number)
        if parsed.notna().sum() >= max(2, len(df) // 2):
            numeric_cols += 1
    return len(df) * numeric_cols


def parse_market_results(html: str, meta: dict) -> list[dict]:
    """Extract long-format records from a market-results HTML page.

    ``meta`` supplies the request context (market_area, modality, sub_modality,
    auction, product, delivery_date, trading_date, source_url, scraped_at) that
    is copied onto every emitted record.
    """
    try:
        tables = pd.read_html(StringIO(html))
    except ValueError:
        logger.debug("no <table> elements found for %s", meta.get("source_url"))
        return []
    if not tables:
        return []

    # Pick the richest table as the values table.
    scored = [(_score_table(df), df) for df in tables]
    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, values = scored[0]
    if best_score == 0:
        logger.debug("no numeric table for %s", meta.get("source_url"))
        return []

    values = values.copy()
    values.columns = _flatten_columns(values)

    # Find period labels: prefer a label-like column *inside* the values table,
    # otherwise look for a sibling single-column label table, otherwise fall
    # back to the row position.
    label_col = None
    for col in values.columns:
        if _looks_like_label_series(values[col]):
            label_col = col
            break

    labels: list
    if label_col is not None:
        labels = values[label_col].tolist()
        metric_cols = [c for c in values.columns if c != label_col]
    else:
        sibling = _find_sibling_labels(tables, len(values))
        labels = sibling if sibling is not None else list(range(len(values)))
        metric_cols = list(values.columns)

    delivery_date = meta["delivery_date"]
    records: list[dict] = []
    for i, (_, row) in enumerate(values.iterrows()):
        label = labels[i] if i < len(labels) else i
        period_label = "" if _is_blank(label) else str(label).strip()
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


def _find_sibling_labels(tables: list[pd.DataFrame], n_rows: int):
    """Look for a separate label table with matching row count."""
    for df in tables:
        if len(df) != n_rows:
            continue
        for col in df.columns:
            if _looks_like_label_series(df[col]):
                return df[col].tolist()
    return None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    return str(value).strip().lower() in _MISSING
