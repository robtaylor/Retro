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
relevance and exclusion filters, writes a cleaned CSV, and prints
the summary table.

Usage:
    uv run summarise.py                              # defaults
    uv run summarise.py -i raw.csv -o filtered.csv   # custom paths
"""

import argparse
import csv
import logging
import sys

# Import everything we need from the scraper
from retro_ic_scraper import (
    CHIP_FAMILIES,
    SoldListing,
    is_relevant,
    is_excluded,
    dedup_listings,
    write_csv,
    print_summary,
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-filter and summarise a retro IC scraper CSV")
    parser.add_argument("-i", "--input", default="retro_ic_sold_listings.csv",
                        help="input CSV from retro_ic_scraper.py")
    parser.add_argument("-o", "--output", default="retro_ic_filtered.csv",
                        help="output filtered CSV")
    args = parser.parse_args()

    listings = load_and_filter(args.input)
    if not listings:
        print("No listings survived filtering.", file=sys.stderr)
        raise SystemExit(1)

    write_csv(listings, args.output)
    print_summary(listings)


if __name__ == "__main__":
    main()
