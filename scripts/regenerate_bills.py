# scripts/regenerate_bills.py
#
# Regenerates the Zoho Bills import CSV file from Tally.
#
# Usage: python scripts/regenerate_bills.py

import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import TALLY_HOST, TALLY_PORT, TALLY_TIMEOUT, OUTPUT_DIR
from core.tally_client import TallyClient
from main import resolve_date_range, get_active_company
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

        f_date, t_date = resolve_date_range(tally)
        logger.info(f"Extracting historical bills for period: {f_date} → {t_date}")

        zoho_rows = run_bill_mapping(tally, dumps_dir, f_date, t_date)

        logger.info("=" * 60)
        logger.info("BILLS FILE REGENERATION COMPLETED SUCCESSFULLY!")
        logger.info(f"  Total bill lines written: {len(zoho_rows)}")
        logger.info(f"  Output directory: {os.path.abspath(dumps_dir)}")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"Failed to regenerate bills file: {e}")

if __name__ == "__main__":
    main()
