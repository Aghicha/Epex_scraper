"""Diagnose a single market-results fetch.

Fetches one (product, market, resolution, delivery_date) combination and prints
a compact report of every HTML table EPEX returned — its shape, headers, and
whether the parser recognises a time column — plus the number of records the
parser would extract. Use this to understand why a combination yields no data.

Example::

    python -m epex_scraper.debug --specs day-ahead --market-areas DE-LU \\
        --products 60 --delivery-date 2026-07-08

Paste its (short) output when reporting coverage problems.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

from . import client, config
from .parser import parse_market_results

logger = logging.getLogger("epex_scraper.debug")


def _report(html: str, meta: dict) -> None:
    soup = BeautifulSoup(html, "lxml")
    times = soup.select(".js-table-times ul li")
    values = soup.select_one(".js-table-values table") or soup.select_one("table.table-01")
    print(f"  html size: {len(html)} bytes")
    print(f"  hours list (.js-table-times li): {len(times)} entries")
    if values is None:
        print("  values table (.js-table-values table): NOT FOUND")
    else:
        tbody = values.find("tbody")
        rows = tbody.find_all("tr", recursive=False) if tbody else []
        ncols = len(rows[0].find_all("td")) if rows else 0
        print(f"  values table: {len(rows)} data rows x {ncols} cols")
    records = parse_market_results(html, meta)
    print(f"  parser extracted {len(records)} records")
    if records:
        r = records[0]
        print(f"    e.g. hours={r['period_label']!r} metric={r['metric']!r} "
              f"value={r['value']!r} unit={r['unit']!r}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--specs", default="day-ahead",
                   help="single instrument slug (default: day-ahead)")
    p.add_argument("--market-areas", default="DE-LU", help="single market area")
    p.add_argument("--products", type=int, default=60, help="resolution (default: 60)")
    p.add_argument("--delivery-date", type=date.fromisoformat,
                   default=date.today(), help="delivery date YYYY-MM-DD")
    p.add_argument("--user-agent", help="override the browser User-Agent")
    p.add_argument("--save-raw", metavar="FILE", help="write the raw HTML to FILE")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.user_agent:
        config.USER_AGENT = args.user_agent

    spec = next((s for s in config.QUERY_SPECS if s.slug == args.specs), None)
    if spec is None:
        print(f"unknown spec {args.specs!r}; choices: "
              f"{', '.join(s.slug for s in config.QUERY_SPECS)}")
        return 2

    session = client.make_session()
    params = client.build_params(spec, args.market_areas, args.delivery_date, args.products)
    url = config.BASE_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items() if v != "")
    print(f"GET {url}")
    try:
        html = client.fetch(session, spec, args.market_areas, args.delivery_date, args.products)
    except client.AccessForbidden:
        print("  403 Forbidden — EPEX blocked this request (see README 'Troubleshooting 403')")
        return 2
    if html is None:
        print("  404 — combination does not exist")
        return 0

    if args.save_raw:
        with open(args.save_raw, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"  raw HTML saved to {args.save_raw} ({len(html)} bytes)")

    meta = {
        "market_area": args.market_areas, "modality": spec.modality,
        "sub_modality": spec.sub_modality, "auction": spec.auction,
        "product": args.products, "delivery_date": args.delivery_date,
        "trading_date": params.get("trading_date", ""), "source_url": url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _report(html, meta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
