# EPEX SPOT market-results scraper

A self-contained daily cron scraper for the public
[EPEX SPOT market results](https://www.epexspot.com/en/market-results).

It captures **all market areas (countries), trading products and instruments**,
reshapes each into the same **wide table EPEX shows on the site**, and stores
them as **deduplicated, per-delivery-date CSV files committed straight into this
repository** by a GitHub Actions cron job. EPEX only keeps ~3 days of data
online; running daily turns that rolling window into a permanent, versioned
archive.

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

The valid market areas and auction codes are **context-dependent** (they differ
per modality) and were read from EPEX's own filter form, so each instrument
only enumerates the areas/resolutions it actually offers:

| Instrument (`slug`) | Auction | Market areas | Resolutions |
|---|---|---|---|
| Day-ahead SDAC (`day-ahead`) | `MRC` | AT, BE, DE-LU, DK1/2, FI, FR, NL, NO1–5, PL, SE1–4 | 60, 15 |
| GB day-ahead (`day-ahead-gb`, `-gb-30`) | `GB`, `30-call-GB` | GB | 60 / 30 |
| CH day-ahead (`day-ahead-ch`) | `CH` | CH | 60, 15 |
| Intraday auctions (`intraday-ida1/2/3`) | `IDA1/2/3` | SDAC zones | 15 |
| CH / GB intraday auctions | `CH-IDA1/2`, `GB-IDA1/2` | CH / GB | 15 / 60 |
| Continuous intraday (`continuous`) | – | AT, BE, CH, DE, DK1/2, EE, FI, FR, LT, LV, NL, NO1–5, PL, SE1–4 | 60, 30, 15 |

Notes:
* Day-ahead uses **`DE-LU`**; continuous uses **`DE`** — different zone sets.
* Continuous embeds all three resolutions in one page and hides the unselected
  ones via CSS; the parser filters to the requested resolution by row class.
* Continuous carries extra columns (Low, High, Last, Weight Avg, ID Full, ID1,
  ID3) alongside Buy/Sell Volume and Volume.

Combinations without data return a no-data page and are skipped. See
[`epex_scraper/config.py`](epex_scraper/config.py) to widen or narrow the scope.

### Storage layout & deduplication

Files are organised **per product, then per market, then per day** — the dedup
unit is one file:

```
data/<product>/<market_area>/<delivery_date>_<resolution>min.csv
```

e.g. `data/day-ahead/DE-LU/2026-07-09_60min.csv`.

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
python -m epex_scraper.scrape --specs day-ahead --market-areas DE-LU,FR \
    --products 60 --days-back 1 --days-forward 1

# Backfill a specific historical "today" (only works while EPEX still serves it)
python -m epex_scraper.scrape --today 2026-07-08

# Keep raw HTML for debugging the parser
python -m epex_scraper.scrape --save-raw raw/ --specs day-ahead \
    --market-areas DE-LU --products 60 --days-back 0 --days-forward 0
```

Key flags: `--days-back`, `--days-forward`, `--settle-days`, `--market-areas`,
`--products`, `--specs`, `--sleep`, `--save-raw`, `--today`, `--log-level`.
Run `python -m epex_scraper.scrape --help` for the full list.

## Diagnosing missing data (coverage)

If a product/market yields no file, inspect one combination with the debug tool.
It prints the page size, the Hours list length, the values-table shape, and how
many records the parser extracted:

```bash
python -m epex_scraper.debug --specs day-ahead --market-areas DE-LU \
    --products 60 --delivery-date 2026-07-08 --save-raw /tmp/epex.html
```

Typical causes of an empty result:

* **404 / genuine no-data** — that market doesn't trade that product/resolution
  on that day. EPEX serves a page with a `no-data-section`; the parser returns
  no rows (expected, and *not* retried).
* **403** — see *Troubleshooting 403* below.
* **Rate-limiting (the big one)** — EPEX enforces a **strict per-IP limit**:
  after only a handful of requests it returns tiny placeholder pages, from *any*
  IP (residential or datacenter). The scraper handles this automatically:
  * a **cooldown pause** every `--burst` requests (default 4 / `--cooldown` 30 s)
    keeps you under the limit proactively;
  * if a throttle still slips through, it **waits `--throttle-wait` seconds
    (default 60) and retries** — a throttle never aborts the run.

  A full backfill is therefore slow but unattended; because runs are
  **resumable** (already-stored days are skipped), just re-run to fill any days
  a run couldn't reach. Tune `--burst` / `--cooldown` up if you still see
  `rate-limited` warnings.
* **`values table … NOT FOUND` with a real-size page** — EPEX changed the
  results markup. The saved `--save-raw` HTML shows the new structure; adjust
  the selectors in [`epex_scraper/parser.py`](epex_scraper/parser.py).

The run's tallies (`written` / `unchanged` / `empty` / `throttled` /
`forbidden` / `error`) are logged as the final `run summary` line and saved to
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

* **A browser User-Agent is already sent** (plus a `Referer`), which avoids the
  WAF 403 that non-browser clients get. 403s are **not retried** (retrying only
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
