# scripts/regenerate_payments.py
#
# Regenerates ONLY zoho_customer_payments_import.csv and zoho_vendor_payments_import.csv.
#
import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import TALLY_HOST, TALLY_PORT, TALLY_TIMEOUT, OUTPUT_DIR
from core.tally_client import TallyClient
from mappers.coa_mapper import build_group_map, parse_ledgers
from mappers.contact_mapper import run_contact_mapping
from mappers.payment_mapper import run_payment_mapping, run_vendor_payment_mapping
from main import get_company_books_from_date, get_last_voucher_date, get_last_voucher_date_from_vouchers, get_current_period

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

    logger.info("Loading ledgers from dump...")
    ledgers = parse_ledgers(ledgers_path)

    with open(ledgers_path, "r", encoding="utf-8") as f:
        ledger_meta = json.load(f)
    period = ledger_meta.get("period", {})
    from_date_raw = period.get("from", "1-4-2016")
    to_date_raw = period.get("to", "2-2-2026")
    
    parts = from_date_raw.split("-")
    if len(parts) == 3:
        migration_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    else:
        migration_date = "2016-04-01"

    gmap = build_group_map(groups)

    logger.info("Resolving contacts and opening advances...")
    contact_results = run_contact_mapping(
        ledgers, gmap, {}, migration_date, dumps_dir
    )
    customer_list, vendor_list, bank_list, customer_advances, vendor_advances = contact_results

    logger.info("Connecting to Tally Client...")
    tally = TallyClient(host=TALLY_HOST, port=TALLY_PORT, timeout=TALLY_TIMEOUT)

    # Determine date range
    f_date = get_company_books_from_date(tally) or from_date_raw
    t_date = to_date_raw if to_date_raw else (get_last_voucher_date(tally) or get_last_voucher_date_from_vouchers(tally) or "31-3-2026")

    logger.info(f"Date range resolved: {f_date} -> {t_date}")

    logger.info("Regenerating Customer Payments CSV...")
    run_payment_mapping(tally, dumps_dir, f_date, t_date, customer_advances)

    logger.info("Regenerating Vendor Payments CSV...")
    run_vendor_payment_mapping(tally, dumps_dir, f_date, t_date, vendor_advances)

    logger.info("Successfully regenerated zoho_customer_payments_import.csv and zoho_vendor_payments_import.csv!")

if __name__ == "__main__":
    main()
