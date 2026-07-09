"""Parse EPEX market-results HTML into long records.

The results widget does **not** render as a single HTML table. Its real markup
(verified against the live site) is::

    <div class="custom-tables 60min">
      <div class="fixed-column js-table-times">          <!-- the Hours -->
        <span class="fixed-head-column">Hours</span>
        <ul><li><a>00 - 01</a></li> ... </ul>
      </div>
      <div class="js-table-values">
        <table class="table-01 ...">
          <thead>
            ... Baseload / Peakload summary rows ...
            <tr><th>Buy Volume (MWh)</th><th>Sell Volume (MWh)</th>
                <th>Volume (MWh)</th><th>Price (€/MWh)</th></tr>   <!-- headers -->
          </thead>
          <tbody>
            <tr><td>25,670.2</td><td>28,398.7</td><td>28,398.7</td><td>114.92</td></tr>
            ...                                                    <!-- one row / period -->
          </tbody>
        </table>
      </div>
    </div>

So the Hours live in a ``<ul>`` (not a table) and the values in a table whose
``<thead>`` mixes a summary block with the real column headers.  We therefore
parse with BeautifulSoup: Hours from the ``js-table-times`` list, headers from
the ``<thead>`` row whose column count matches the ``<tbody>`` rows, and values
from ``<tbody>``, aligning rows to Hours by position.  This structure is shared
by every product (day-ahead, intraday auctions, continuous), only the set of
value columns differs.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MISSING = {"", "-", "–", "—", "n/a", "na", "n.a.", "null", "none", "nan"}
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")
_HOUR_RE = re.compile(r"^\s*(\d{1,2})\b")


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


def _cell_text(el) -> str:
    """Collapse an element's text (joining <br>-separated parts with a space)."""
    return " ".join(el.get_text(separator=" ", strip=True).split())


def _row_resolution(tr) -> int:
    """Resolution (minutes) of a continuous-table row from its CSS class."""
    cls = set(tr.get("class", []))
    if "lvl-2" in cls:
        return 15
    if "lvl-1" in cls:
        return 30
    return 60


def _header_row(table, ncols: int):
    """Return the <thead> row whose <th> count matches the data rows."""
    thead = table.find("thead")
    if thead is None:
        return None
    match = None
    for tr in thead.find_all("tr"):
        ths = tr.find_all("th")
        if len(ths) == ncols:
            match = ths  # keep the last matching row (the real column headers)
    return match


def parse_market_results(html: str, meta: dict) -> list[dict]:
    """Extract long-format records from a market-results HTML page."""
    soup = BeautifulSoup(html, "lxml")

    times = [
        _cell_text(li)
        for li in soup.select(".js-table-times ul li")
    ]

    table = soup.select_one(".js-table-values table") or soup.select_one("table.table-01")
    if table is None:
        logger.debug("no values table for %s", meta.get("source_url"))
        return []
    tbody = table.find("tbody")
    if tbody is None:
        return []
    data_rows = [tr for tr in tbody.find_all("tr", recursive=False)]
    data_rows = [r for r in data_rows if r.find_all("td")]
    if not data_rows:
        return []

    ncols = len(data_rows[0].find_all("td"))
    header_ths = _header_row(table, ncols)
    if header_ths:
        headers = [_cell_text(th) for th in header_ths]
    else:
        headers = [f"col_{i}" for i in range(ncols)]

    # Continuous pages embed all three resolutions (60/30/15 min) in one table
    # and hide the non-selected ones via CSS classes (lvl-1 = 30, lvl-2 = 15,
    # neither = 60); the browser filters client-side. Day-ahead / IDA pages are
    # already single-resolution. So: if the table mixes levels, keep only the
    # rows matching the requested product.
    has_levels = any(
        {"lvl-1", "lvl-2"} & set(r.get("class", [])) for r in data_rows
    )
    target = int(meta.get("product") or 60)
    selected = [
        (i, r) for i, r in enumerate(data_rows)
        if not has_levels or _row_resolution(r) == target
    ]

    delivery_date = meta["delivery_date"]
    records: list[dict] = []
    for out_index, (i, row) in enumerate(selected):
        cells = row.find_all("td")
        period_label = times[i] if i < len(times) else str(i)
        if not period_label or period_label.strip().lower() in _MISSING:
            continue
        period_start = _period_start(period_label, delivery_date)
        for j, td in enumerate(cells):
            header = headers[j] if j < len(headers) else f"col_{j}"
            metric, unit = _split_unit(header)
            raw = _cell_text(td)
            if raw.lower() in _MISSING:
                continue
            records.append(
                {
                    **meta,
                    "period_index": out_index,
                    "period_label": period_label,
                    "period_start": period_start,
                    "metric": metric,
                    "unit": unit,
                    "value_raw": raw,
                    "value": _clean_number(raw),
                }
            )
    return records
