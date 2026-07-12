# EPEX SPOT market-results scraper

A self-contained cron scraper for the public
[EPEX SPOT market results](https://www.epexspot.com/en/market-results).

It captures **all market areas (countries), trading products and instruments**,
reshapes each into the same **wide table EPEX shows on the site**, and stores
them as **deduplicated, per-delivery-date CSV files committed straight into this
repository** by a GitHub Actions cron job. EPEX only publishes a **rolling
3-day window** (yesterday, today, tomorrow) of results; running frequently
turns that window into a permanent, versioned archive.

## How it works

```
GitHub Actions (cron, every 15 min)
        │
        ▼
python -m epex_scraper.scrape
        │  for every  instrument × market_area × resolution × delivery_date
        │  (never-fetched combos first, then refreshing already-stored ones)
        ▼
  fetch market-results HTML  ──►  parse tables to long records  ──►  write CSV
        │                                                              │
        └──────────  skip already-settled, already-stored days  ◄──────┘
        │
        ▼
   git add data/ && commit && push   (only if something actually changed)
```

EPEX enforces a strict per-IP rate limit — only a handful of requests before
sustained throttling that doesn't clear within a single run. A throttled combo
is **retried until it actually succeeds**, never skipped — see *Rate-limiting*
below for why, and for `--proxies` as the real fix for a sustained limit.
Never-fetched combinations are still attempted **before** refreshing
already-stored ones, so a run's early progress goes toward expanding
coverage rather than re-checking what's already on disk.

### What gets captured

The valid market areas and auction codes are **context-dependent** (they differ
per modality) and were read from EPEX's own filter form, so each instrument
only enumerates the areas/resolutions it actually offers:

EPEX needs a different `auction` filter code per market area even within the
same conceptual instrument (SDAC-coupled zones use `MRC`, but GB/CH have their
own standalone auctions), so each variant is still fetched with its own
params — but all variants of one instrument share a single output `slug` and
write into the same `data/<slug>/` tree, split only by market area:

| Output slug | Variants (auction codes) | Market areas | Resolutions |
|---|---|---|---|
| `day-ahead` | `MRC` (SDAC), `GB`, `30-call-GB`, `CH` | AT, BE, DE-LU, DK1/2, FI, FR, NL, NO1–5, PL, SE1–4, GB, CH | 60, 15 (GB: 60/30) |
| `intraday-ida1` | `IDA1` (SDAC), `CH-IDA1`, `GB-IDA1` | SDAC zones, CH, GB | 15 (GB: 60) |
| `intraday-ida2` | `IDA2` (SDAC), `CH-IDA2`, `GB-IDA2` | SDAC zones, CH, GB | 15 (GB: 60) |
| `intraday-ida3` | `IDA3` (SDAC only) | SDAC zones | 15 |
| `continuous` | – (no auction) | AT, BE, CH, DE, DK1/2, EE, FI, FR, LT, LV, NL, NO1–5, PL, SE1–4 | 60, 30, 15 |

Notes:
* Day-ahead uses **`DE-LU`**; continuous uses **`DE`** — different zone sets.
* Continuous embeds all three resolutions in one page and hides the unselected
  ones via CSS; the parser filters to the requested resolution by row class.
* Continuous carries extra columns (Low, High, Last, Weight Avg, ID Full, ID1,
  ID3) alongside Buy/Sell Volume and Volume.
* `--specs` filters by slug, so `--specs day-ahead` now pulls in every
  day-ahead variant (SDAC + GB + CH) together, not just the SDAC one.

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

# Full scrape into ./data — defaults to EPEX's published window: yesterday,
# today and tomorrow (--days-back 1 --days-forward 1)
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

Key flags: `--days-back`, `--days-forward` (default 1/1 — EPEX only ever
publishes yesterday/today/tomorrow; requesting further out risks EPEX silently
serving a nearby day's page, which the parser now detects and discards rather
than mislabeling), `--settle-days`, `--market-areas`, `--products`, `--specs`,
`--sleep`, `--proxies`, `--save-raw`, `--today`, `--log-level`.
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
  IP (residential or datacenter), and the limit does **not** reliably clear
  within one run even with long waits. A throttled combo is **retried until it
  actually succeeds** — it is never skipped in favour of moving on to the next
  one — via a few layers, cheap enough to loop indefinitely without hammering
  EPEX:
  * a **cooldown pause** every `--burst` requests (default 4 / `--cooldown` 30 s)
    keeps you under the limit proactively;
  * per HTTP request, a throttle/shell response gets a couple of quick, fixed
    3 s retries (`config.THROTTLE_RETRIES` / `THROTTLE_PAUSE`) — enough to
    smooth a one-off blip, not enough to burn real time on a limit that isn't
    clearing;
  * one level up, if still throttled, the pacer **waits `--throttle-wait`
    seconds (default 15) and retries** the combo up to `--throttle-retries`
    times (default 1) before logging and cycling through the layers again —
    `run()` keeps doing this for the *same* combo for as long as it takes.

  Because the scraper never gives up on a combo, a sustained, unresolvable
  block (rather than an ordinary rolling limit) can make a run take a long
  time — there is deliberately no cap. If you need a bounded run (e.g. a
  strict CI timeout), the fix is **not using the same IP twice**, below —
  not a retry limit.

  **Set `--proxies` (or the `EPEX_PROXIES` env var)** to a comma-separated
  list of proxy URLs and the scraper round-robins one proxy per request
  (`client.ProxyRotator`), so no single egress IP ever sees enough traffic to
  trip the limit — and once a pool is configured, a throttled combo is
  retried on a *different* proxy immediately instead of waiting, since
  waiting can't help an IP that was never actually capped. This needs a
  proxy provider (residential proxies work best; EPEX WAF-blocks many
  datacenter ranges outright — see *Troubleshooting 403*). In the GitHub
  Actions workflow, set an `EPEX_PROXIES` repo secret and uncomment the `env:`
  line in `scrape.yml`. Without a pool, `HTTP(S)_PROXY` env vars still work
  for a single static proxy as before, or widen `--cooldown` /
  `--throttle-wait` if you'd rather just wait longer on the one IP you have.
* **`values table … NOT FOUND` with a real-size page** — EPEX changed the
  results markup. The saved `--save-raw` HTML shows the new structure; adjust
  the selectors in [`epex_scraper/parser.py`](epex_scraper/parser.py).

The run's tallies (`written` / `unchanged` / `empty` / `forbidden` / `error` /
`throttle_retries`) are logged as the final `run summary` line and saved to
`data/_manifest/last_run.json`. `throttle_retries` counts total wait-and-retry
cycles spent on throttled combos — since those are retried until they
succeed, it's a count of retries, not a terminal outcome.

## The cron job

[`.github/workflows/scrape.yml`](.github/workflows/scrape.yml) runs **every 15
minutes** and can also be triggered manually
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
