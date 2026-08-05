# scripts/regenerate_items_and_bills.py
#
# Regenerates Items, Items Opening Stock, and Bills CSV files from Tally.
#
# Usage: python scripts/regenerate_items_and_bills.py

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import TALLY_HOST, TALLY_PORT, TALLY_TIMEOUT, OUTPUT_DIR
from core.tally_client import TallyClient
from main import resolve_date_range, get_active_company
from mappers.item_mapper import run_item_mapping
from mappers.bill_mapper import run_bill_mapping

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def main():
    dumps_dir = os.path.join(OUTPUT_DIR, "tally_dumps")
    os.makedirs(dumps_dir, exist_ok=True)

    logger.info("Initializing Tally connection...")
    timeout = int(os.getenv("TALLY_TIMEOUT", "120"))
    tally = TallyClient(host=TALLY_HOST, port=TALLY_PORT, timeout=timeout)

    try:
        company = get_active_company(tally)
        logger.info(f"Active Company: {company}")

        # 1. Regenerate Items and Items Opening Stock
        logger.info("Extracting Stock Items & Opening Balances from Tally...")
        item_rows = run_item_mapping(tally, dumps_dir)
        logger.info(f"Items mapping complete: {len(item_rows)} items.")

        # 2. Regenerate Bills
        f_date, t_date = resolve_date_range(tally)
        logger.info(f"Extracting historical bills for period: {f_date} → {t_date}")
        bill_rows = run_bill_mapping(tally, dumps_dir, f_date, t_date)
        logger.info(f"Bills mapping complete: {len(bill_rows)} bill lines.")

        logger.info("=" * 60)
        logger.info("REGENERATION COMPLETED SUCCESSFULLY!")
        logger.info(f"  Items Master         : {os.path.join(dumps_dir, 'zoho_items_import.csv')}")
        logger.info(f"  Items Opening Stock  : {os.path.join(dumps_dir, 'zoho_items_opening_stock_import.csv')}")
        logger.info(f"  Bills Import         : {os.path.join(dumps_dir, 'zoho_bills_import.csv')}")
        logger.info(f"  Output directory     : {os.path.abspath(dumps_dir)}")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"Failed to regenerate items and bills: {e}")

if __name__ == "__main__":
    main()
