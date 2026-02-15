# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "playwright>=1.40",
#     "playwright-stealth>=1.0",
#     "beautifulsoup4>=4.12",
# ]
# ///
"""
eBay sold-listing scraper for retro / vintage IC chips.

Supports multiple chip families (SID, VIC-II, Amiga custom chips,
Yamaha sound chips, TI SN76489, Ricoh 2A03) plus a discovery mode
to find other retro ICs changing hands.

Uses Playwright with stealth patches to bypass eBay's bot protection.
Scrapes completed/sold listings from eBay (.com, .co.uk, .de) to
estimate market demand and pricing for original chips.

Prerequisites:
    uv run --with playwright python -m playwright install chromium

Usage:
    uv run retro_ic_scraper.py                          # all families, 2 pages
    uv run retro_ic_scraper.py --chips sid vic-ii        # specific families
    uv run retro_ic_scraper.py --chips discover --min-price 20
    uv run retro_ic_scraper.py --pages 5 --sites com     # more pages, one site
    uv run retro_ic_scraper.py --dry-run                 # show URLs, don't fetch
"""

import argparse
import csv
import logging
import re
import time
import random
from dataclasses import dataclass, fields
from datetime import datetime
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page
from playwright_stealth import Stealth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Chip family catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChipFamily:
    name: str
    queries: list[str]
    exclude: list[str]
    variants: dict[str, str]  # title substring -> label


GLOBAL_EXCLUSIONS = [
    "replacement",
    "replica",
    "clone",
    "fpga",
    "emulator",
]

CHIP_FAMILIES: dict[str, ChipFamily] = {
    "sid": ChipFamily(
        name="MOS SID",
        queries=[
            "MOS 6581 SID",
            "MOS 8580 SID",
            "SID chip Commodore 64",
            "6581 sound chip",
            "8580 sound chip",
            "MOS 6581R4",
            "MOS 8580R5",
        ],
        exclude=[
            "sidkick", "swinsid", "armsid", "fpgasid", "arm2sid",
            "nano sid", "nanosid", "x-sid", "xsid", "mixsid",
        ],
        variants={"6581": "6581", "8580": "8580"},
    ),
    "vic-ii": ChipFamily(
        name="MOS VIC-II",
        queries=[
            "MOS 6567 VIC",
            "MOS 6569 VIC",
            "MOS 8562",
            "MOS 8565",
            "VIC-II chip",
        ],
        exclude=["vic-20"],
        variants={"6567": "6567", "6569": "6569", "8562": "8562", "8565": "8565"},
    ),
    "denise": ChipFamily(
        name="Amiga Denise",
        queries=[
            "Amiga Denise 8362",
            "Amiga Denise 8373",
            "Super Denise",
            "MOS 8362",
            "MOS 8373",
        ],
        exclude=[],
        variants={"8362": "8362", "8373": "8373 (Super)"},
    ),
    "paula": ChipFamily(
        name="Amiga Paula",
        queries=[
            "Amiga Paula 8364",
            "MOS 8364 Paula",
        ],
        exclude=[],
        variants={"8364": "8364"},
    ),
    "agnus": ChipFamily(
        name="Amiga Agnus",
        queries=[
            "Amiga Agnus 8361",
            "Amiga Agnus 8370",
            "Amiga Agnus 8372",
            "Amiga Agnus 8375",
            "Fat Agnus",
            "MOS 8372",
        ],
        exclude=[],
        variants={
            "8361": "8361", "8370": "8370",
            "8372": "8372", "8375": "8375",
        },
    ),
    "ym2151": ChipFamily(
        name="Yamaha YM2151",
        queries=[
            "Yamaha YM2151",
            "YM2151 OPM",
            "YM2151 sound chip",
        ],
        exclude=["breakout board", "module", "synth"],
        variants={},
    ),
    "ym2612": ChipFamily(
        name="Yamaha YM2612",
        queries=[
            "Yamaha YM2612",
            "YM2612 OPN2",
            "YM2612 Sega",
        ],
        exclude=["breakout board", "module", "synth"],
        variants={},
    ),
    "sn76489": ChipFamily(
        name="TI SN76489",
        queries=[
            "SN76489 sound chip",
            "TI SN76489",
            "SN76489AN",
        ],
        exclude=[],
        variants={"sn76489an": "SN76489AN"},
    ),
    "2a03": ChipFamily(
        name="Ricoh 2A03",
        queries=[
            "Ricoh 2A03",
            "RP2A03 NES",
            "2A03 NES chip",
            "Ricoh 2A07",
        ],
        exclude=[],
        variants={"2a03": "2A03", "2a07": "2A07"},
    ),
    "discover": ChipFamily(
        name="Discovery",
        queries=[
            "vintage sound chip IC",
            "retro computer chip IC",
            "vintage game chip",
            "MOS custom chip",
            "Amiga custom chip",
        ],
        exclude=[],
        variants={},
    ),
}

# ---------------------------------------------------------------------------
# General configuration
# ---------------------------------------------------------------------------

EBAY_SITES = {
    "com": "https://www.ebay.com",
    "co.uk": "https://www.ebay.co.uk",
    "de": "https://www.ebay.de",
}

CURRENCY_SYMBOLS = {"$": "USD", "\u00a3": "GBP", "\u20ac": "EUR"}

PRICE_RE = re.compile(r"([$\u00a3\u20ac])\s?([\d,]+(?:\.\d{1,2})?)")

DATE_PATTERNS = [
    re.compile(r"Sold\s+(\w{3}\s+\d{1,2},?\s+\d{4})"),
    re.compile(r"Sold\s+(\d{1,2}\s+\w{3}\s+\d{4})"),
    re.compile(r"(\d{1,2}\s+\w{3}\s+\d{4})"),
    re.compile(r"(\w{3}\s+\d{1,2},?\s+\d{4})"),
]

DATE_FORMATS = [
    "%b %d, %Y",
    "%b %d %Y",
    "%d %b %Y",
]

TITLE_NOISE = re.compile(
    r"(^New listing|Opens in a new window or tab$)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SoldListing:
    chip_family: str
    title: str
    price: float
    currency: str
    date_sold: str  # ISO date string or empty
    ebay_site: str
    search_query: str


# ---------------------------------------------------------------------------
# Scraping helpers
# ---------------------------------------------------------------------------

def polite_sleep(min_s: float = 3.0, max_s: float = 7.0) -> None:
    delay = random.uniform(min_s, max_s)
    log.debug("sleeping %.1fs", delay)
    time.sleep(delay)


def build_sold_url(query: str, page: int, site: str) -> str:
    base = EBAY_SITES[site]
    encoded = quote(query)
    return (
        f"{base}/sch/i.html"
        f"?_nkw={encoded}"
        f"&LH_Sold=1&LH_Complete=1"
        f"&_pgn={page}&_ipg=120"
    )


def fetch_page(page: Page, url: str, retries: int = 3) -> str | None:
    """Navigate to url and return rendered HTML."""
    for attempt in range(1, retries + 1):
        try:
            log.debug("navigating to %s (attempt %d)", url, attempt)
            resp = page.goto(url, wait_until="networkidle", timeout=60_000)
            if resp is None:
                log.warning("no response from %s", url)
                continue

            html = page.content()

            # Check for bot-block pages — but avoid false positives from
            # CSS class names like ".ifh-captcha" that appear on normal pages.
            # A real block page is small and lacks search result elements.
            soup_quick = BeautifulSoup(html, "html.parser")
            has_results = bool(
                soup_quick.select("li.s-card") or soup_quick.select("li.s-item")
            )
            if not has_results:
                body_text = soup_quick.get_text(" ", strip=True).lower()
                if any(w in body_text for w in (
                    "checking your browser",
                    "access denied",
                    "verify you are human",
                )):
                    log.warning("bot-detection page, backing off 30s (attempt %d)", attempt)
                    time.sleep(30)
                    continue

            if resp.status == 503:
                log.warning("503 from eBay, backing off 30s")
                time.sleep(30)
                continue

            return html

        except Exception as exc:
            log.warning("page load error (attempt %d): %s", attempt, exc)
            time.sleep(5 * attempt)

    log.error("all retries exhausted for %s", url)
    return None


def clean_title(raw: str) -> str:
    """Remove eBay decoration from listing titles."""
    cleaned = TITLE_NOISE.sub("", raw).strip()
    return re.sub(r"\s{2,}", " ", cleaned)


def parse_price(text: str) -> tuple[float, str] | None:
    text = text.replace(",", "")
    m = PRICE_RE.search(text)
    if not m:
        return None
    symbol = m.group(1)
    currency = CURRENCY_SYMBOLS.get(symbol, symbol)
    try:
        price = float(m.group(2))
    except ValueError:
        return None
    return price, currency


def parse_date(text: str) -> str:
    for pattern in DATE_PATTERNS:
        m = pattern.search(text)
        if m:
            raw = m.group(1).strip().replace(",", "")
            for fmt in DATE_FORMATS:
                try:
                    dt = datetime.strptime(raw, fmt)
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return ""


def is_excluded(title: str, family: ChipFamily) -> bool:
    """Check title against global and family-specific exclusions."""
    title_lower = title.lower()
    for kw in GLOBAL_EXCLUSIONS:
        if kw in title_lower:
            return True
    for kw in family.exclude:
        if kw in title_lower:
            return True
    return False


def parse_listings(
    html: str,
    site: str,
    query: str,
    family_id: str,
    family: ChipFamily,
    min_price: float,
) -> list[SoldListing]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[SoldListing] = []

    # eBay 2025+ uses li.s-card; older pages use li.s-item
    cards = soup.select("li.s-card")
    items = soup.select("li.s-item")

    # --- New layout: s-card ---
    for card in cards:
        title_el = card.select_one(".s-card__title")
        if not title_el:
            continue
        title = clean_title(title_el.get_text(strip=True))
        if not title or "shop on ebay" in title.lower():
            continue
        if is_excluded(title, family):
            log.debug("excluded: %s", title[:80])
            continue

        price_el = card.select_one(".s-card__price")
        if not price_el:
            continue
        parsed = parse_price(price_el.get_text(strip=True))
        if not parsed:
            continue
        price, currency = parsed
        if price < min_price or price > 5000.0:
            continue

        date_str = ""
        caption = card.select_one(".s-card__caption")
        if caption:
            date_str = parse_date(caption.get_text())
        if not date_str:
            date_str = parse_date(card.get_text())

        results.append(SoldListing(
            chip_family=family_id, title=title, price=price,
            currency=currency, date_sold=date_str,
            ebay_site=site, search_query=query,
        ))

    # --- Legacy layout: s-item ---
    for item in items:
        title_el = item.select_one(".s-item__title")
        if not title_el:
            continue
        title = clean_title(title_el.get_text(strip=True))
        if not title or "shop on ebay" in title.lower():
            continue
        if is_excluded(title, family):
            continue

        price_el = item.select_one(".s-item__price")
        if not price_el:
            continue
        parsed = parse_price(price_el.get_text(strip=True))
        if not parsed:
            continue
        price, currency = parsed
        if price < min_price or price > 5000.0:
            continue

        date_str = ""
        for sel in (".s-item__caption", ".s-item__ended-date", ".s-item__detail"):
            el = item.select_one(sel)
            if el:
                date_str = parse_date(el.get_text())
                if date_str:
                    break
        if not date_str:
            date_str = parse_date(item.get_text())

        results.append(SoldListing(
            chip_family=family_id, title=title, price=price,
            currency=currency, date_sold=date_str,
            ebay_site=site, search_query=query,
        ))

    return results


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def dedup_listings(listings: list[SoldListing]) -> list[SoldListing]:
    seen: set[tuple[str, str, float, str, str]] = set()
    unique: list[SoldListing] = []
    for item in listings:
        key = (item.chip_family, item.title, item.price, item.date_sold, item.ebay_site)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def write_csv(listings: list[SoldListing], path: str) -> None:
    fieldnames = [f.name for f in fields(SoldListing)]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for item in listings:
            row = {
                "chip_family": item.chip_family,
                "title": item.title,
                "price": f"{item.price:.2f}",
                "currency": item.currency,
                "date_sold": item.date_sold,
                "ebay_site": item.ebay_site,
                "search_query": item.search_query,
            }
            writer.writerow(row)
    log.info("wrote %d rows to %s", len(listings), path)


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def _print_group_stats(label: str, items: list[SoldListing], indent: int = 2) -> None:
    """Print count / mean / median for a group of listings."""
    if not items:
        return
    prices = sorted(i.price for i in items)
    n = len(prices)
    mean = sum(prices) / n
    median = prices[n // 2]
    pad = " " * indent
    print(f"{pad}{label:20s}: {n:4d} listings, mean {mean:8.2f}, median {median:8.2f}")


def print_summary(listings: list[SoldListing]) -> None:
    if not listings:
        print("\nNo listings found.")
        return

    print(f"\n{'=' * 65}")
    print(f"SUMMARY: {len(listings)} unique sold listings scraped")
    print(f"{'=' * 65}")

    # --- By eBay site ---
    by_site: dict[str, list[SoldListing]] = {}
    for item in listings:
        by_site.setdefault(item.ebay_site, []).append(item)
    print("\nBy eBay site:")
    for site, items in sorted(by_site.items()):
        prices = [i.price for i in items]
        mean = sum(prices) / len(prices)
        print(f"  .{site:5s} : {len(items):4d} listings, mean price {items[0].currency} {mean:.2f}")

    # --- By chip family ---
    by_family: dict[str, list[SoldListing]] = {}
    for item in listings:
        by_family.setdefault(item.chip_family, []).append(item)

    print("\nBy chip family:")
    for fam_id in CHIP_FAMILIES:
        fam_items = by_family.get(fam_id)
        if not fam_items:
            continue
        family = CHIP_FAMILIES[fam_id]
        _print_group_stats(f"{family.name} (all)", fam_items)

        # Variant breakdown
        if family.variants:
            matched_ids: set[int] = set()
            for substr, label in family.variants.items():
                variant_items = [
                    i for i in fam_items if substr.lower() in i.title.lower()
                ]
                matched_ids.update(id(i) for i in variant_items)
                if variant_items:
                    _print_group_stats(f"  {label}", variant_items, indent=4)
            other_items = [i for i in fam_items if id(i) not in matched_ids]
            if other_items:
                _print_group_stats("  other/mixed", other_items, indent=4)

    # --- Date range ---
    dated = [i for i in listings if i.date_sold]
    if dated:
        dates = sorted(i.date_sold for i in dated)
        print(f"\nDate range: {dates[0]} to {dates[-1]} ({len(dated)} listings with dates)")
    else:
        print("\nNo sold dates could be extracted.")

    # --- Price distribution ---
    all_prices = sorted(i.price for i in listings)
    n = len(all_prices)
    if n >= 4:
        q1 = all_prices[n // 4]
        median = all_prices[n // 2]
        q3 = all_prices[3 * n // 4]
        print(f"\nPrice distribution (all currencies mixed):")
        print(f"  Min: {all_prices[0]:.2f}  Q1: {q1:.2f}  Median: {median:.2f}  Q3: {q3:.2f}  Max: {all_prices[-1]:.2f}")
    elif n > 0:
        print(f"\nPrices: {', '.join(f'{p:.2f}' for p in all_prices)}")

    print(f"{'=' * 65}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def resolve_families(chip_args: list[str]) -> list[str]:
    """Resolve --chips argument to a list of family IDs."""
    if "all" in chip_args:
        return [fid for fid in CHIP_FAMILIES if fid != "discover"]
    resolved: list[str] = []
    for name in chip_args:
        if name not in CHIP_FAMILIES:
            log.error("unknown chip family: %s (valid: %s)",
                      name, ", ".join(CHIP_FAMILIES))
            raise SystemExit(1)
        resolved.append(name)
    return resolved


def main() -> None:
    all_family_ids = list(CHIP_FAMILIES.keys())

    parser = argparse.ArgumentParser(
        description="Scrape eBay sold listings for retro IC chips")
    parser.add_argument("--chips", nargs="+", default=["all"],
                        metavar="FAMILY",
                        help=(
                            "chip families to scrape (default: all except discover). "
                            f"choices: {', '.join(all_family_ids)}, all"
                        ))
    parser.add_argument("--pages", type=int, default=2,
                        help="pages per query per site (default: 2)")
    parser.add_argument("--min-price", type=float, default=1.0,
                        help="minimum listing price to include (default: 1.0)")
    parser.add_argument("--output", default="retro_ic_sold_listings.csv",
                        help="output CSV path")
    parser.add_argument("--sites", nargs="+", default=["com", "co.uk"],
                        choices=list(EBAY_SITES.keys()),
                        help="eBay sites to scrape (default: com co.uk)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print URLs without fetching")
    parser.add_argument("--verbose", action="store_true",
                        help="debug logging")
    parser.add_argument("--headed", action="store_true",
                        help="show browser window (useful for debugging)")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    families = resolve_families(args.chips)
    log.info("chip families: %s", ", ".join(families))

    # Build work list: (family_id, query, site, page)
    work: list[tuple[str, str, str, int]] = []
    for fam_id in families:
        family = CHIP_FAMILIES[fam_id]
        for query in family.queries:
            for site in args.sites:
                for pg in range(1, args.pages + 1):
                    work.append((fam_id, query, site, pg))

    # Dry-run mode
    if args.dry_run:
        for i, (fam_id, query, site, pg) in enumerate(work, 1):
            url = build_sold_url(query, pg, site)
            print(f"[{i}/{len(work)}] [{fam_id}] {url}")
        print(f"\n{len(work)} requests would be made across {len(families)} chip families.")
        return

    # Real scraping
    all_listings: list[SoldListing] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        # Warm up session with homepage
        log.info("warming up browser session...")
        page.goto("https://www.ebay.com", wait_until="domcontentloaded",
                  timeout=30_000)
        polite_sleep(2, 4)

        for i, (fam_id, query, site, pg) in enumerate(work, 1):
            family = CHIP_FAMILIES[fam_id]
            url = build_sold_url(query, pg, site)

            log.info("[%d/%d] [%s] %s (page %d on .%s)",
                     i, len(work), fam_id, query, pg, site)

            html = fetch_page(page, url)
            if html is None:
                continue

            page_listings = parse_listings(
                html, site, query, fam_id, family, args.min_price,
            )
            log.info("  -> %d listings from this page", len(page_listings))
            all_listings.extend(page_listings)

            polite_sleep()

        browser.close()

    unique = dedup_listings(all_listings)
    log.info("total: %d raw, %d after dedup", len(all_listings), len(unique))

    write_csv(unique, args.output)
    print_summary(unique)


if __name__ == "__main__":
    main()
