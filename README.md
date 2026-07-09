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

### Storage layout & deduplication

Files are organised **per product, then per market, then per day** — the dedup
unit is one file:

```
data/<product>/<market_area>/<delivery_date>_<resolution>min.csv
```

e.g. `data/dayahead-mrc/DE-LU/2026-07-09_60min.csv`.

* Each delivery day maps to exactly one file, so re-scraping the same day just
  rewrites the same path — history never duplicates.
* Writes are **idempotent**: identical content is not rewritten, so unchanged
  days produce **no git diff and no commit**.
* Days already stored **and** older than `--settle-days` (default 2) are not
  re-fetched at all — day-ahead results are final once published.

### Output format (wide — mirrors the EPEX table)

**One row per delivery period**, exactly like the table on the website:

| delivery_date | market_area | hours | Buy Volume (MWh) | Sell Volume (MWh) | Volume (MWh) | Price (€/MWh) | period_start |
|---|---|---|---|---|---|---|---|
| 2026-07-09 | DE-LU | 00:00 - 00:15 | 0.0 | 9.2 | 9.2 | 131.92 | 2026-07-09T00:00:00 |
| 2026-07-09 | DE-LU | 00:15 - 00:30 | 0.0 | 5.3 | 5.3 | 133.53 | 2026-07-09T00:15:00 |

The metric columns are whatever that product exposes, in EPEX's own order —
day-ahead / intraday auctions show Buy/Sell Volume, Volume and Price; continuous
intraday adds Low / High / Last / Weighted Avg / ID indices. `market_area`,
product and resolution are also encoded in the file path (partition-key style).

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

## Diagnosing missing data (coverage)

If a product/market yields no file, inspect one combination with the debug tool.
It prints every table EPEX returned, whether the parser found a time column, and
how many records it extracted:

```bash
python -m epex_scraper.debug --specs dayahead-mrc --market-areas DE-LU \
    --products 60 --delivery-date 2026-07-08 --save-raw /tmp/epex.html
```

Typical causes of an empty result:

* **404 / genuine no-data** — that market doesn't trade that product/resolution
  on that day. EPEX serves a page with a `no-data-section`; the parser returns
  no rows (expected, and *not* retried).
* **403** — see *Troubleshooting 403* below.
* **Throttling** — under load EPEX intermittently returns a tiny placeholder
  page or a table-less JS shell (neither the results table nor a no-data
  message). The client detects these (`is_valid_page`) and **retries with
  backoff**; raise `--sleep` if you still see `throttle/shell` warnings on big
  runs.
* **`values table … NOT FOUND` with a real-size page** — EPEX changed the
  results markup. The saved `--save-raw` HTML shows the new structure; adjust
  the selectors in [`epex_scraper/parser.py`](epex_scraper/parser.py).

The run's tallies (`written` / `unchanged` / `empty` / `forbidden` / `error`)
are logged as the final `run summary` line and saved to
`data/_manifest/last_run.json`.

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
  (`--sleep`, default 2 s) to stay a polite consumer and avoid throttling.
  Review EPEX's terms before publishing the archive.
* **Parser** — the results widget renders Hours in a `<ul>` and values in a
  separate `<table>` (verified against the live site); the parser reads both
  with BeautifulSoup and aligns them by position, so it works across day-ahead,
  intraday auctions and continuous. It keeps `value_raw` alongside the parsed
  `value`. If EPEX changes its markup, run with `--save-raw` and adjust the
  selectors in [`epex_scraper/parser.py`](epex_scraper/parser.py).
* **Auction codes** — `QUERY_SPECS` lists the known instrument codes. Broadening
  it is safe: unknown/invalid combinations are skipped automatically.
