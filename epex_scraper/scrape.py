"""Orchestrate a full scrape run and write deduplicated files.

Run as::

    python -m epex_scraper.scrape --data-dir data

It walks the cartesian product of instruments (``QUERY_SPECS``) x market areas
x contract resolutions (``PRODUCTS``) x the rolling delivery-date window that
EPEX publishes (~3 days), fetches each table, parses it and writes one file per
``(instrument, area, product, delivery_date)``.  Already-settled days that are
already stored are skipped, so steady-state daily runs only touch the newest
day and never duplicate history.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import client, config, storage
from .config import QuerySpec
from .parser import parse_market_results

logger = logging.getLogger("epex_scraper")


def _delivery_dates(today: date, days_back: int, days_forward: int) -> list[date]:
    return [today + timedelta(days=d) for d in range(-days_back, days_forward + 1)]


def _select_specs(slugs: list[str] | None) -> list[QuerySpec]:
    if not slugs:
        return config.QUERY_SPECS
    wanted = set(slugs)
    return [s for s in config.QUERY_SPECS if s.slug in wanted]


def run(args: argparse.Namespace) -> int:
    today = args.today or datetime.now(timezone.utc).date()
    data_dir = Path(args.data_dir)
    raw_dir = Path(args.save_raw) if args.save_raw else None

    specs = _select_specs(args.specs)
    areas = args.market_areas or config.MARKET_AREAS
    products = args.products or config.PRODUCTS
    delivery_dates = _delivery_dates(today, args.days_back, args.days_forward)

    if args.user_agent:
        config.USER_AGENT = args.user_agent
    session = client.make_session()
    stats: Counter[str] = Counter()
    started = datetime.now(timezone.utc)

    logger.info(
        "run start: %d specs x %d areas x %d products x %d days (today=%s)",
        len(specs), len(areas), len(products), len(delivery_dates), today,
    )

    consecutive_forbidden = 0
    aborted = False
    for spec in specs:
        if aborted:
            break
        spec_areas = [a for a in areas if a in spec.market_areas]
        for market_area in spec_areas:
            if aborted:
                break
            for product in products:
                if aborted:
                    break
                for delivery_date in delivery_dates:
                    path = storage.partition_path(
                        data_dir, spec.slug, market_area, product, delivery_date
                    )
                    if path.exists() and storage.is_settled(
                        delivery_date, today, args.settle_days
                    ):
                        stats["skipped_settled"] += 1
                        continue

                    outcome = _scrape_one(
                        session, spec, market_area, product, delivery_date,
                        data_dir, raw_dir, args.sleep,
                    )
                    stats[outcome] += 1

                    # Circuit breaker: if EPEX blocks us (403) many times in a
                    # row, stop early instead of hammering the WAF for an hour.
                    if outcome == "forbidden":
                        consecutive_forbidden += 1
                        if consecutive_forbidden >= args.max_forbidden:
                            logger.error(
                                "aborting: %d consecutive 403s — EPEX is refusing "
                                "requests (bot/WAF block or blocked source IP)",
                                consecutive_forbidden,
                            )
                            aborted = True
                            break
                    else:
                        consecutive_forbidden = 0

    stats["duration_s"] = int((datetime.now(timezone.utc) - started).total_seconds())
    _report(stats, started, today, data_dir, args)

    # Fail loudly if EPEX blocked us or every request errored — that is a real
    # problem to fix, not "no data today".
    attempted = (stats["written"] + stats["unchanged"] + stats["empty"]
                 + stats["error"] + stats["forbidden"])
    if aborted or (attempted > 0 and stats["forbidden"] == attempted):
        logger.error(
            "run failed: %d forbidden, %d errors out of %d attempts. "
            "See the README 'Troubleshooting 403' section.",
            stats["forbidden"], stats["error"], attempted,
        )
        return 2
    if attempted > 0 and stats["error"] == attempted:
        logger.error("all %d fetch attempts failed (network)", attempted)
        return 1
    return 0


def _scrape_one(session, spec: QuerySpec, market_area: str, product: int,
                delivery_date: date, data_dir: Path, raw_dir: Path | None,
                sleep_s: float) -> str:
    params = client.build_params(spec, market_area, delivery_date, product)
    source_url = f"{config.BASE_URL}?" + "&".join(
        f"{k}={v}" for k, v in params.items() if v != ""
    )
    try:
        html = client.fetch(session, spec, market_area, delivery_date, product)
    except client.AccessForbidden:
        logger.warning(
            "403 forbidden %s %s p%s %s", spec.slug, market_area, product, delivery_date
        )
        return "forbidden"
    except Exception as exc:  # network exhausted retries
        logger.warning(
            "fetch error %s %s p%s %s: %s",
            spec.slug, market_area, product, delivery_date, exc,
        )
        return "error"
    finally:
        if sleep_s:
            time.sleep(sleep_s)

    if html is None:
        return "empty"

    if raw_dir is not None:
        _dump_raw(raw_dir, spec, market_area, product, delivery_date, html)

    meta = {
        "market_area": market_area,
        "modality": spec.modality,
        "sub_modality": spec.sub_modality,
        "auction": spec.auction,
        "product": product,
        "delivery_date": delivery_date,
        "trading_date": params.get("trading_date", ""),
        "source_url": source_url,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    records = parse_market_results(html, meta)
    return storage.write_partition(
        data_dir, spec.slug, market_area, product, delivery_date, records
    )


def _dump_raw(raw_dir: Path, spec: QuerySpec, market_area: str, product: int,
              delivery_date: date, html: str) -> None:
    out = raw_dir / spec.slug / market_area / f"p{product}" / f"{delivery_date}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def _report(stats: Counter, started: datetime, today: date, data_dir: Path,
            args: argparse.Namespace) -> None:
    summary = {
        "started_at": started.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "window": {"days_back": args.days_back, "days_forward": args.days_forward},
        "stats": dict(stats),
    }
    logger.info("run summary: %s", json.dumps(summary["stats"]))
    manifest = data_dir / "_manifest"
    manifest.mkdir(parents=True, exist_ok=True)
    (manifest / "last_run.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def _parse_csv_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Scrape EPEX SPOT market results into deduplicated files."
    )
    p.add_argument("--data-dir", default="data", help="output root (default: data)")
    p.add_argument("--days-back", type=int, default=2,
                   help="delivery days before today to fetch (default: 2)")
    p.add_argument("--days-forward", type=int, default=2,
                   help="delivery days after today to fetch (default: 2)")
    p.add_argument("--settle-days", type=int, default=2,
                   help="days after which stored data is treated as final "
                        "and not re-fetched (default: 2)")
    p.add_argument("--market-areas", type=_parse_csv_list,
                   help="comma-separated subset of market areas (default: all)")
    p.add_argument("--products", type=lambda v: [int(x) for x in _parse_csv_list(v)],
                   help="comma-separated resolutions e.g. 60,15 (default: all)")
    p.add_argument("--specs", type=_parse_csv_list,
                   help="comma-separated instrument slugs (default: all)")
    p.add_argument("--sleep", type=float, default=config.REQUEST_SLEEP,
                   help="seconds to sleep between requests (default: %(default)s)")
    p.add_argument("--max-forbidden", type=int, default=20,
                   help="abort after this many consecutive 403s (default: 20)")
    p.add_argument("--user-agent",
                   help="override the browser User-Agent sent to EPEX")
    p.add_argument("--save-raw", metavar="DIR",
                   help="also dump raw HTML responses to DIR (for debugging)")
    p.add_argument("--today", type=date.fromisoformat,
                   help="override 'today' (YYYY-MM-DD), for testing/backfill")
    p.add_argument("--log-level", default="INFO",
                   help="logging level (default: INFO)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
