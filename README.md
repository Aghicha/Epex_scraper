# EPEX SPOT market-results scraper

A self-contained daily cron scraper for the public
[EPEX SPOT market results](https://www.epexspot.com/en/market-results).

It captures **all market areas (countries), trading products and instruments**,
normalises them to a tidy/long format, and stores them as **deduplicated,
per-delivery-date CSV files committed straight into this repository** by a
GitHub Actions cron job. EPEX only keeps ~3 days of data online; running daily
turns that rolling window into a permanent, versioned archive.

## How it works

```
GitHub Actions (daily cron)
        │
        ▼
python -m epex_scraper.scrape
        │  for every  instrument × market_area × resolution × delivery_date
        ▼
  fetch market-results HTML  ──►  parse tables to long records  ──►  write CSV
        │                                                              │
        └──────────  skip already-settled, already-stored days  ◄──────┘
        │
        ▼
   git add data/ && commit && push   (only if something actually changed)
```

### What gets captured

| Dimension | Values | Config |
|-----------|--------|--------|
| **Countries / market areas** | AT, BE, CH, DE-LU, DK1/2, FI, FR, GB, NL, NO1–5, PL, SE1–4 | `MARKET_AREAS` |
| **Products / instruments** | Day-ahead (MRC, GB-DAA, CH-DAA), Intraday auctions (IDA1/2/3), Intraday continuous | `QUERY_SPECS` |
| **Resolution** | 60 / 30 / 15 minutes | `PRODUCTS` |
| **Delivery dates** | rolling window around today (default −2 … +2) | `--days-back` / `--days-forward` |

Every combination is attempted; combinations that don't exist (e.g. GB has no
MRC day-ahead) simply return no table and are skipped. See
[`epex_scraper/config.py`](epex_scraper/config.py) to widen or narrow the scope.

### Deduplication

The dedup unit is a single file:

```
data/<instrument>/<market_area>/p<resolution>/<delivery_date>.csv
```

* Each delivery day maps to exactly one file, so re-scraping the same day just
  rewrites the same path — history never duplicates.
* Writes are **idempotent**: if freshly scraped data equals what's on disk
  (ignoring the `scraped_at` timestamp), the file is left untouched, so
  unchanged days produce **no git diff and no commit**.
* Days that are already stored **and** older than `--settle-days` (default 2)
  are not re-fetched at all — day-ahead results are final once published.

### Output schema (long / tidy)

One row per `(delivery period, metric)`:

| column | example |
|--------|---------|
| `market_area` | `DE-LU` |
| `modality` / `sub_modality` / `auction` | `Auction` / `DayAhead` / `MRC` |
| `product` | `60` |
| `delivery_date` / `trading_date` | `2026-07-09` / `2026-07-08` |
| `period_index` / `period_label` / `period_start` | `0` / `00 - 01` / `2026-07-09T00:00:00` |
| `metric` / `unit` | `price` / `€/MWh` |
| `value` / `value_raw` | `45.67` / `45.67` |
| `source_url` / `scraped_at` | the request URL / UTC ISO timestamp |

Both the parsed `value` and the original `value_raw` string are stored, so no
information is lost even if a locale/number-format assumption is off.

## Running locally

```bash
pip install -r requirements.txt

# Full scrape into ./data
python -m epex_scraper.scrape --data-dir data

# Narrow scope while testing
python -m epex_scraper.scrape --specs dayahead-mrc --market-areas DE-LU,FR \
    --products 60 --days-back 1 --days-forward 1

# Backfill a specific historical "today" (only works while EPEX still serves it)
python -m epex_scraper.scrape --today 2026-07-08

# Keep raw HTML for debugging the parser
python -m epex_scraper.scrape --save-raw raw/ --specs dayahead-mrc \
    --market-areas DE-LU --products 60 --days-back 0 --days-forward 0
```

Key flags: `--days-back`, `--days-forward`, `--settle-days`, `--market-areas`,
`--products`, `--specs`, `--sleep`, `--save-raw`, `--today`, `--log-level`.
Run `python -m epex_scraper.scrape --help` for the full list.

## The cron job

[`.github/workflows/scrape.yml`](.github/workflows/scrape.yml) runs daily at
**22:00 UTC** and can also be triggered manually
(**Actions → Scrape EPEX market results → Run workflow**) with custom
`days_back` / `days_forward` for backfills. It commits and pushes changed data
using the built-in `GITHUB_TOKEN` (needs no secrets). A separate
[`ci.yml`](.github/workflows/ci.yml) runs the tests on every push and PR.

## Tests

```bash
pip install -r requirements.txt pytest
python -m pytest -q
```

The tests exercise the HTML parser and the dedup/idempotency logic offline
against a fixture, so they need no network access.

## Troubleshooting 403 (Forbidden)

EPEX sits behind a WAF/bot filter. If you see repeated
`403 Client Error: Forbidden`:

* **Browser headers are already sent.** The client uses a real Chrome
  `User-Agent`, `Sec-Fetch-*`/`sec-ch-ua` hints and warms up session cookies by
  loading the landing page first. 403s are **not retried** (retrying only
  hammers the WAF), and the run **aborts fast** after `--max-forbidden`
  consecutive 403s (default 20) instead of grinding for an hour.
* **Try a different User-Agent** if EPEX rotates its rules:
  `--user-agent "Mozilla/5.0 … Chrome/126.0.0.0 …"`.
* **Blocked source IP (most common in CI).** WAFs frequently block datacenter
  IP ranges — including GitHub Actions (Azure) runners — so requests that work
  from your laptop 403 from the cron. If the run 403s from Actions but not
  locally, route through a residential/rotating proxy: the client honours the
  standard `HTTPS_PROXY` / `HTTP_PROXY` environment variables. In the workflow,
  add a proxy secret and set it in the `Scrape` step's `env:`.
* Increase `--sleep` to be gentler if you suspect rate-based blocking.

The run exits with code **2** when it is blocked (vs **1** for pure network
failure), so a failed cron clearly distinguishes "we're blocked" from "EPEX was
down".

## Notes & caveats

* **Terms of use** — EPEX publishes this data for internal use; commercial
  redistribution requires their approval. The scraper rate-limits itself
  (`--sleep`, default 1.5 s) to stay a polite consumer. Review EPEX's terms
  before publishing the archive.
* **Parser robustness** — the market-results DOM differs across products and
  changes over time. The parser is heuristic (it picks the richest table and
  keeps raw values) rather than pinned to fixed columns. If EPEX changes its
  layout, run with `--save-raw` and adjust
  [`epex_scraper/parser.py`](epex_scraper/parser.py); the stored `value_raw`
  column means earlier data stays usable regardless.
* **Auction codes** — `QUERY_SPECS` lists the known instrument codes. Broadening
  it is safe: unknown/invalid combinations are skipped automatically.
