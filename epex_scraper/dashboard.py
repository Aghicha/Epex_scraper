"""Build a self-contained interactive HTML dashboard from scraped CSVs.

Run as::

    python -m epex_scraper.dashboard --data-dir data --output dashboard.html

Walks ``data/<slug>/<market_area>/<delivery_date>_<resolution>min.csv``,
normalises every file's columns (auction products expose a single ``Price``
column; continuous exposes ``Weight Avg`` instead, plus Low/High/Last/ID
indices we don't chart), and embeds the result as JSON in a static HTML page
that renders synced price/volume charts client-side with Plotly — no server,
no network access needed to view it (Plotly itself is loaded from a CDN).
"""

from __future__ import annotations

import argparse
import json
import re
import webbrowser
from collections import defaultdict
from pathlib import Path

FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)min\.csv$")
# Priority order: a plain auction Price column wins; continuous instruments
# have no such column so fall back to Weight Avg, then Last.
PRICE_COL_RE = re.compile(r"^(Price|Weight Avg|Last) \(([^/]+)/MWh\)$")


def _parse_csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _detect_price_col(header: list[str]) -> tuple[str, str, str] | None:
    """Return (column_name, metric_label, currency) for the best price-like column."""
    candidates: dict[str, tuple[str, str, str]] = {}
    for col in header:
        m = PRICE_COL_RE.match(col)
        if m:
            candidates[m.group(1)] = (col, m.group(1), m.group(2))
    for metric in ("Price", "Weight Avg", "Last"):
        if metric in candidates:
            return candidates[metric]
    return None


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def collect_series(data_dir: Path, slugs: list[str] | None,
                    market_areas: list[str] | None) -> dict:
    """Walk data_dir and build the nested JSON structure the page consumes."""
    wanted_slugs = set(slugs) if slugs else None
    wanted_areas = set(market_areas) if market_areas else None

    # specs[slug]["markets"][market_area][resolution] -> list of points
    specs: dict[str, dict] = {}

    if not data_dir.is_dir():
        return {"specs": {}}

    for slug_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        slug = slug_dir.name
        if slug.startswith("_"):
            continue  # data/_manifest
        if wanted_slugs and slug not in wanted_slugs:
            continue
        for area_dir in sorted(p for p in slug_dir.iterdir() if p.is_dir()):
            market_area = area_dir.name
            if wanted_areas and market_area not in wanted_areas:
                continue
            for csv_path in sorted(area_dir.glob("*.csv")):
                m = FILENAME_RE.match(csv_path.name)
                if not m:
                    continue
                resolution = m.group(2)
                rows = _read_csv_rows(csv_path)
                if not rows:
                    continue
                header = list(rows[0].keys())
                price_info = _detect_price_col(header)
                points = []
                for row in rows:
                    try:
                        volume = float(row["Volume (MWh)"])
                    except (KeyError, ValueError):
                        volume = None
                    try:
                        buy = float(row["Buy Volume (MWh)"])
                    except (KeyError, ValueError):
                        buy = None
                    try:
                        sell = float(row["Sell Volume (MWh)"])
                    except (KeyError, ValueError):
                        sell = None
                    price = None
                    if price_info:
                        try:
                            price = float(row[price_info[0]])
                        except (KeyError, ValueError):
                            price = None
                    points.append({
                        "t": row.get("period_start"),
                        "p": price,
                        "v": volume,
                        "b": buy,
                        "s": sell,
                    })
                points.sort(key=lambda r: r["t"] or "")

                spec = specs.setdefault(slug, {"markets": {}})
                market = spec["markets"].setdefault(market_area, {})
                # A market/resolution's schema (which price-like column EPEX
                # exposed, and its currency) can differ day to day in the
                # scraped data. Each point still keeps its own correctly
                # detected value; the series-level label is last-write-wins
                # so it reflects the most recent (and most relevant) file
                # rather than silently freezing on the first one seen.
                existing = market.setdefault(resolution, {"points": []})
                if price_info:
                    existing["metric"] = price_info[1]
                    existing["currency"] = price_info[2]
                else:
                    existing.setdefault("metric", None)
                    existing.setdefault("currency", None)
                existing["points"].extend(points)

    for spec in specs.values():
        for market in spec["markets"].values():
            for res in market.values():
                res["points"].sort(key=lambda r: r["t"] or "")

    return {"specs": specs}


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EPEX market results dashboard</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
:root {
  color-scheme: light;
  --surface-1:      #fcfcfb;
  --page:           #f9f9f7;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --text-muted:     #898781;
  --grid:           #e1e0d9;
  --baseline:       #c3c2b7;
  --border:         rgba(11,11,11,0.10);
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --grid:           #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1:      #1a1a19;
  --page:           #0d0d0d;
  --text-primary:   #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted:     #898781;
  --grid:           #2c2c2a;
  --baseline:       #383835;
  --border:         rgba(255,255,255,0.10);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--page);
  color: var(--text-primary);
}
header {
  padding: 20px 24px 4px;
}
h1 { font-size: 18px; margin: 0 0 2px; }
.subtitle { color: var(--text-secondary); font-size: 13px; margin: 0 0 16px; }
.controls {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 20px;
  padding: 14px 24px;
  margin: 0 24px 16px;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.control-group { display: flex; flex-direction: column; gap: 6px; }
.control-group label.group-label {
  font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
  color: var(--text-muted);
}
select, input[type=date], button {
  font: inherit;
  font-size: 13px;
  background: var(--page);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
}
button { cursor: pointer; }
button.active { outline: 2px solid var(--baseline); }
.market-list {
  display: flex; flex-wrap: wrap; gap: 4px 12px; max-width: 520px;
}
.market-list label {
  font-size: 12.5px; display: flex; align-items: center; gap: 5px;
  color: var(--text-secondary); cursor: pointer;
}
.market-list input:disabled + span { color: var(--text-muted); }
.preset-row { display: flex; gap: 6px; }
.preset-row button { padding: 5px 9px; font-size: 12px; }
main { padding: 0 24px 40px; display: flex; flex-direction: column; gap: 4px; }
.chart-card {
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 12px 4px;
  margin-bottom: 12px;
}
.chart-card h2 {
  font-size: 13px; font-weight: 600; margin: 6px 4px 0;
  color: var(--text-secondary);
}
.note { font-size: 12px; color: var(--text-muted); padding: 0 24px 8px; }
table.data-table {
  border-collapse: collapse; width: 100%; font-size: 12.5px;
  font-variant-numeric: tabular-nums;
}
table.data-table th, table.data-table td {
  text-align: right; padding: 4px 10px; border-bottom: 1px solid var(--grid);
}
table.data-table th:first-child, table.data-table td:first-child { text-align: left; }
table.data-table th { color: var(--text-muted); font-weight: 600; position: sticky; top: 0; background: var(--surface-1); }
.table-wrap { max-height: 420px; overflow: auto; }
.empty-state { color: var(--text-muted); font-size: 13px; padding: 24px; }
</style>
</head>
<body>
<header>
  <h1>EPEX market results dashboard</h1>
  <p class="subtitle">Generated __GENERATED_AT__ from local scrape data. Loads no external data — everything below is embedded.</p>
</header>

<div class="controls">
  <div class="control-group">
    <label class="group-label" for="product-select">Product</label>
    <select id="product-select"></select>
  </div>
  <div class="control-group">
    <label class="group-label" for="resolution-select">Resolution</label>
    <select id="resolution-select"></select>
  </div>
  <div class="control-group">
    <span class="group-label">Date range</span>
    <div class="preset-row" id="preset-row">
      <button data-preset="all">All</button>
      <button data-preset="7">Last 7d</button>
      <button data-preset="30">Last 30d</button>
    </div>
    <div class="preset-row">
      <input type="date" id="date-from">
      <input type="date" id="date-to">
    </div>
  </div>
  <div class="control-group">
    <span class="group-label">Market areas (up to 8)</span>
    <div class="market-list" id="market-list"></div>
  </div>
  <div class="control-group">
    <span class="group-label">View</span>
    <div class="preset-row">
      <button id="toggle-table">Show as table</button>
      <button id="toggle-theme">Toggle dark mode</button>
    </div>
  </div>
</div>

<main id="main">
  <div class="chart-card">
    <h2 id="price-title">Price</h2>
    <div id="price-chart" style="height:340px;"></div>
  </div>
  <div class="chart-card">
    <h2>Volume (MWh)</h2>
    <div id="volume-chart" style="height:220px;"></div>
  </div>
  <div class="chart-card" id="table-card" style="display:none;">
    <h2>Data table</h2>
    <div class="table-wrap"><table class="data-table" id="data-table"></table></div>
  </div>
</main>
<p class="note">Colors are assigned per market area on a first-checked/first-freed basis, so a series keeps its color for as long as it stays selected.</p>

<script>
const DATA = __DATA_JSON__;

// Validated 8-slot categorical palette (light/dark), fixed order, never cycled.
const PALETTE = [
  { light: "#2a78d6", dark: "#3987e5" },
  { light: "#eb6834", dark: "#d95926" },
  { light: "#1baf7a", dark: "#199e70" },
  { light: "#eda100", dark: "#c98500" },
  { light: "#e87ba4", dark: "#d55181" },
  { light: "#008300", dark: "#008300" },
  { light: "#4a3aa7", dark: "#9085e9" },
  { light: "#e34948", dark: "#e66767" },
];

function isDark() {
  const t = document.documentElement.getAttribute("data-theme");
  if (t === "dark") return true;
  if (t === "light") return false;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

// Slot pool allocator: a market area keeps its slot as long as it stays
// checked; unchecking frees the slot for reuse. This keeps already-plotted
// series from repainting when the selection changes elsewhere.
const slotOf = new Map();
const freeSlots = [0, 1, 2, 3, 4, 5, 6, 7];
function colorFor(marketArea) {
  if (!slotOf.has(marketArea)) {
    const slot = freeSlots.length ? freeSlots.shift() : (slotOf.size % 8);
    slotOf.set(marketArea, slot);
  }
  const slot = slotOf.get(marketArea);
  return PALETTE[slot][isDark() ? "dark" : "light"];
}
function releaseColor(marketArea) {
  if (slotOf.has(marketArea)) {
    freeSlots.push(slotOf.get(marketArea));
    slotOf.delete(marketArea);
  }
}

const productSelect = document.getElementById("product-select");
const resolutionSelect = document.getElementById("resolution-select");
const marketList = document.getElementById("market-list");
const dateFrom = document.getElementById("date-from");
const dateTo = document.getElementById("date-to");

const slugs = Object.keys(DATA.specs).sort();
for (const slug of slugs) {
  const opt = document.createElement("option");
  opt.value = slug;
  opt.textContent = slug;
  productSelect.appendChild(opt);
}

function resolutionsFor(slug) {
  const markets = DATA.specs[slug].markets;
  const set = new Set();
  for (const area of Object.keys(markets)) {
    for (const res of Object.keys(markets[area])) set.add(res);
  }
  return [...set].sort((a, b) => Number(a) - Number(b));
}

function marketsFor(slug, resolution) {
  const markets = DATA.specs[slug].markets;
  return Object.keys(markets)
    .filter((area) => markets[area][resolution])
    .sort();
}

function populateResolutions() {
  const slug = productSelect.value;
  resolutionSelect.innerHTML = "";
  for (const res of resolutionsFor(slug)) {
    const opt = document.createElement("option");
    opt.value = res;
    opt.textContent = res + " min";
    resolutionSelect.appendChild(opt);
  }
}

function populateMarkets(preserveChecked) {
  const slug = productSelect.value;
  const resolution = resolutionSelect.value;
  const previouslyChecked = preserveChecked
    ? new Set([...marketList.querySelectorAll("input:checked")].map((i) => i.value))
    : new Set();
  marketList.innerHTML = "";
  const areas = marketsFor(slug, resolution);
  for (const area of areas) {
    const id = "mkt-" + area;
    const wrap = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = area;
    cb.id = id;
    if (previouslyChecked.has(area)) cb.checked = true;
    cb.addEventListener("change", () => {
      if (!cb.checked) releaseColor(area);
      enforceMaxSelection();
      render();
    });
    const span = document.createElement("span");
    span.textContent = area;
    wrap.appendChild(cb);
    wrap.appendChild(span);
    marketList.appendChild(wrap);
  }
  if (![...marketList.querySelectorAll("input:checked")].length && areas.length) {
    // Default: first market area checked so the page isn't empty on load.
    const first = marketList.querySelector("input");
    if (first) first.checked = true;
  }
  enforceMaxSelection();
}

function enforceMaxSelection() {
  const boxes = [...marketList.querySelectorAll("input")];
  const checkedCount = boxes.filter((b) => b.checked).length;
  for (const b of boxes) {
    b.disabled = !b.checked && checkedCount >= 8;
  }
}

function allDates(slug, resolution, areas) {
  const markets = DATA.specs[slug].markets;
  const dates = [];
  for (const area of areas) {
    const series = markets[area] && markets[area][resolution];
    if (!series) continue;
    for (const pt of series.points) if (pt.t) dates.push(pt.t.slice(0, 10));
  }
  return dates.sort();
}

function checkedMarkets() {
  return [...marketList.querySelectorAll("input:checked")].map((i) => i.value);
}

function applyPreset(days) {
  const slug = productSelect.value, resolution = resolutionSelect.value;
  const areas = marketsFor(slug, resolution);
  const dates = allDates(slug, resolution, areas);
  if (!dates.length) return;
  const max = dates[dates.length - 1];
  if (days === "all") {
    dateFrom.value = dates[0];
    dateTo.value = max;
  } else {
    const to = new Date(max + "T00:00:00Z");
    const from = new Date(to);
    from.setUTCDate(from.getUTCDate() - Number(days) + 1);
    dateFrom.value = from.toISOString().slice(0, 10);
    dateTo.value = max;
  }
  render();
}

document.getElementById("preset-row").addEventListener("click", (e) => {
  const preset = e.target.getAttribute("data-preset");
  if (preset) applyPreset(preset);
});
dateFrom.addEventListener("change", render);
dateTo.addEventListener("change", render);

productSelect.addEventListener("change", () => {
  populateResolutions();
  populateMarkets(false);
  applyPreset("all");
});
resolutionSelect.addEventListener("change", () => {
  populateMarkets(true);
  applyPreset("all");
});

function currentSeries() {
  const slug = productSelect.value;
  const resolution = resolutionSelect.value;
  const areas = checkedMarkets();
  const markets = DATA.specs[slug].markets;
  const out = [];
  for (const area of areas) {
    const s = markets[area] && markets[area][resolution];
    if (!s) continue;
    const from = dateFrom.value, to = dateTo.value;
    const points = s.points.filter((p) => {
      if (!p.t) return false;
      const d = p.t.slice(0, 10);
      return (!from || d >= from) && (!to || d <= to);
    });
    out.push({ area, metric: s.metric, currency: s.currency, points });
  }
  return out;
}

function baseLayout(extra) {
  const dark = isDark();
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "system-ui, -apple-system, Segoe UI, sans-serif",
             color: dark ? "#c3c2b7" : "#52514e", size: 12 },
    margin: { l: 56, r: 16, t: 8, b: 32 },
    hovermode: "x unified",
    hoverlabel: { bgcolor: dark ? "#1a1a19" : "#fcfcfb",
                  bordercolor: dark ? "#383835" : "#c3c2b7",
                  font: { color: dark ? "#ffffff" : "#0b0b0b" } },
    legend: { orientation: "h", y: 1.15, font: { size: 11 } },
    xaxis: { gridcolor: dark ? "#2c2c2a" : "#e1e0d9", showline: false, zeroline: false },
    yaxis: { gridcolor: dark ? "#2c2c2a" : "#e1e0d9", showline: false, zeroline: false,
              rangemode: "tozero" },
  }, extra || {});
}

function render() {
  const series = currentSeries();
  const priceTitle = document.getElementById("price-title");
  const main = document.getElementById("main");

  if (!series.length || series.every((s) => s.points.length === 0)) {
    Plotly.purge("price-chart");
    Plotly.purge("volume-chart");
    priceTitle.textContent = "Price";
    renderTable([]);
    return;
  }

  const metric = series.find((s) => s.metric)?.metric || "Price";
  const currencies = [...new Set(series.map((s) => s.currency).filter(Boolean))];
  priceTitle.textContent = metric + (currencies.length === 1 ? " (" + currencies[0] + "/MWh)" : "");

  const priceTraces = series.map((s) => ({
    x: s.points.map((p) => p.t),
    y: s.points.map((p) => p.p),
    name: s.area,
    mode: "lines",
    line: { width: 2, color: colorFor(s.area) },
    hovertemplate: "%{y:,.2f}<extra>" + s.area + "</extra>",
  }));

  const volumeTraces = series.map((s) => ({
    x: s.points.map((p) => p.t),
    y: s.points.map((p) => p.v),
    name: s.area,
    type: "bar",
    marker: { color: colorFor(s.area) },
    hovertemplate: "%{y:,.1f}<extra>" + s.area + "</extra>",
    showlegend: false,
  }));

  Plotly.react("price-chart", priceTraces, baseLayout({ yaxis: { gridcolor: isDark() ? "#2c2c2a" : "#e1e0d9" } }),
    { displaylogo: false, responsive: true });
  Plotly.react("volume-chart", volumeTraces,
    baseLayout({ barmode: "group", legend: { orientation: "h", y: 1.25, font: { size: 11 } } }),
    { displaylogo: false, responsive: true });

  renderTable(series);
}

function renderTable(series) {
  const table = document.getElementById("data-table");
  table.innerHTML = "";
  if (!series.length) {
    table.innerHTML = '<tr><td class="empty-state">No data for this selection.</td></tr>';
    return;
  }
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  ["Time", ...series.map((s) => s.area + " price"), ...series.map((s) => s.area + " volume")]
    .forEach((h) => {
      const th = document.createElement("th");
      th.textContent = h;
      headRow.appendChild(th);
    });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const allTimes = [...new Set(series.flatMap((s) => s.points.map((p) => p.t)))].sort();
  const byArea = series.map((s) => {
    const m = new Map(s.points.map((p) => [p.t, p]));
    return m;
  });
  const tbody = document.createElement("tbody");
  for (const t of allTimes.slice(-500)) {
    const tr = document.createElement("tr");
    const tdT = document.createElement("td");
    tdT.textContent = t;
    tr.appendChild(tdT);
    for (const m of byArea) {
      const td = document.createElement("td");
      const pt = m.get(t);
      td.textContent = pt && pt.p != null ? pt.p.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "";
      tr.appendChild(td);
    }
    for (const m of byArea) {
      const td = document.createElement("td");
      const pt = m.get(t);
      td.textContent = pt && pt.v != null ? pt.v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "";
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
}

document.getElementById("toggle-table").addEventListener("click", (e) => {
  const card = document.getElementById("table-card");
  const showing = card.style.display !== "none";
  card.style.display = showing ? "none" : "block";
  e.target.classList.toggle("active", !showing);
});

document.getElementById("toggle-theme").addEventListener("click", (e) => {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  e.target.classList.toggle("active", next === "dark");
  render();
});

// --- init ---
if (slugs.length === 0) {
  document.getElementById("main").innerHTML =
    '<p class="empty-state">No CSV data found under the data directory this dashboard was built from.</p>';
} else {
  productSelect.value = slugs[0];
  populateResolutions();
  populateMarkets(false);
  applyPreset("all");
}
</script>
</body>
</html>
"""


def build_html(payload: dict, generated_at: str) -> str:
    return (PAGE_TEMPLATE
            .replace("__DATA_JSON__", json.dumps(payload, separators=(",", ":")))
            .replace("__GENERATED_AT__", generated_at))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build a self-contained interactive HTML dashboard from scraped CSVs.")
    p.add_argument("--data-dir", default="data", help="scraped data root (default: data)")
    p.add_argument("--output", default="dashboard.html", help="HTML file to write (default: dashboard.html)")
    p.add_argument("--specs", type=_parse_csv_list,
                    help="comma-separated output slugs to include (default: all found)")
    p.add_argument("--market-areas", type=_parse_csv_list,
                    help="comma-separated market areas to include (default: all found)")
    p.add_argument("--open", action="store_true", help="open the dashboard in a browser after writing it")
    return p


def main(argv: list[str] | None = None) -> int:
    from datetime import datetime, timezone

    args = build_arg_parser().parse_args(argv)
    data_dir = Path(args.data_dir)
    payload = collect_series(data_dir, args.specs, args.market_areas)

    n_series = sum(
        len(res_map)
        for spec in payload["specs"].values()
        for res_map in spec["markets"].values()
    )
    if n_series == 0:
        print(f"warning: no CSV files found under {data_dir}", flush=True)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = build_html(payload, generated_at)

    out_path = Path(args.output)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path} ({n_series} market/resolution series)")

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
