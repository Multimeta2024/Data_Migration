# mappers/invoice_mapper.py

import os
import csv
import logging
import re
from datetime import datetime, timedelta
from lxml import etree

from config.constants import CURRENCY, GST_STATE_MAP, INVOICE_HEADERS
from utils.gst_helpers import get_state_code, infer_gst_treatment
from utils.date_helpers import format_date, calculate_due_date, get_fy_batches
from utils.math_helpers import clean_float, parse_qty_unit, parse_rate, parse_due_days
from core.xml_parser import sanitize_xml

logger = logging.getLogger(__name__)

_TAX_LEDGER_REGEX = re.compile(
    r"\b(CGST|SGST|IGST|UTGST|OUTPUT GST|INPUT GST|TAX|DUTIES|CESS|VAT|ROUND OFF|ROUNDOFF)\b",
    re.IGNORECASE
)

def is_tax_ledger(name):
    if not name:
        return False
    return bool(_TAX_LEDGER_REGEX.search(name))

def format_number(val):
    """Formats numeric values to prevent float representation errors (.0) in Zoho."""
    if val is None:
        return ""
    try:
        f = float(val)
        if f.is_integer():
            return str(int(f))
        return f"{f:.2f}"
    except (ValueError, TypeError):
        return str(val)

def format_invoice_number(vch_no: str, max_len: int = 16) -> str:
    """Ensures invoice number adheres to Zoho/GST strict 16-character limit."""
    if not vch_no or len(vch_no) <= max_len:
        return vch_no
    # Replace 4-digit year format (e.g. 2024-25 or 2024-2025) with 2-digit year (e.g. 24-25)
    shortened = re.sub(r"20(\d{2})[-/](?:20)?(\d{2})", r"\1-\2", vch_no)
    if len(shortened) <= max_len:
        return shortened
    return shortened[:max_len]

def snap_to_standard_gst(tax_percent: float) -> int:
    """Snaps calculated tax percentage to standard Indian GST slabs (0, 5, 12, 18, 28)."""
    val = round(tax_percent, 2)
    if val <= 2.5:
        return 0
    elif val <= 8.5:
        return 5
    elif val <= 15.0:
        return 12
    elif val <= 23.0:
        return 18
    else:
        return 28

def get_zoho_tax_info(tax_percent, is_interstate):
    """Returns (item_tax_name, item_tax_type) formatted exactly as configured in Zoho Books organization."""
    tax_val = snap_to_standard_gst(tax_percent if tax_percent is not None else 0.0)
    if is_interstate:
        return f"IGST{tax_val}", "IGST"
    else:
        return f"GST{tax_val}", "Tax Group"

def query_sales_vouchers(tally_client, f_date: str, t_date: str):
    """
    Fetch all Sales vouchers from Tally for the given date range.
    f_date / t_date must be in D-M-YYYY format (e.g. '1-4-2000', '29-7-2026').
    """
    payload = f"""<ENVELOPE>
        <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>Export Data</TALLYREQUEST>
            <TYPE>Collection</TYPE>
            <ID>SalesVouchers</ID>
        </HEADER>
        <BODY>
            <DESC>
                <STATICVARIABLES>
                    <SVFROMDATE TYPE="Date">{f_date}</SVFROMDATE>
                    <SVTODATE TYPE="Date">{t_date}</SVTODATE>
                </STATICVARIABLES>
                <TDL>
                    <TDLMESSAGE>
                        <COLLECTION NAME="SalesVouchers">
                            <TYPE>Voucher</TYPE>
                            <FILTER>IsSalesFilter</FILTER>
                            <FETCH>DATE, VOUCHERNUMBER, PARTYLEDGERNAME, PLACEOFSUPPLY, PARTYGSTIN, GSTREGISTRATIONTYPE, NARRATION</FETCH>
                            <FETCH>BASICBUYERADDRESS.*, BASICDUEDATEOFPYMT</FETCH>
                            <FETCH>ALLINVENTORYENTRIES.*</FETCH>
                            <FETCH>LEDGERENTRIES.*</FETCH>
                        </COLLECTION>
                        <SYSTEM TYPE="Formula" NAME="IsSalesFilter">$$IsSales:$VoucherTypeName</SYSTEM>
                    </TDLMESSAGE>
                </TDL>
            </DESC>
        </BODY>
    </ENVELOPE>"""
    return tally_client.send_request(payload)

# Maximum rows per Zoho import file (Zoho Books limit is ~25,000; we use 20,000 for safety)
_ZOHO_MAX_ROWS = 20_000


def _write_split_csv(base_path: str, headers: list, rows: list, label: str) -> list:
    """
    Write rows to one or more split CSV files.
    If len(rows) <= _ZOHO_MAX_ROWS, writes a single file (base_path).
    Otherwise, writes base_name_part1.csv, base_name_part2.csv, etc.
    Returns list of file paths written.
    """
    written = []
    if len(rows) <= _ZOHO_MAX_ROWS:
        _safe_write_csv(base_path, headers, rows)
        written.append(base_path)
        logger.info(f"{label}: {len(rows)} rows → {base_path}")
    else:
        base, ext = os.path.splitext(base_path)
        part_num = 1
        for start in range(0, len(rows), _ZOHO_MAX_ROWS):
            chunk = rows[start: start + _ZOHO_MAX_ROWS]
            part_path = f"{base}_part{part_num}{ext}"
            _safe_write_csv(part_path, headers, chunk)
            written.append(part_path)
            logger.info(f"{label} Part {part_num}: {len(chunk)} rows → {part_path}")
            part_num += 1
    return written


def _safe_write_csv(path: str, headers: list, rows: list):
    """Write CSV; if permission denied, write to an _unlocked fallback."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    def _do_write(p):
        with open(p, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    try:
        _do_write(path)
    except PermissionError:
        base, ext = os.path.splitext(path)
        fallback = base + "_unlocked" + ext
        logger.warning(f"Permission denied on {path}. Writing to: {fallback}")
        _do_write(fallback)


def run_invoice_mapping(tally_client, out_dir, f_date: str, t_date: str):
    """
    Fetches ALL sales vouchers from Tally ONE FINANCIAL YEAR AT A TIME
    to avoid Tally timeouts, maps them to Zoho invoices, and writes CSV(s).
    """
    base_csv = os.path.join(out_dir, "zoho_invoices_import.csv")
    batches = get_fy_batches(f_date, t_date)
    logger.info(f"Fetching invoices in {len(batches)} FY batch(es): {f_date} → {t_date}")

    zoho_rows = []
    assigned_vouchers = {}  # (base_vch_no, date_str, party_name) -> final_vch_no
    vch_no_counts = {}      # base_vch_no -> count of unique (date_str, party_name) pairs

    for batch_num, (b_from, b_to) in enumerate(batches, start=1):
        logger.info(f"  [Invoices {batch_num}/{len(batches)}] {b_from} → {b_to} ...")
        xml_data = query_sales_vouchers(tally_client, b_from, b_to)
        xml_data_cleaned = sanitize_xml(xml_data)
        parser = etree.XMLParser(recover=True)
        root = etree.fromstring(xml_data_cleaned.encode("utf-8", errors="ignore"), parser=parser)
        vouchers = root.findall(".//VOUCHER")
        logger.info(f"  [Invoices {batch_num}/{len(batches)}] {len(vouchers)} vouchers found.")

        for v in vouchers:
            vch_no_node = v.find("VOUCHERNUMBER")
            vch_no_raw = (vch_no_node.text or "").strip() if vch_no_node is not None else ""
            if not vch_no_raw:
                continue
            base_vch_no = format_invoice_number(vch_no_raw)

            date_node = v.find("DATE")
            date_str = format_date(date_node.text) if date_node is not None else ""

            party_node = v.find("PARTYLEDGERNAME")
            party_name = (party_node.text or "").strip() if party_node is not None else ""

            if not party_name:
                for p_tag in ("PARTYNAME", "BASICBUYERNAME", "BASICPARTYNAME", "BUYERNAME", "CUSTOMERNAME"):
                    n = v.find(p_tag)
                    if n is not None and (n.text or "").strip():
                        party_name = n.text.strip()
                        break

            ledger_entries = v.findall(".//LEDGERENTRIES.LIST")
            party_ledgers = [le for le in ledger_entries
                             if (le.find("ISPARTYLEDGER") is not None and le.find("ISPARTYLEDGER").text == "Yes")]

            if not party_name and party_ledgers:
                pn = party_ledgers[0].find("LEDGERNAME")
                if pn is not None and pn.text:
                    party_name = pn.text.strip()

            if not party_name:
                for le in ledger_entries:
                    lname = (le.find("LEDGERNAME").text or "").strip() if le.find("LEDGERNAME") is not None else ""
                    if not lname or is_tax_ledger(lname):
                        continue
                    is_deemed_pos = (le.find("ISDEEMEDPOSITIVE").text or "").strip() if le.find("ISDEEMEDPOSITIVE") is not None else ""
                    if is_deemed_pos == "Yes":
                        party_name = lname
                        break

            if not party_name:
                party_name = "Unspecified Customer"

            v_key = (base_vch_no, date_str, party_name)
            if v_key in assigned_vouchers:
                vch_no = assigned_vouchers[v_key]
            else:
                if base_vch_no not in vch_no_counts:
                    vch_no_counts[base_vch_no] = 1
                    vch_no = base_vch_no
                else:
                    vch_no_counts[base_vch_no] += 1
                    vch_no = f"{base_vch_no}-{vch_no_counts[base_vch_no]}"
                    logger.info(f"Deduplicated reused invoice number '{base_vch_no}' -> '{vch_no}' for party '{party_name}' on date '{date_str}'")
                assigned_vouchers[v_key] = vch_no

            gstin_node = v.find("PARTYGSTIN")
            gstin = (gstin_node.text or "").strip().upper() if gstin_node is not None else ""

            reg_type_node = v.find("GSTREGISTRATIONTYPE")
            reg_type = (reg_type_node.text or "").strip().lower() if reg_type_node is not None else ""

            if reg_type in ("regular", "composition"):
                gst_treatment = "business_gst"
            elif gstin:
                gst_treatment = "business_gst"
            else:
                gst_treatment = "business_unregistered"

            pos_node = v.find("PLACEOFSUPPLY")
            pos_str = (pos_node.text or "").strip() if pos_node is not None else ""
            pos_code = get_state_code(pos_str)
            if not pos_code and gstin and len(gstin) >= 2 and gstin[:2].isdigit():
                pos_code = GST_STATE_MAP.get(gstin[:2], "TN")
            if not pos_code:
                pos_code = "TN"

            narration_node = v.find("NARRATION")
            notes = (narration_node.text or "").strip() if narration_node is not None else ""

            terms_node = v.find("BASICDUEDATEOFPYMT")
            terms_str = (terms_node.text or "").strip() if terms_node is not None else ""
            due_days = parse_due_days(terms_str)

            party_ledgers = [le for le in v.findall(".//LEDGERENTRIES.LIST")
                             if (le.find("ISPARTYLEDGER") is not None and le.find("ISPARTYLEDGER").text == "Yes")]
            if not due_days and party_ledgers:
                for cp in party_ledgers[0].findall(".//BILLALLOCATIONS.LIST/BILLCREDITPERIOD"):
                    if cp.text:
                        due_days = parse_due_days(cp.text)
                        break

            payment_terms_num = str(due_days)
            payment_terms_label = f"Net {due_days}" if due_days > 0 else "Due on Receipt"
            due_date = calculate_due_date(date_str, due_days)

            # Voucher-level tax rate calculation
            total_tax_amt = 0.0
            total_revenue_amt = 0.0
            ledger_entries = v.findall(".//LEDGERENTRIES.LIST")
            for le in ledger_entries:
                lname_node = le.find("LEDGERNAME")
                lname = (lname_node.text or "").strip() if (lname_node is not None and lname_node.text) else ""
                if not lname:
                    continue
                lamt_str = le.find("AMOUNT").text if le.find("AMOUNT") is not None else "0"
                lamt = clean_float(lamt_str)
                is_party = le.find("ISPARTYLEDGER").text if le.find("ISPARTYLEDGER") is not None else "No"
                if is_party == "Yes":
                    continue
                if "CGST" in lname.upper() or "SGST" in lname.upper() or "IGST" in lname.upper():
                    total_tax_amt += abs(lamt)
                elif not is_tax_ledger(lname):
                    total_revenue_amt += abs(lamt)

            voucher_tax_rate = 0.0
            if total_revenue_amt > 0:
                voucher_tax_rate = (total_tax_amt / total_revenue_amt) * 100.0

            inv_entries = [ie for ie in v.findall(".//ALLINVENTORYENTRIES.LIST")
                           if ie.find("STOCKITEMNAME") is not None and (ie.find("STOCKITEMNAME").text or "").strip()]

            is_interstate = (pos_code != "TN")

            # CASE 1: Item Invoice (contains stock items)
            if len(inv_entries) > 0:
                for ie in inv_entries:
                    item_name_node = ie.find("STOCKITEMNAME")
                    item_name = (item_name_node.text or "").strip() if item_name_node is not None else ""
                    hsn_node = ie.find("GSTHSNNAME")
                    hsn = (hsn_node.text or "").strip() if hsn_node is not None else ""
                    desc_node = ie.find("DESCRIPTION")
                    desc = (desc_node.text or "").strip() if desc_node is not None else ""
                    qty_node = ie.find("BILLEDQTY")
                    qty_str = qty_node.text if qty_node is not None else "1"
                    qty_val, unit_val = parse_qty_unit(qty_str)
                    amt_node = ie.find("AMOUNT")
                    amt_val = abs(clean_float(amt_node.text if amt_node is not None else "0"))
                    rate_node = ie.find("RATE")
                    rate_str = rate_node.text if rate_node is not None else ""
                    item_price = (amt_val / qty_val) if qty_val != 0 else parse_rate(rate_str)
                    sales_acc_node = ie.find(".//ACCOUNTINGALLOCATIONS.LIST/LEDGERNAME")
                    sales_acc = (sales_acc_node.text or "").strip() if (sales_acc_node is not None and sales_acc_node.text) else "Sales"

                    cgst_rate = sgst_rate = igst_rate = 0.0
                    for rd in ie.findall(".//RATEDETAILS.LIST"):
                        head = rd.find("GSTRATEDUTYHEAD")
                        rate_n = rd.find("GSTRATE")
                        if head is not None and rate_n is not None:
                            h_text = (head.text or "").strip().upper()
                            r_text = (rate_n.text or "").strip()
                            if r_text:
                                try:
                                    val = float(r_text)
                                    if h_text == "CGST": cgst_rate = val
                                    elif h_text in ("SGST", "SGST/UTGST", "UTGST"): sgst_rate = val
                                    elif h_text == "IGST": igst_rate = val
                                except ValueError:
                                    pass

                    item_tax_percent = igst_rate if igst_rate > 0 else (cgst_rate + sgst_rate)
                    if item_tax_percent == 0 and voucher_tax_rate > 0:
                        item_tax_percent = voucher_tax_rate
                    item_tax, item_tax_type = get_zoho_tax_info(item_tax_percent, is_interstate)
                    snapped_tax_rate = snap_to_standard_gst(item_tax_percent)

                    zoho_rows.append({
                        "Invoice Number": vch_no, "Estimate Number": "",
                        "Invoice Date": date_str, "Invoice Status": "Sent",
                        "Customer Name": party_name, "GST Treatment": gst_treatment,
                        "GST Identification Number (GSTIN)": gstin,
                        "Place of Supply": pos_code,
                        "Payment Terms": payment_terms_num, "Payment Terms Label": payment_terms_label,
                        "Due Date": due_date, "Currency Code": CURRENCY, "Exchange Rate": "1",
                        "Account": sales_acc, "Item Name": item_name, "SKU": "",
                        "Item Desc": desc or notes, "Item Type": "goods", "HSN/SAC": hsn,
                        "Quantity": format_number(qty_val), "Usage unit": unit_val,
                        "Item Price": format_number(item_price),
                        "Item Tax Exemption Reason": "", "Is Inclusive Tax": "FALSE",
                        "Item Tax": item_tax, "Item Tax Type": item_tax_type,
                        "Item Tax %": str(snapped_tax_rate),
                        "Is Discount Before Tax": "TRUE",
                        "Branch Name": "Head Office", "Warehouse Name": "Head Office", "Notes": notes
                    })

                # Add additional charge ledger entries (non-tax, non-party)
                for le in ledger_entries:
                    lname_node = le.find("LEDGERNAME")
                    lname = (lname_node.text or "").strip() if (lname_node is not None and lname_node.text) else ""
                    if not lname:
                        continue
                    is_party = le.find("ISPARTYLEDGER").text if le.find("ISPARTYLEDGER") is not None else "No"
                    if is_party == "Yes" or is_tax_ledger(lname):
                        continue
                    lamt_str = le.find("AMOUNT").text if le.find("AMOUNT") is not None else "0"
                    lamt = clean_float(lamt_str)
                    if lamt == 0:
                        continue
                    item_tax, item_tax_type = get_zoho_tax_info(0.0, is_interstate)
                    zoho_rows.append({
                        "Invoice Number": vch_no, "Estimate Number": "",
                        "Invoice Date": date_str, "Invoice Status": "Sent",
                        "Customer Name": party_name, "GST Treatment": gst_treatment,
                        "GST Identification Number (GSTIN)": gstin,
                        "Place of Supply": pos_code,
                        "Payment Terms": payment_terms_num, "Payment Terms Label": payment_terms_label,
                        "Due Date": due_date, "Currency Code": CURRENCY, "Exchange Rate": "1",
                        "Account": lname, "Item Name": lname, "SKU": "",
                        "Item Desc": f"Additional charge: {lname}", "Item Type": "service",
                        "HSN/SAC": "999900", "Quantity": "1", "Usage unit": "count",
                        "Item Price": format_number(lamt),
                        "Item Tax Exemption Reason": "", "Is Inclusive Tax": "FALSE",
                        "Item Tax": item_tax, "Item Tax Type": item_tax_type, "Item Tax %": "0",
                        "Is Discount Before Tax": "TRUE",
                        "Branch Name": "Head Office", "Warehouse Name": "Head Office", "Notes": notes
                    })

            # CASE 2: Accounting / Service Invoice
            else:
                for le in ledger_entries:
                    lname_node = le.find("LEDGERNAME")
                    lname = (lname_node.text or "").strip() if (lname_node is not None and lname_node.text) else ""
                    if not lname:
                        continue
                    is_party = le.find("ISPARTYLEDGER").text if le.find("ISPARTYLEDGER") is not None else "No"
                    if is_party == "Yes" or is_tax_ledger(lname):
                        continue
                    lamt_str = le.find("AMOUNT").text if le.find("AMOUNT") is not None else "0"
                    lamt = clean_float(lamt_str)
                    if lamt == 0:
                        continue
                    item_tax, item_tax_type = get_zoho_tax_info(voucher_tax_rate, is_interstate)
                    snapped_tax_rate = snap_to_standard_gst(voucher_tax_rate)
                    zoho_rows.append({
                        "Invoice Number": vch_no, "Estimate Number": "",
                        "Invoice Date": date_str, "Invoice Status": "Sent",
                        "Customer Name": party_name, "GST Treatment": gst_treatment,
                        "GST Identification Number (GSTIN)": gstin,
                        "Place of Supply": pos_code,
                        "Payment Terms": payment_terms_num, "Payment Terms Label": payment_terms_label,
                        "Due Date": due_date, "Currency Code": CURRENCY, "Exchange Rate": "1",
                        "Account": lname, "Item Name": lname, "SKU": "",
                        "Item Desc": notes or f"Service: {lname}", "Item Type": "service",
                        "HSN/SAC": "999900", "Quantity": "1", "Usage unit": "count",
                        "Item Price": format_number(lamt),
                        "Item Tax Exemption Reason": "", "Is Inclusive Tax": "FALSE",
                        "Item Tax": item_tax, "Item Tax Type": item_tax_type,
                        "Item Tax %": str(snapped_tax_rate),
                        "Is Discount Before Tax": "TRUE",
                        "Branch Name": "Head Office", "Warehouse Name": "Head Office", "Notes": notes
                    })

    _write_split_csv(base_csv, INVOICE_HEADERS, zoho_rows, "Invoices")
    logger.info(f"Total invoice line items written: {len(zoho_rows)}")
    logger.info(f"Unique invoices written: {len(set(r['Invoice Number'] for r in zoho_rows))}")
    return zoho_rows


