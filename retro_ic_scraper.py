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
class VariantRule:
    """Ordered rule for classifying a listing into a variant.

    A listing matches if it contains at least one `include` substring AND
    none of the `exclude` substrings (all case-insensitive).  The first
    matching rule wins.
    """
    label: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChipFamily:
    name: str
    queries: list[str]
    exclude: list[str]           # title substrings that reject a listing
    must_match: list[str]        # at least one must appear or listing is noise
    variant_rules: list[VariantRule]


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
        must_match=["sid", "6581", "8580"],
        variant_rules=[
            VariantRule("6581", include=("6581",)),
            VariantRule("8580", include=("8580",)),
        ],
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
        must_match=["vic", "6567", "6569", "8562", "8565", "8566"],
        variant_rules=[
            VariantRule("6567 (NTSC)", include=("6567",)),
            VariantRule("6569 (PAL)", include=("6569",)),
            VariantRule("8562 (NTSC)", include=("8562",)),
            VariantRule("8565 (PAL)", include=("8565",)),
            VariantRule("8566", include=("8566",)),
        ],
    ),
    "denise": ChipFamily(
        name="Amiga Denise",
        queries=[
            "Amiga Denise 8362",
            "Amiga Denise 8373",
            "Super Denise",
            "MOS 8362 Denise",
            "CSG 8373 Denise",
        ],
        exclude=[],
        must_match=[
            "denise", "8362", "8373", "390433", "391081",
        ],
        variant_rules=[
            # PLCC must be checked before generic 8373
            VariantRule("PLCC-52 Super (391081)",
                        include=("391081", "8373r4pl", "plcc")),
            VariantRule("DIP-48 Super (8373)",
                        include=("8373", "super denise", "390433"),
                        exclude=("plcc", "391081", "8373r4pl")),
            VariantRule("DIP-48 OCS (8362)",
                        include=("8362",)),
        ],
    ),
    "paula": ChipFamily(
        name="Amiga Paula",
        queries=[
            "Amiga Paula 8364",
            "CSG 8364R7 Paula",
        ],
        exclude=[
            # Common false positives from "Paula" as a first name
            "abdul", "choice", "yates", "rego", "cole band", "cole amen",
            "figurine", "autograph", "vinyl", "record", "album",
            "photo", "book", "wigs", "blouse", "top ", "dress",
            "sweater", "nylons", "stockings", "denarius", "brooch",
            "ski ", "prentiss", "doll", "hey paula", "disco poster",
        ],
        must_match=[
            "8364", "paula chip", "paula audio", "paula sound",
            "252127", "391077",
        ],
        variant_rules=[
            VariantRule("PLCC-52 (391077)",
                        include=("391077", "8364r7pl", "plcc")),
            VariantRule("DIP-48 (8364)",
                        include=("8364",),
                        exclude=("plcc", "391077", "8364r7pl")),
        ],
    ),
    "agnus": ChipFamily(
        name="Amiga Agnus",
        queries=[
            "Amiga Agnus 8372A",
            "Amiga Agnus 8375",
            "Fat Agnus chip",
            "Fatter Agnus chip",
            "CSG 8372 Agnus",
        ],
        exclude=[
            # Vitex agnus-castus (herbal supplement)
            "vitex", "equine", "supplement", "mares", "chasteberry",
            "hormone", "t-shirt", "shirt",
        ],
        must_match=[
            "agnus", "8361", "8370", "8371", "8372", "8375",
            "318069", "390544",
        ],
        variant_rules=[
            VariantRule("DIP-48 (8361/8370/8371)",
                        include=("8361", "8370", "8371")),
            VariantRule("PLCC-84 8372/A (1MB)",
                        include=("8372",),
                        exclude=("8375",)),
            VariantRule("PLCC-84 8375 (2MB)",
                        include=("8375", "390544")),
        ],
    ),
    "ym2151": ChipFamily(
        name="Yamaha YM2151",
        queries=[
            "Yamaha YM2151",
            "YM2151 OPM",
            "YM2151 sound chip",
        ],
        exclude=["breakout board", "module", "synth"],
        must_match=["ym2151"],
        variant_rules=[],
    ),
    "ym2612": ChipFamily(
        name="Yamaha YM2612",
        queries=[
            "Yamaha YM2612",
            "YM2612 OPN2",
            "YM2612 Sega Genesis",
        ],
        exclude=["breakout board", "module", "synth"],
        must_match=["ym2612"],
        variant_rules=[],
    ),
    "sn76489": ChipFamily(
        name="TI SN76489",
        queries=[
            "SN76489 sound chip",
            "TI SN76489",
            "SN76489AN",
        ],
        exclude=[],
        must_match=["sn76489", "76489"],
        variant_rules=[
            VariantRule("SN76489AN", include=("sn76489an",)),
        ],
    ),
    "2a03": ChipFamily(
        name="Ricoh 2A03",
        queries=[
            "Ricoh 2A03 NES",
            "RP2A03 NES",
            "Ricoh 2A07 NES",
            "RP2A07 NES",
        ],
        exclude=[],
        must_match=["2a03", "2a07", "rp2a"],
        variant_rules=[
            VariantRule("2A03 (NTSC)", include=("2a03",), exclude=("2a07",)),
            VariantRule("2A07 (PAL)", include=("2a07",)),
        ],
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
        must_match=[],  # discovery mode accepts everything
        variant_rules=[],
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


def is_relevant(title: str, family: ChipFamily) -> bool:
    """Check that the title contains at least one family-specific keyword.

    eBay's broad matching often returns unrelated results (e.g. "Yamaha
    motorcycle parts" for YM2612 queries).  This filter ensures we only
    keep listings that actually mention the chip.
    """
    if not family.must_match:
        return True  # discovery mode — accept everything
    title_lower = title.lower()
    return any(kw in title_lower for kw in family.must_match)


def classify_variant(title: str, rules: list[VariantRule]) -> str:
    """Return the variant label for a listing, or "other/mixed"."""
    title_lower = title.lower()
    for rule in rules:
        has_include = any(kw in title_lower for kw in rule.include)
        has_exclude = any(kw in title_lower for kw in rule.exclude) if rule.exclude else False
        if has_include and not has_exclude:
            return rule.label
    return "other/mixed"


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
        if not is_relevant(title, family):
            log.debug("not relevant: %s", title[:80])
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
        if not is_relevant(title, family):
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

def _calc_stats(items: list[SoldListing]) -> dict[str, float | int]:
    """Return count, mean, median, q1, q3, min, max for a group."""
    prices = sorted(i.price for i in items)
    n = len(prices)
    return {
        "count": n,
        "mean": sum(prices) / n,
        "median": prices[n // 2],
        "q1": prices[n // 4] if n >= 4 else prices[0],
        "q3": prices[3 * n // 4] if n >= 4 else prices[-1],
        "min": prices[0],
        "max": prices[-1],
    }


def _detect_package(variant_label: str) -> str:
    """Extract package type from a variant label."""
    vl = variant_label.lower()
    if "plcc-84" in vl:
        return "PLCC-84"
    if "plcc-52" in vl:
        return "PLCC-52"
    if "dip-48" in vl:
        return "DIP-48"
    if "dip" in vl:
        return "DIP"
    if "plcc" in vl:
        return "PLCC"
    return ""


def print_summary(listings: list[SoldListing]) -> None:
    if not listings:
        print("\nNo listings found.")
        return

    W = 95
    print(f"\n{'=' * W}")
    print(f"SUMMARY: {len(listings)} unique sold listings scraped")
    print(f"{'=' * W}")

    # --- By eBay site ---
    by_site: dict[str, list[SoldListing]] = {}
    for item in listings:
        by_site.setdefault(item.ebay_site, []).append(item)
    print("\nBy eBay site:")
    for site, items in sorted(by_site.items()):
        s = _calc_stats(items)
        print(f"  .{site:5s} : {s['count']:4d} listings, "
              f"mean {items[0].currency} {s['mean']:.2f}, "
              f"median {items[0].currency} {s['median']:.2f}")

    # --- Variant table ---
    # Header
    hdr = (f"  {'Chip Family':<16s} {'Variant':<28s} {'Package':<10s} "
           f"{'Count':>5s} {'Median':>8s} {'Mean':>8s} {'Q1':>8s} {'Q3':>8s}")
    sep = "  " + "-" * (len(hdr) - 2)

    print(f"\nBy chip family and variant:")
    print(hdr)
    print(sep)

    by_family: dict[str, list[SoldListing]] = {}
    for item in listings:
        by_family.setdefault(item.chip_family, []).append(item)

    grand_total = 0

    for fam_id in CHIP_FAMILIES:
        fam_items = by_family.get(fam_id)
        if not fam_items:
            continue
        family = CHIP_FAMILIES[fam_id]

        # Classify all items into variants
        variant_groups: dict[str, list[SoldListing]] = {}
        for item in fam_items:
            label = classify_variant(item.title, family.variant_rules) if family.variant_rules else "(all)"
            variant_groups.setdefault(label, []).append(item)

        # Print variants in rule order, then other/mixed
        labels_in_order: list[str] = []
        for rule in family.variant_rules:
            if rule.label in variant_groups:
                labels_in_order.append(rule.label)
        if "(all)" in variant_groups:
            labels_in_order.append("(all)")
        if "other/mixed" in variant_groups:
            labels_in_order.append("other/mixed")

        fam_total = 0
        for label in labels_in_order:
            items = variant_groups[label]
            s = _calc_stats(items)
            pkg = _detect_package(label)
            fam_total += s["count"]
            print(f"  {family.name:<16s} {label:<28s} {pkg:<10s} "
                  f"{s['count']:5d} {s['median']:8.2f} {s['mean']:8.2f} "
                  f"{s['q1']:8.2f} {s['q3']:8.2f}")

        # Family subtotal
        if len(labels_in_order) > 1:
            s = _calc_stats(fam_items)
            print(f"  {'':<16s} {'--- subtotal ---':<28s} {'':<10s} "
                  f"{s['count']:5d} {s['median']:8.2f} {s['mean']:8.2f} "
                  f"{s['q1']:8.2f} {s['q3']:8.2f}")
        grand_total += fam_total

    # Grand total
    print(sep)
    s = _calc_stats(listings)
    print(f"  {'TOTAL':<16s} {'':<28s} {'':<10s} "
          f"{s['count']:5d} {s['median']:8.2f} {s['mean']:8.2f} "
          f"{s['q1']:8.2f} {s['q3']:8.2f}")

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

    print(f"{'=' * W}")


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
