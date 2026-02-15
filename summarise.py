# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "playwright>=1.40",
#     "playwright-stealth>=1.0",
#     "beautifulsoup4>=4.12",
# ]
# ///
"""
Re-filter and summarise an existing retro IC scraper CSV.

Reads a CSV produced by retro_ic_scraper.py, applies the current
relevance and exclusion filters, writes a summary CSV with per-variant
statistics, and prints the summary table to stdout.

Usage:
    uv run summarise.py                              # defaults
    uv run summarise.py -i raw.csv -o summary.csv    # custom paths
"""

import argparse
import csv
import logging
import sys

from retro_ic_scraper import (
    CHIP_FAMILIES,
    SoldListing,
    is_relevant,
    is_excluded,
    dedup_listings,
    classify_variant,
    print_summary,
    _calc_stats,
    _detect_package,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_and_filter(input_path: str) -> list[SoldListing]:
    """Load a scraper CSV and apply current relevance/exclusion filters."""
    with open(input_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        raw: list[SoldListing] = []
        skipped = 0
        for row in reader:
            fam_id = row["chip_family"]
            if fam_id not in CHIP_FAMILIES:
                skipped += 1
                continue
            family = CHIP_FAMILIES[fam_id]
            if not is_relevant(row["title"], family):
                skipped += 1
                continue
            if is_excluded(row["title"], family):
                skipped += 1
                continue
            raw.append(SoldListing(
                chip_family=fam_id,
                title=row["title"],
                price=float(row["price"]),
                currency=row["currency"],
                date_sold=row["date_sold"],
                ebay_site=row["ebay_site"],
                search_query=row["search_query"],
            ))

    unique = dedup_listings(raw)
    log.info("loaded %d rows, kept %d after filtering, %d after dedup",
             len(raw) + skipped, len(raw), len(unique))
    return unique


def write_summary_csv(listings: list[SoldListing], path: str) -> None:
    """Write a summary CSV with one row per chip family / variant."""
    by_family: dict[str, list[SoldListing]] = {}
    for item in listings:
        by_family.setdefault(item.chip_family, []).append(item)

    fieldnames = [
        "chip_family", "chip_name", "variant", "package",
        "count", "median", "mean", "q1", "q3", "min", "max",
    ]

    rows: list[dict[str, str]] = []

    for fam_id in CHIP_FAMILIES:
        fam_items = by_family.get(fam_id)
        if not fam_items:
            continue
        family = CHIP_FAMILIES[fam_id]

        # Classify into variants
        variant_groups: dict[str, list[SoldListing]] = {}
        for item in fam_items:
            label = (classify_variant(item.title, family.variant_rules)
                     if family.variant_rules else "(all)")
            variant_groups.setdefault(label, []).append(item)

        # Emit rows in rule order, then other/mixed
        labels: list[str] = []
        for rule in family.variant_rules:
            if rule.label in variant_groups:
                labels.append(rule.label)
        if "(all)" in variant_groups:
            labels.append("(all)")
        if "other/mixed" in variant_groups:
            labels.append("other/mixed")

        for label in labels:
            s = _calc_stats(variant_groups[label])
            rows.append({
                "chip_family": fam_id,
                "chip_name": family.name,
                "variant": label,
                "package": _detect_package(label),
                "count": str(s["count"]),
                "median": f"{s['median']:.2f}",
                "mean": f"{s['mean']:.2f}",
                "q1": f"{s['q1']:.2f}",
                "q3": f"{s['q3']:.2f}",
                "min": f"{s['min']:.2f}",
                "max": f"{s['max']:.2f}",
            })

        # Subtotal row for families with multiple variants
        if len(labels) > 1:
            s = _calc_stats(fam_items)
            rows.append({
                "chip_family": fam_id,
                "chip_name": family.name,
                "variant": "SUBTOTAL",
                "package": "",
                "count": str(s["count"]),
                "median": f"{s['median']:.2f}",
                "mean": f"{s['mean']:.2f}",
                "q1": f"{s['q1']:.2f}",
                "q3": f"{s['q3']:.2f}",
                "min": f"{s['min']:.2f}",
                "max": f"{s['max']:.2f}",
            })

    # Grand total
    s = _calc_stats(listings)
    rows.append({
        "chip_family": "",
        "chip_name": "TOTAL",
        "variant": "",
        "package": "",
        "count": str(s["count"]),
        "median": f"{s['median']:.2f}",
        "mean": f"{s['mean']:.2f}",
        "q1": f"{s['q1']:.2f}",
        "q3": f"{s['q3']:.2f}",
        "min": f"{s['min']:.2f}",
        "max": f"{s['max']:.2f}",
    })

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log.info("wrote %d summary rows to %s", len(rows), path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-filter and summarise a retro IC scraper CSV")
    parser.add_argument("-i", "--input", default="retro_ic_sold_listings.csv",
                        help="input CSV from retro_ic_scraper.py")
    parser.add_argument("-o", "--output", default="retro_ic_summary.csv",
                        help="output summary CSV")
    args = parser.parse_args()

    listings = load_and_filter(args.input)
    if not listings:
        print("No listings survived filtering.", file=sys.stderr)
        raise SystemExit(1)

    write_summary_csv(listings, args.output)
    print_summary(listings)


if __name__ == "__main__":
    main()
