# main.py

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from lxml import etree

from config.settings import TALLY_HOST, TALLY_PORT, TALLY_TIMEOUT, OUTPUT_DIR
from core.tally_client import TallyClient
from core.xml_parser import sanitize_xml, etree_to_dict
from mappers.coa_mapper import build_group_map, parse_ledgers, run_coa_mapping
from mappers.contact_mapper import run_contact_mapping
from mappers.invoice_mapper import run_invoice_mapping
from mappers.bill_mapper import run_bill_mapping
from mappers.payment_mapper import run_payment_mapping, run_vendor_payment_mapping
from mappers.item_mapper import run_item_mapping

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


def get_active_company(tally: TallyClient) -> str:
    """Fetch active company name from Tally."""
    payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>CompanyNameCollection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="CompanyNameCollection">
                        <TYPE>Company</TYPE>
                        <FETCH>NAME, BASICCOMPANYNAME</FETCH>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    try:
        resp_xml = tally.send_request(payload)
        cleaned = sanitize_xml(resp_xml)
        root = etree.fromstring(cleaned.encode("utf-8"))
        company_elem = root.find(".//DATA/COLLECTION/COMPANY")
        if company_elem is not None:
            for tag in ["BASICCOMPANYNAME", "NAME"]:
                elem = company_elem.find(tag)
                if elem is not None and elem.text and elem.text.strip():
                    return elem.text.strip()
            if company_elem.get("NAME", "").strip():
                return company_elem.get("NAME").strip()
    except Exception as e:
        logger.warning(f"Failed to fetch active company: {e}")
    return "UnknownCompany"


def _parse_tally_date(raw: str) -> str:
    """Convert Tally 8-digit date YYYYMMDD → D-M-YYYY format."""
    if raw and len(raw) == 8 and raw.isdigit():
        y, m, d = raw[:4], raw[4:6], raw[6:]
        return f"{int(d)}-{int(m)}-{y}"
    return raw


def get_company_books_from_date(tally: TallyClient) -> str:
    """
    Fetch the company's 'Books From' date — the day the company was set up in Tally.
    This is the absolute start of all accounting history.
    Returns date in D-M-YYYY format.
    """
    payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>CompanyBooksFromCollection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="CompanyBooksFromCollection">
                        <TYPE>Company</TYPE>
                        <FETCH>BOOKSFROM, STARTINGFROM</FETCH>
                        <COMPUTE>BOOKSFROM: $BooksFrom</COMPUTE>
                        <COMPUTE>STARTINGFROM: $StartingFrom</COMPUTE>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    try:
        resp_xml = tally.send_request(payload)
        cleaned = sanitize_xml(resp_xml)
        root = etree.fromstring(cleaned.encode("utf-8"))
        company_elem = root.find(".//DATA/COLLECTION/COMPANY")
        if company_elem is not None:
            for tag in ["BOOKSFROM", "STARTINGFROM"]:
                elem = company_elem.find(tag)
                if elem is not None and elem.text and elem.text.strip():
                    parsed = _parse_tally_date(elem.text.strip())
                    if parsed:
                        logger.info(f"Company books-from date ({tag}): {parsed}")
                        return parsed
    except Exception as e:
        logger.warning(f"Failed to fetch company books-from date: {e}")
    return None


def get_last_voucher_date(tally: TallyClient) -> str:
    """Fetch the date of the last entered voucher from Tally (returns D-M-YYYY format)."""
    payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>CompanyEndingDateCollection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="CompanyEndingDateCollection">
                        <TYPE>Company</TYPE>
                        <FETCH>ENDINGAT</FETCH>
                        <COMPUTE>ENDINGAT: $EndingAt:Company:##SVCurrentCompany</COMPUTE>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    try:
        resp_xml = tally.send_request(payload)
        cleaned = sanitize_xml(resp_xml)
        root = etree.fromstring(cleaned.encode("utf-8"))
        ending_at_elem = root.find(".//DATA/COLLECTION/COMPANY/ENDINGAT")
        if ending_at_elem is not None and ending_at_elem.text:
            parsed = _parse_tally_date(ending_at_elem.text.strip())
            if parsed:
                return parsed
    except Exception as e:
        logger.warning(f"Failed to fetch last voucher date: {e}")
    return None


def get_last_voucher_date_from_vouchers(tally: TallyClient) -> str:
    """
    Fallback: Query all vouchers without a date filter and pick the latest date.
    Used when the EndingAt company attribute is unavailable.
    Returns D-M-YYYY format.
    """
    payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>LastVoucherDateCollection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="LastVoucherDateCollection">
                        <TYPE>Voucher</TYPE>
                        <FETCH>DATE</FETCH>
                        <SORT>DATE : Descending</SORT>
                        <RANGE>1:1</RANGE>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    try:
        resp_xml = tally.send_request(payload)
        cleaned = sanitize_xml(resp_xml)
        root = etree.fromstring(cleaned.encode("utf-8"))
        date_elem = root.find(".//DATA/COLLECTION/VOUCHER/DATE")
        if date_elem is not None and date_elem.text:
            parsed = _parse_tally_date(date_elem.text.strip())
            if parsed:
                logger.info(f"Last voucher date from voucher scan: {parsed}")
                return parsed
    except Exception as e:
        logger.warning(f"Failed to fetch last voucher date via voucher scan: {e}")
    return None


def get_current_period(tally: TallyClient) -> tuple:
    """Fetch active period from Tally (returns from_date, to_date in D-M-YYYY format)."""
    payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>CompanyPeriodCollection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="CompanyPeriodCollection">
                        <TYPE>Company</TYPE>
                        <FETCH>SVFromDate: ##SVFromDate, SVToDate: ##SVToDate</FETCH>
                        <COMPUTE>SVFromDate: ##SVFromDate</COMPUTE>
                        <COMPUTE>SVToDate: ##SVToDate</COMPUTE>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    try:
        resp_xml = tally.send_request(payload)
        cleaned = sanitize_xml(resp_xml)
        root = etree.fromstring(cleaned.encode("utf-8"))
        company_elem = root.find(".//DATA/COLLECTION/COMPANY")
        if company_elem is not None:
            from_date_raw = company_elem.find("SVFROMDATE")
            to_date_raw = company_elem.find("SVTODATE")
            from_date = _parse_tally_date(from_date_raw.text) if from_date_raw is not None else None
            to_date = _parse_tally_date(to_date_raw.text) if to_date_raw is not None else None
            return from_date, to_date
    except Exception as e:
        logger.warning(f"Failed to fetch current period: {e}")
    return None, None


def fetch_groups(tally: TallyClient) -> list:
    """Fetch all Tally Groups."""
    group_payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>Enhanced Group Collection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="Enhanced Group Collection" ISMODIFY="No">
                        <TYPE>Group</TYPE>
                        <FETCH>Name,Parent,ReservedName,ISREVENUE,ISDEEMEDPOSITIVE</FETCH>
                        <COMPUTE>ISREVENUE: $IsRevenue</COMPUTE>
                        <COMPUTE>ISDEEMEDPOSITIVE: $IsDeemedPositive</COMPUTE>
                        <FETCH>LanguageName.*</FETCH>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    raw_xml = tally.send_request(group_payload)
    cleaned = sanitize_xml(raw_xml)
    root = etree.fromstring(cleaned.encode("utf-8"))
    groups_raw = root.findall(".//DATA/COLLECTION/GROUP")
    groups = []
    for g in groups_raw:
        def txt(tag):
            el = g.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            return ""

        name = txt("NAME")
        if not name:
            name_el = g.find(".//LANGUAGENAME.LIST/NAME.LIST/NAME")
            if name_el is not None and name_el.text:
                name = name_el.text.strip()
        if not name:
            name = g.get("NAME", "").strip()

        parent = txt("PARENT")
        reserved = txt("RESERVEDNAME")

        is_rev_str = txt("ISREVENUE")
        is_deemed_str = txt("ISDEEMEDPOSITIVE")

        is_revenue = True if is_rev_str.lower() in ("yes", "true") else False
        is_deemed_positive = True if is_deemed_str.lower() in ("yes", "true") else False

        if name:
            groups.append({
                "name": name,
                "parent": parent,
                "reserved_name": reserved,
                "is_revenue": is_revenue,
                "is_deemed_positive": is_deemed_positive
            })
    return groups


def resolve_date_range(tally: TallyClient) -> tuple:
    """
    Dynamically resolve the full date range to extract:
      f_date = company's Books From date (day one of accounting history)
      t_date = last voucher date ever entered
    All dates in D-M-YYYY format.
    Falls back through multiple strategies.
    """
    # --- Determine TO date: last voucher entered ---
    t_date = get_last_voucher_date(tally)
    if not t_date:
        logger.warning("EndingAt attribute unavailable. Trying voucher scan fallback...")
        t_date = get_last_voucher_date_from_vouchers(tally)
    if not t_date:
        logger.warning("Could not determine last voucher date. Falling back to current period TO date.")
        _, t_date = get_current_period(tally)
    if not t_date:
        # Absolute last resort: today's date
        today = datetime.now(IST)
        t_date = f"{today.day}-{today.month}-{today.year}"
        logger.warning(f"Using today as fallback TO date: {t_date}")

    # --- Determine FROM date: company inception ---
    f_date = get_company_books_from_date(tally)
    if not f_date:
        logger.warning("BooksFrom unavailable. Trying current period FROM date as fallback.")
        f_date, _ = get_current_period(tally)
    if not f_date:
        # Last resort: use a very early date that predates any Indian company in Tally
        f_date = "1-4-2000"
        logger.warning(f"Using early fallback FROM date: {f_date}")

    logger.info(f"FULL HISTORY DATE RANGE: {f_date}  →  {t_date}")
    return f_date, t_date


def main():
    logger.info("Initializing Tally connection...")
    tally = TallyClient(host=TALLY_HOST, port=TALLY_PORT, timeout=TALLY_TIMEOUT)

    try:
        # 1. Fetch Company metadata
        company = get_active_company(tally)
        logger.info(f"Active Company: {company}")

        # 2. Dynamically resolve FULL date range (company inception → last voucher)
        f_date, t_date = resolve_date_range(tally)

        # 3. Compute the migration/opening-balance date (= company's first day)
        #    Format needed by Zoho opening balances: YYYY-MM-DD
        parts = f_date.split("-")
        if len(parts) == 3:
            migration_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
        else:
            migration_date = "2000-04-01"
        logger.info(f"Migration (opening balance) date: {migration_date}")

        # 4. Extract Ledgers XML (period-sensitive for balances)
        logger.info(f"Querying Chart of Accounts (Ledgers) for full period: {f_date} to {t_date}...")
        ledger_payload = f"""<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>Comprehensive Ledger Collection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVFROMDATE TYPE="Date">{f_date}</SVFROMDATE>
                <SVTODATE TYPE="Date">{t_date}</SVTODATE>
            </STATICVARIABLES>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="Comprehensive Ledger Collection" ISMODIFY="No">
                        <TYPE>Ledger</TYPE>
                        <FETCH>Name,Parent,ClosingBalance,OpeningBalance,ReservedName</FETCH>
                        <FETCH>LedgerPhone,Email,IncomeTaxNumber,PartyGSTIN,LedgerStateName,Pincode,Address.*</FETCH>
                        <FETCH>CreditPeriod,BillDueFromDate</FETCH>
                        <FETCH>LanguageName.*</FETCH>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""

        raw_xml = tally.send_request(ledger_payload)
        logger.info("Fetched raw ledger XML successfully.")

        cleaned_xml = sanitize_xml(raw_xml)
        logger.info("Cleaned ledger XML parsed and prepared.")

        root = etree.fromstring(cleaned_xml.encode("utf-8"))
        parsed_dict = etree_to_dict(root)
        logger.info("Successfully converted XML tree to structured JSON/Dict.")

        # Save to local dumps directory
        dumps_dir = os.path.join(OUTPUT_DIR, "tally_dumps")
        os.makedirs(dumps_dir, exist_ok=True)

        raw_path = os.path.join(dumps_dir, "ledgers_raw.xml")
        cleaned_path = os.path.join(dumps_dir, "ledgers_cleaned.xml")
        json_path = os.path.join(dumps_dir, "ledgers.json")

        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_xml)
        with open(cleaned_path, "w", encoding="utf-8") as f:
            f.write(cleaned_xml)

        timestamp = datetime.now(IST).isoformat()
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "company": company,
                "period": {"from": f_date, "to": t_date},
                "fetched_at": timestamp,
                "parsed_json": parsed_dict
            }, f, indent=2)

        logger.info(f"Ledger dumps saved to {dumps_dir}")

        # 5. Extract Groups XML
        logger.info("Fetching Tally Groups (for hierarchy resolution)...")
        groups = fetch_groups(tally)
        groups_path = os.path.join(dumps_dir, "groups.json")
        with open(groups_path, "w", encoding="utf-8") as f:
            json.dump({
                "company": company,
                "fetched_at": timestamp,
                "groups": groups
            }, f, indent=2)
        logger.info(f"Groups JSON saved: {groups_path} ({len(groups)} groups)")

        # 6. Run Mappers
        logger.info("Running Tally to Zoho mappers (FULL HISTORY MODE)...")

        # Load group map
        gmap = build_group_map(groups)

        # Parse ledgers
        ledgers = parse_ledgers(json_path)
        logger.info(f"Parsed {len(ledgers)} ledgers.")

        # Run Chart of Accounts resolution (opening balances baked in)
        deduped_rows, parent_accounts = run_coa_mapping(ledgers, gmap, dumps_dir)
        logger.info(f"Chart of Accounts mapping complete ({len(deduped_rows)} accounts).")

        # Run Contact resolution (Customers, Vendors, Opening Balances)
        contact_results = run_contact_mapping(
            ledgers, gmap, parent_accounts, migration_date, dumps_dir
        )
        customer_list, vendor_list, bank_list, customer_advances, vendor_advances = contact_results
        logger.info("Contact & opening balances mapping complete.")

        # Run Items extraction (stock items master data — no date filter needed)
        logger.info("Extracting Stock Items from Tally...")
        run_item_mapping(tally, dumps_dir)
        logger.info("Items extraction & mapping complete.")

        # Run ALL voucher mappers with dynamically resolved full date range
        logger.info(f"Extracting ALL historical invoices: {f_date} → {t_date}")
        run_invoice_mapping(tally, dumps_dir, f_date, t_date)
        logger.info("Invoice extraction & mapping complete.")

        logger.info(f"Extracting ALL historical bills: {f_date} → {t_date}")
        run_bill_mapping(tally, dumps_dir, f_date, t_date)
        logger.info("Bills extraction & mapping complete.")

        logger.info(f"Extracting ALL historical customer payments: {f_date} → {t_date}")
        run_payment_mapping(tally, dumps_dir, f_date, t_date, customer_advances)
        logger.info("Customer payments extraction & mapping complete.")

        logger.info(f"Extracting ALL historical vendor payments: {f_date} → {t_date}")
        run_vendor_payment_mapping(tally, dumps_dir, f_date, t_date, vendor_advances)
        logger.info("Vendor payments extraction & mapping complete.")

        logger.info("=" * 60)
        logger.info("END-TO-END FULL HISTORY MIGRATION RUN COMPLETED SUCCESSFULLY!")
        logger.info(f"  Company  : {company}")
        logger.info(f"  From     : {f_date}")
        logger.info(f"  To       : {t_date}")
        logger.info(f"  Outputs  : {os.path.abspath(dumps_dir)}")
        logger.info("=" * 60)
        logger.info("ZOHO IMPORT ORDER:")
        logger.info("  1. zoho_coa_import.csv              (Chart of Accounts + opening balances)")
        logger.info("  2. zoho_customers_import.csv         (Customers)")
        logger.info("  3. zoho_vendors_import.csv           (Vendors)")
        logger.info("  4. zoho_items_import.csv             (Items / Stock Items)")
        logger.info("  5. zoho_invoices_import*.csv         (Sales Invoices — all parts)")
        logger.info("  6. zoho_bills_import*.csv            (Purchase Bills — all parts)")
        logger.info("  7. zoho_customer_payments_import.csv (Customer Payments / Receipts)")
        logger.info("  8. zoho_vendor_payments_import.csv   (Vendor Payments)")
        logger.info("=" * 60)

    except Exception as e:
        logger.exception(f"An error occurred during migration: {e}")


if __name__ == "__main__":
    main()
