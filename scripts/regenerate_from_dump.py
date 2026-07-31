# scripts/regenerate_from_dump.py
#
# Regenerates all Zoho import CSVs from the already-extracted Tally dump JSON files.
# Does NOT need a live Tally connection.
#
# Usage: python scripts/regenerate_from_dump.py

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import OUTPUT_DIR
from mappers.coa_mapper import build_group_map, parse_ledgers, run_coa_mapping
from mappers.contact_mapper import run_contact_mapping

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def main():
    dumps_dir = os.path.join(OUTPUT_DIR, "tally_dumps")
    groups_path = os.path.join(dumps_dir, "groups.json")
    ledgers_path = os.path.join(dumps_dir, "ledgers.json")

    if not os.path.exists(groups_path) or not os.path.exists(ledgers_path):
        logger.error(f"Dump files not found in {dumps_dir}. Please run main.py first.")
        sys.exit(1)

    logger.info("Loading groups from dump...")
    with open(groups_path, "r", encoding="utf-8") as f:
        groups_data = json.load(f)
    groups = groups_data.get("groups", [])
    logger.info(f"Loaded {len(groups)} groups.")

    logger.info("Loading ledgers from dump...")
    ledgers = parse_ledgers(ledgers_path)
    logger.info(f"Loaded {len(ledgers)} ledgers.")

    with open(ledgers_path, "r", encoding="utf-8") as f:
        ledger_meta = json.load(f)
    period = ledger_meta.get("period", {})
    from_date_raw = period.get("from", "1-4-2025")
    parts = from_date_raw.split("-")
    if len(parts) == 3:
        migration_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    else:
        migration_date = "2025-04-01"
    logger.info(f"Migration date resolved to: {migration_date}")

    gmap = build_group_map(groups)

    logger.info("Running COA mapping...")
    deduped_rows, parent_accounts = run_coa_mapping(ledgers, gmap, dumps_dir)
    logger.info(f"COA mapping complete: {len(deduped_rows)} accounts.")

    logger.info("Running Contact & Opening Balance mapping (P&L accounts excluded)...")
    run_contact_mapping(ledgers, gmap, parent_accounts, migration_date, dumps_dir)

    logger.info("Done! Regenerated CSVs:")
    logger.info(f"  {os.path.join(dumps_dir, 'zoho_opening_balances_import.csv')}")
    logger.info(f"  {os.path.join(dumps_dir, 'zoho_customers_import.csv')}")
    logger.info(f"  {os.path.join(dumps_dir, 'zoho_vendors_import.csv')}")

if __name__ == "__main__":
    main()
