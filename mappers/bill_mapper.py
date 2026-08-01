# mappers/bill_mapper.py

import os
import csv
import logging
from lxml import etree

from config.constants import CURRENCY, GST_STATE_MAP, BILL_HEADERS
from utils.gst_helpers import get_state_code, infer_gst_treatment
from utils.date_helpers import format_date, calculate_due_date, get_fy_batches
from utils.math_helpers import clean_float, parse_due_days
from core.xml_parser import sanitize_xml
from mappers.invoice_mapper import format_invoice_number, is_tax_ledger, get_zoho_tax_info, _write_split_csv

logger = logging.getLogger(__name__)

def query_purchase_vouchers(tally_client, f_date: str, t_date: str):
    """
    Fetch all Purchase vouchers from Tally for the given date range.
    f_date / t_date must be in D-M-YYYY format (e.g. '1-4-2000', '29-7-2026').
    """
    payload = f"""<ENVELOPE>
        <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>Export Data</TALLYREQUEST>
            <TYPE>Collection</TYPE>
            <ID>PurchaseVouchers</ID>
        </HEADER>
        <BODY>
            <DESC>
                <STATICVARIABLES>
                    <SVFROMDATE TYPE="Date">{f_date}</SVFROMDATE>
                    <SVTODATE TYPE="Date">{t_date}</SVTODATE>
                </STATICVARIABLES>
                <TDL>
                    <TDLMESSAGE>
                        <COLLECTION NAME="PurchaseVouchers">
                            <TYPE>Voucher</TYPE>
                            <FILTER>IsPurchaseFilter</FILTER>
                            <FETCH>DATE, VOUCHERNUMBER, PARTYLEDGERNAME, NARRATION, PARTYGSTIN, PLACEOFSUPPLY, GSTREGISTRATIONTYPE, BASICDUEDATEOFPYMT</FETCH>
                            <FETCH>ALLLEDGERENTRIES.*</FETCH>
                            <FETCH>LEDGERENTRIES.*</FETCH>
                        </COLLECTION>
                        <SYSTEM TYPE="Formula" NAME="IsPurchaseFilter">$$IsPurchase:$VoucherTypeName</SYSTEM>
                    </TDLMESSAGE>
                </TDL>
            </DESC>
        </BODY>
    </ENVELOPE>"""
    return tally_client.send_request(payload)

def run_bill_mapping(tally_client, out_dir, f_date: str, t_date: str):
    """
    Fetches ALL purchase vouchers from Tally ONE FINANCIAL YEAR AT A TIME
    to avoid Tally timeouts, maps them to Zoho Bills, and writes CSV(s).
    """
    base_csv = os.path.join(out_dir, "zoho_bills_import.csv")
    batches = get_fy_batches(f_date, t_date)
    logger.info(f"Fetching bills in {len(batches)} FY batch(es): {f_date} → {t_date}")
    zoho_rows = []
    assigned_vouchers = {}  # (base_vch_no, date_str, party_name) -> final_vch_no
    vch_no_counts = {}      # base_vch_no -> count of unique (date_str, party_name) pairs

    for batch_num, (b_from, b_to) in enumerate(batches, start=1):
        logger.info(f"  [Bills {batch_num}/{len(batches)}] {b_from} → {b_to} ...")
        xml_data = query_purchase_vouchers(tally_client, b_from, b_to)
        xml_data_cleaned = sanitize_xml(xml_data)
        parser = etree.XMLParser(recover=True)
        root = etree.fromstring(xml_data_cleaned.encode("utf-8", errors="ignore"), parser=parser)
        vouchers = root.findall(".//VOUCHER")
        logger.info(f"  [Bills {batch_num}/{len(batches)}] {len(vouchers)} vouchers found.")
    
        for v in vouchers:
            vch_no_node = v.find("VOUCHERNUMBER")
            vch_no_raw = (vch_no_node.text or "").strip() if vch_no_node is not None else ""
            if not vch_no_raw:
                continue
            base_vch_no = format_invoice_number(vch_no_raw)
                
            date_node = v.find("DATE")
            date_str = format_date(date_node.text) if date_node is not None else ""
            
            # Party / Vendor Name extraction with multi-level fallbacks
            party_node = v.find("PARTYLEDGERNAME")
            party_name = (party_node.text or "").strip() if party_node is not None else ""

            if not party_name:
                for p_tag in ("PARTYNAME", "BASICBUYERNAME", "BASICPARTYNAME", "SUPPLIERNAME", "VENDORNAME"):
                    n = v.find(p_tag)
                    if n is not None and (n.text or "").strip():
                        party_name = n.text.strip()
                        break

            ledger_entries = v.findall(".//LEDGERENTRIES.LIST") + v.findall(".//ALLLEDGERENTRIES.LIST")
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
                    if is_deemed_pos == "No":
                        party_name = lname
                        break

            if not party_name:
                for le in ledger_entries:
                    lname = (le.find("LEDGERNAME").text or "").strip() if le.find("LEDGERNAME") is not None else ""
                    if not lname or is_tax_ledger(lname):
                        continue
                    lname_upper = lname.upper()
                    if not any(exp_kw in lname_upper for exp_kw in ("PURCHASE", "EXPENSE", "FREIGHT", "CHARGES", "DUTY")):
                        party_name = lname
                        break

            if not party_name:
                party_name = "Unspecified Vendor"

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
                    logger.info(f"Deduplicated reused bill number '{base_vch_no}' -> '{vch_no}' for vendor '{party_name}' on date '{date_str}'")
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
            
            if not due_days and party_ledgers:
                for cp in party_ledgers[0].findall(".//BILLALLOCATIONS.LIST/BILLCREDITPERIOD"):
                    if cp.text:
                        due_days = parse_due_days(cp.text)
                        break
                        
            payment_terms_num = str(due_days)
            payment_terms_label = f"Net {due_days}" if due_days > 0 else "Due on Receipt"
            due_date = calculate_due_date(date_str, due_days)
            
            # Voucher-level tax calculation
            total_tax_amt = 0.0
            total_expense_amt = 0.0
            
            for le in ledger_entries:
                lname = (le.find("LEDGERNAME").text or "").strip() if le.find("LEDGERNAME") is not None else ""
                lamt_str = le.find("AMOUNT").text if le.find("AMOUNT") is not None else "0"
                lamt = abs(clean_float(lamt_str))
                
                is_party = le.find("ISPARTYLEDGER").text if le.find("ISPARTYLEDGER") is not None else "No"
                if is_party == "Yes" or lname == party_name:
                    continue
                    
                if is_tax_ledger(lname):
                    total_tax_amt += lamt
                else:
                    total_expense_amt += lamt
                    
            tax_rate = 0.0
            if total_expense_amt > 0 and total_tax_amt > 0:
                tax_rate = round((total_tax_amt / total_expense_amt) * 100)

            is_interstate = (pos_code != "TN")
            tax_name, tax_type = get_zoho_tax_info(tax_rate, is_interstate)
            if tax_rate > 0 and tax_name:
                tax_exemption_reason = ""
                tax_pct_str = str(int(tax_rate))
            else:
                tax_name = ""
                tax_type = ""
                tax_exemption_reason = "Out of Scope"
                tax_pct_str = "0"

            expense_lines = []
            for le in ledger_entries:
                lname_node = le.find("LEDGERNAME")
                lname = (lname_node.text or "").strip() if (lname_node is not None and lname_node.text) else ""
                if not lname:
                    continue

                lamt_str = le.find("AMOUNT").text if le.find("AMOUNT") is not None else "0"
                lamt = abs(clean_float(lamt_str))

                is_party = le.find("ISPARTYLEDGER").text if le.find("ISPARTYLEDGER") is not None else "No"
                if is_party == "Yes" or lname.lower() == party_name.lower():
                    continue

                if is_tax_ledger(lname):
                    continue

                expense_lines.append((lname, lamt))

            if not expense_lines:
                fallback_amt = 0.0
                if party_ledgers:
                    amt_node = party_ledgers[0].find("AMOUNT")
                    if amt_node is not None and amt_node.text:
                        fallback_amt = abs(clean_float(amt_node.text))
                expense_lines.append(("Purchase", fallback_amt))

            for lname, lamt in expense_lines:
                account_name = lname if lname else "Purchase"
                zoho_rows.append({
                    "Bill Number": vch_no,
                    "Bill Date": date_str,
                    "Vendor Name": party_name,
                    "GST Treatment": gst_treatment,
                    "GST Identification Number (GSTIN)": gstin,
                    "Place of Supply": pos_code,
                    "PurchaseOrder": "",
                    "Payment Terms": payment_terms_num,
                    "Payment Terms Label": payment_terms_label,
                    "Due Date": due_date,
                    "Currency Code": CURRENCY,
                    "Exchange Rate": "1",
                    "Account": account_name,
                    "Item Name": "",
                    "SKU": "",
                    "Item Desc": notes or account_name,
                    "Item Type": "service",
                    "HSN/SAC": "",
                    "Quantity": "1",
                    "Usage unit": "pcs",
                    "Rate": f"{lamt:.2f}",
                    "Item Price": f"{lamt:.2f}",
                    "Is Inclusive Tax": "false",
                    "Tax Name": tax_name,
                    "Tax Percentage": tax_pct_str,
                    "Tax Type": tax_type,
                    "Tax Exemption Reason": tax_exemption_reason,
                    "Item Tax": tax_name,
                    "Item Tax Type": tax_type,
                    "Item Tax %": tax_pct_str,
                    "Item Tax Exemption Reason": tax_exemption_reason,
                    "Branch Name": "Head Office"
                })

    _write_split_csv(base_csv, BILL_HEADERS, zoho_rows, "Bills")
    logger.info(f"Total bill line items written: {len(zoho_rows)}")
    logger.info(f"Unique bills written: {len(set(r['Bill Number'] for r in zoho_rows))}")
    return zoho_rows
