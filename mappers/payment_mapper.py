# mappers/payment_mapper.py

import os
import csv
import logging
from lxml import etree

from config.constants import PAYMENT_HEADERS
from utils.date_helpers import format_date, get_fy_batches
from utils.math_helpers import clean_float
from core.xml_parser import sanitize_xml
from mappers.invoice_mapper import format_invoice_number, _write_split_csv

logger = logging.getLogger(__name__)

def query_receipt_vouchers(tally_client, f_date: str, t_date: str):
    """
    Fetch all Receipt vouchers from Tally for the given date range.
    f_date / t_date must be in D-M-YYYY format.
    """
    payload = f"""<ENVELOPE>
        <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>Export Data</TALLYREQUEST>
            <TYPE>Collection</TYPE>
            <ID>ReceiptVouchers</ID>
        </HEADER>
        <BODY>
            <DESC>
                <STATICVARIABLES>
                    <SVFROMDATE TYPE="Date">{f_date}</SVFROMDATE>
                    <SVTODATE TYPE="Date">{t_date}</SVTODATE>
                </STATICVARIABLES>
                <TDL>
                    <TDLMESSAGE>
                        <COLLECTION NAME="ReceiptVouchers">
                            <TYPE>Voucher</TYPE>
                            <FILTER>IsReceiptFilter</FILTER>
                            <FETCH>DATE, VOUCHERNUMBER, PARTYLEDGERNAME, NARRATION</FETCH>
                            <FETCH>ALLLEDGERENTRIES.*</FETCH>
                            <FETCH>LEDGERENTRIES.*</FETCH>
                        </COLLECTION>
                        <SYSTEM TYPE="Formula" NAME="IsReceiptFilter">$$IsReceipt:$VoucherTypeName</SYSTEM>
                    </TDLMESSAGE>
                </TDL>
            </DESC>
        </BODY>
    </ENVELOPE>"""
    return tally_client.send_request(payload)

def run_payment_mapping(tally_client, out_dir, f_date: str, t_date: str, customer_advances=None):
    """
    Fetches ALL receipt vouchers from Tally ONE FINANCIAL YEAR AT A TIME
    to avoid timeouts, then generates the Zoho customer payments CSV.
    """
    base_csv = os.path.join(out_dir, "zoho_customer_payments_import.csv")
    batches = get_fy_batches(f_date, t_date)
    logger.info(f"Fetching receipts in {len(batches)} FY batch(es): {f_date} → {t_date}")

    all_xml_vouchers = []
    for batch_num, (b_from, b_to) in enumerate(batches, start=1):
        logger.info(f"  [Receipts {batch_num}/{len(batches)}] {b_from} → {b_to} ...")
        xml_data = query_receipt_vouchers(tally_client, b_from, b_to)
        xml_cleaned = sanitize_xml(xml_data)
        parser = etree.XMLParser(recover=True)
        root = etree.fromstring(xml_cleaned.encode("utf-8", errors="ignore"), parser=parser)
        batch_vouchers = root.findall(".//VOUCHER")
        logger.info(f"  [Receipts {batch_num}/{len(batches)}] {len(batch_vouchers)} vouchers found.")
        all_xml_vouchers.extend(batch_vouchers)

    vouchers = all_xml_vouchers
    logger.info(f"Total receipt vouchers across all batches: {len(vouchers)}")

    payment_rows = []

    # Include opening customer advances as unapplied payments/advances
    if customer_advances:
        for idx, adv in enumerate(customer_advances, start=1):
            payment_rows.append({
                "Payment Number Prefix": "ADV-",
                "Payment Number Suffix": str(idx),
                "Customer Name": adv.get("Customer Name", ""),
                "Place of Supply": "",
                "GST Treatment": "",
                "GST Identification Number (GSTIN)": "",
                "Payment Type": "Customer Advance",
                "Description of Supply": "",
                "Tax Name": "", "Tax Percentage": "", "Tax Type": "",
                "Date": adv.get("Date", ""),
                "Mode": "Cash",
                "Exchange Rate": "1",
                "Amount": adv.get("Amount", ""),
                "Description": adv.get("Description", "Opening Customer Advance"),
                "Bank Charges": "",
                "Tax Account": "",
                "Deposit To": "Petty Cash Ledger",
                "Reference Number": "Opening Customer Advance",
                "Invoice Number": "",
                "Amount Applied to Invoice": "",
                "Invoice Amount": "",
                "Withholding Tax Amount": "0",
                "Branch Name": "Head Office"
            })
        logger.info(f"Pre-populated {len(customer_advances)} opening customer advances into payments CSV.")

    
    # Load Bank and Cash account names from COA
    coa_file = os.path.join(out_dir, "zoho_coa_import.csv")
    bank_cash_accounts = set()
    if os.path.exists(coa_file):
        with open(coa_file, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("Account Type") in ("Bank", "Cash", "Credit Card"):
                    bank_cash_accounts.add(r["Account Name"].strip())

    # Load valid invoice numbers from the already-generated invoices CSV
    inv_file = os.path.join(out_dir, "zoho_invoices_import.csv")
    valid_invoice_numbers = set()
    if os.path.exists(inv_file):
        with open(inv_file, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                valid_invoice_numbers.add(r["Invoice Number"].strip())
    # Load valid customers from zoho_customers_import.csv
    cust_file = os.path.join(out_dir, "zoho_customers_import.csv")
    valid_customers = set()
    if os.path.exists(cust_file):
        with open(cust_file, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                valid_customers.add(r["Display Name"].strip())
    logger.info(f"Loaded {len(valid_customers)} valid customer contacts for customer payment filtering.")

    for v in vouchers:
        vch_no_node = v.find("VOUCHERNUMBER")
        vch_no_raw = (vch_no_node.text or "").strip() if vch_no_node is not None else ""
        if not vch_no_raw:
            continue

        party_node = v.find("PARTYLEDGERNAME")
        party_name = (party_node.text or "").strip() if party_node is not None else ""
        
        if party_name not in valid_customers:
            logger.info(f"Skipping non-customer receipt voucher REC-{vch_no_raw} (Party: '{party_name}')")
            continue

        payment_number = f"REC-{vch_no_raw}" if not vch_no_raw.startswith("REC") else vch_no_raw

        date_node = v.find("DATE")
        date_str = format_date(date_node.text) if date_node is not None else ""

        narration_node = v.find("NARRATION")
        notes = (narration_node.text or "").strip() if narration_node is not None else ""


        ledger_entries = v.findall(".//LEDGERENTRIES.LIST") + v.findall(".//ALLLEDGERENTRIES.LIST")
        
        deposit_to = None
        party_amt = 0.0
        bill_allocations = []

        for le in ledger_entries:
            lname = (le.find("LEDGERNAME").text or "").strip() if le.find("LEDGERNAME") is not None else ""
            lamt_str = le.find("AMOUNT").text if le.find("AMOUNT") is not None else "0"
            lamt = clean_float(lamt_str)

            is_party = le.find("ISPARTYLEDGER").text if le.find("ISPARTYLEDGER") is not None else "No"
            if is_party == "Yes" or lname == party_name:
                party_amt += abs(lamt)
                for ba in le.findall(".//BILLALLOCATIONS.LIST"):
                    bname = (ba.find("NAME").text or "").strip() if ba.find("NAME") is not None else ""
                    bamt_str = ba.find("AMOUNT").text if ba.find("AMOUNT") is not None else "0"
                    bamt = abs(clean_float(bamt_str))
                    btype = (ba.find("BILLTYPE").text or "").strip() if ba.find("BILLTYPE") is not None else ""
                    if bname:
                        bill_allocations.append({"bill_name": bname, "amount": bamt, "type": btype})
            else:
                if lname in bank_cash_accounts or any(kw in lname.lower() for kw in ("bank", "cash", "idfc", "axis", "kvb")):
                    deposit_to = lname

        if not deposit_to:
            deposit_to = "Petty Cash Ledger" if "Petty Cash Ledger" in bank_cash_accounts else (list(bank_cash_accounts)[0] if bank_cash_accounts else "Cash")

        payment_mode = "Cash" if "cash" in deposit_to.lower() else "Bank Transfer"


        if bill_allocations:
            # Group allocations: valid (matched) vs unmatched
            valid_allocs = []
            unmatched_total = 0.0
            for ba in bill_allocations:
                inv_no = format_invoice_number(ba["bill_name"])
                if inv_no in valid_invoice_numbers:
                    valid_allocs.append((inv_no, ba["amount"]))
                else:
                    unmatched_total += ba["amount"]
                    logger.info(f"  Receipt {vch_no_raw}: Bill '{ba['bill_name']}' -> '{inv_no}' not in current FY invoices. Will be treated as unapplied credit.")

            if valid_allocs:
                for inv_no, alloc_amt in valid_allocs:
                    payment_rows.append({
                        "Payment Number Prefix": "REC-",
                        "Payment Number Suffix": vch_no_raw,
                        "Customer Name": party_name,
                        "Place of Supply": "",
                        "GST Treatment": "",
                        "GST Identification Number (GSTIN)": "",
                        "Payment Type": "Invoice Payment",
                        "Description of Supply": "",
                        "Tax Name": "", "Tax Percentage": "", "Tax Type": "",
                        "Date": date_str,
                        "Mode": payment_mode,
                        "Exchange Rate": "1",
                        "Amount": f"{party_amt:.2f}",
                        "Description": notes,
                        "Bank Charges": "",
                        "Tax Account": "",
                        "Deposit To": deposit_to,
                        "Reference Number": notes[:50],
                        "Invoice Number": inv_no,
                        "Amount Applied to Invoice": f"{alloc_amt:.2f}",
                        "Invoice Amount": "",
                        "Withholding Tax Amount": "0",
                        "Branch Name": "Head Office"
                    })
            else:
                # No valid FY invoices matched — import as unapplied credit
                payment_rows.append({
                    "Payment Number Prefix": "REC-",
                    "Payment Number Suffix": vch_no_raw,
                    "Customer Name": party_name,
                    "Place of Supply": "",
                    "GST Treatment": "",
                    "GST Identification Number (GSTIN)": "",
                    "Payment Type": "Customer Advance",
                    "Description of Supply": "",
                    "Tax Name": "", "Tax Percentage": "", "Tax Type": "",
                    "Date": date_str,
                    "Mode": payment_mode,
                    "Exchange Rate": "1",
                    "Amount": f"{party_amt:.2f}",
                    "Description": notes,
                    "Bank Charges": "",
                    "Tax Account": "",
                    "Deposit To": deposit_to,
                    "Reference Number": notes[:50],
                    "Invoice Number": "",
                    "Amount Applied to Invoice": "",
                    "Invoice Amount": "",
                    "Withholding Tax Amount": "0",
                    "Branch Name": "Head Office"
                })
        else:
            payment_rows.append({
                "Payment Number Prefix": "REC-",
                "Payment Number Suffix": vch_no_raw,
                "Customer Name": party_name,
                "Place of Supply": "",
                "GST Treatment": "",
                "GST Identification Number (GSTIN)": "",
                "Payment Type": "Customer Advance",
                "Description of Supply": "",
                "Tax Name": "", "Tax Percentage": "", "Tax Type": "",
                "Date": date_str,
                "Mode": payment_mode,
                "Exchange Rate": "1",
                "Amount": f"{party_amt:.2f}",
                "Description": notes,
                "Bank Charges": "",
                "Tax Account": "",
                "Deposit To": deposit_to,
                "Reference Number": notes[:50],
                "Invoice Number": "",
                "Amount Applied to Invoice": "",
                "Invoice Amount": "",
                "Withholding Tax Amount": "0",
                "Branch Name": "Head Office"
            })


    _write_split_csv(base_csv, PAYMENT_HEADERS, payment_rows, "Customer Payments")
    logger.info(f"Total customer payment rows written: {len(payment_rows)}")
    return payment_rows

def query_payment_vouchers(tally_client, f_date: str, t_date: str):
    """
    Fetch all Payment vouchers from Tally for the given date range.
    f_date / t_date must be in D-M-YYYY format.
    """
    payload = f"""<ENVELOPE>
        <HEADER>
            <VERSION>1</VERSION>
            <TALLYREQUEST>Export Data</TALLYREQUEST>
            <TYPE>Collection</TYPE>
            <ID>PaymentVouchers</ID>
        </HEADER>
        <BODY>
            <DESC>
                <STATICVARIABLES>
                    <SVFROMDATE TYPE="Date">{f_date}</SVFROMDATE>
                    <SVTODATE TYPE="Date">{t_date}</SVTODATE>
                </STATICVARIABLES>
                <TDL>
                    <TDLMESSAGE>
                        <COLLECTION NAME="PaymentVouchers">
                            <TYPE>Voucher</TYPE>
                            <FILTER>IsPaymentFilter</FILTER>
                            <FETCH>DATE, VOUCHERNUMBER, PARTYLEDGERNAME, NARRATION</FETCH>
                            <FETCH>ALLLEDGERENTRIES.*</FETCH>
                            <FETCH>LEDGERENTRIES.*</FETCH>
                        </COLLECTION>
                        <SYSTEM TYPE="Formula" NAME="IsPaymentFilter">$$IsPayment:$VoucherTypeName</SYSTEM>
                    </TDLMESSAGE>
                </TDL>
            </DESC>
        </BODY>
    </ENVELOPE>"""
    return tally_client.send_request(payload)

def run_vendor_payment_mapping(tally_client, out_dir, f_date: str, t_date: str, vendor_advances=None):
    """
    Fetches ALL payment vouchers from Tally ONE FINANCIAL YEAR AT A TIME
    to avoid timeouts, combines them with any opening vendor advances, and generates the Zoho vendor payments CSV.
    """
    base_csv = os.path.join(out_dir, "zoho_vendor_payments_import.csv")
    batches = get_fy_batches(f_date, t_date)
    logger.info(f"Fetching vendor payments in {len(batches)} FY batch(es): {f_date} → {t_date}")

    all_xml_vouchers = []
    for batch_num, (b_from, b_to) in enumerate(batches, start=1):
        logger.info(f"  [Vendor Payments {batch_num}/{len(batches)}] {b_from} → {b_to} ...")
        xml_data = query_payment_vouchers(tally_client, b_from, b_to)
        xml_cleaned = sanitize_xml(xml_data)
        parser = etree.XMLParser(recover=True)
        root = etree.fromstring(xml_cleaned.encode("utf-8", errors="ignore"), parser=parser)
        batch_vouchers = root.findall(".//VOUCHER")
        logger.info(f"  [Vendor Payments {batch_num}/{len(batches)}] {len(batch_vouchers)} vouchers found.")
        all_xml_vouchers.extend(batch_vouchers)

    vouchers = all_xml_vouchers
    logger.info(f"Total vendor payment vouchers across all batches: {len(vouchers)}")

    vendor_payment_rows = []

    # Pre-populate opening vendor advances
    if vendor_advances:
        for idx, adv in enumerate(vendor_advances, start=1):
            vendor_payment_rows.append({
                "Payment Number": f"VADV-{idx}",
                "Date": adv.get("Date", ""),
                "Vendor Name": adv.get("Vendor Name", ""),
                "Mode": adv.get("Mode", "Cash"),
                "Paid Through": "Petty Cash Ledger",
                "Amount": adv.get("Amount", ""),
                "Exchange Rate": "1",
                "Reference Number": "Opening Vendor Advance",
                "Description": adv.get("Description", "Opening Vendor Advance"),
                "Bill Number": "",
                "Bill Date": "",
                "Amount Applied to Bill": "",
                "Bank Charges": "0",
                "Tax Account": "",
                "Branch Name": "Head Office"
            })
        logger.info(f"Pre-populated {len(vendor_advances)} opening vendor advances into vendor payments CSV.")

    coa_file = os.path.join(out_dir, "zoho_coa_import.csv")
    bank_cash_accounts = set()
    if os.path.exists(coa_file):
        with open(coa_file, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("Account Type") in ("Bank", "Cash", "Credit Card"):
                    bank_cash_accounts.add(r["Account Name"].strip())

    # Load valid vendors from zoho_vendors_import.csv
    vend_file = os.path.join(out_dir, "zoho_vendors_import.csv")
    valid_vendors = set()
    if os.path.exists(vend_file):
        with open(vend_file, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                valid_vendors.add(r["Display Name"].strip())
    logger.info(f"Loaded {len(valid_vendors)} valid vendor contacts for vendor payment filtering.")

    # Load valid bill numbers from zoho_bills_import.csv
    bill_file = os.path.join(out_dir, "zoho_bills_import.csv")
    valid_bill_numbers = set()
    if os.path.exists(bill_file):
        with open(bill_file, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                valid_bill_numbers.add(r["Bill Number"].strip())
    logger.info(f"Loaded {len(valid_bill_numbers)} valid bill numbers for vendor payment matching.")

    for v in vouchers:
        vch_no_node = v.find("VOUCHERNUMBER")
        vch_no_raw = (vch_no_node.text or "").strip() if vch_no_node is not None else ""
        if not vch_no_raw:
            continue

        party_node = v.find("PARTYLEDGERNAME")
        party_name = (party_node.text or "").strip() if party_node is not None else ""
        
        if party_name not in valid_vendors:
            logger.info(f"Skipping non-vendor payment voucher PAY-{vch_no_raw} (Party: '{party_name}')")
            continue

        payment_number = f"PAY-{vch_no_raw}" if not vch_no_raw.startswith("PAY") else vch_no_raw

        date_node = v.find("DATE")
        date_str = format_date(date_node.text) if date_node is not None else ""

        narration_node = v.find("NARRATION")
        notes = (narration_node.text or "").strip() if narration_node is not None else ""

        ledger_entries = v.findall(".//LEDGERENTRIES.LIST") + v.findall(".//ALLLEDGERENTRIES.LIST")
        
        paid_through = None
        party_amt = 0.0
        bill_allocations = []

        for le in ledger_entries:
            lname = (le.find("LEDGERNAME").text or "").strip() if le.find("LEDGERNAME") is not None else ""
            lamt_str = le.find("AMOUNT").text if le.find("AMOUNT") is not None else "0"
            lamt = clean_float(lamt_str)

            is_party = le.find("ISPARTYLEDGER").text if le.find("ISPARTYLEDGER") is not None else "No"
            if is_party == "Yes" or lname == party_name:
                party_amt += abs(lamt)
                for ba in le.findall(".//BILLALLOCATIONS.LIST"):
                    bname = (ba.find("NAME").text or "").strip() if ba.find("NAME") is not None else ""
                    bamt_str = ba.find("AMOUNT").text if ba.find("AMOUNT") is not None else "0"
                    bamt = abs(clean_float(bamt_str))
                    btype = (ba.find("BILLTYPE").text or "").strip() if ba.find("BILLTYPE") is not None else ""
                    if bname:
                        bill_allocations.append({"bill_name": bname, "amount": bamt, "type": btype})
            else:
                if lname in bank_cash_accounts or any(kw in lname.lower() for kw in ("bank", "cash", "idfc", "axis", "kvb")):
                    paid_through = lname

        if not paid_through:
            paid_through = "Petty Cash Ledger" if "Petty Cash Ledger" in bank_cash_accounts else (list(bank_cash_accounts)[0] if bank_cash_accounts else "Cash")

        payment_mode = "Cash" if "cash" in paid_through.lower() else "Bank Transfer"

        if bill_allocations:
            valid_allocs = []
            for ba in bill_allocations:
                bill_no = format_invoice_number(ba["bill_name"])
                if bill_no in valid_bill_numbers:
                    valid_allocs.append((bill_no, ba["amount"]))

            if valid_allocs:
                for bill_no, alloc_amt in valid_allocs:
                    vendor_payment_rows.append({
                        "Payment Number": payment_number,
                        "Date": date_str,
                        "Vendor Name": party_name,
                        "Mode": payment_mode,
                        "Paid Through": paid_through,
                        "Amount": f"{party_amt:.2f}",
                        "Exchange Rate": "1",
                        "Reference Number": notes[:50],
                        "Description": notes,
                        "Bill Number": bill_no,
                        "Bill Date": "",
                        "Amount Applied to Bill": f"{alloc_amt:.2f}",
                        "Bank Charges": "0",
                        "Tax Account": "",
                        "Branch Name": "Head Office"
                    })
            else:
                vendor_payment_rows.append({
                    "Payment Number": payment_number,
                    "Date": date_str,
                    "Vendor Name": party_name,
                    "Mode": payment_mode,
                    "Paid Through": paid_through,
                    "Amount": f"{party_amt:.2f}",
                    "Exchange Rate": "1",
                    "Reference Number": notes[:50],
                    "Description": notes,
                    "Bill Number": "",
                    "Bill Date": "",
                    "Amount Applied to Bill": "",
                    "Bank Charges": "0",
                    "Tax Account": "",
                    "Branch Name": "Head Office"
                })
        else:
            vendor_payment_rows.append({
                "Payment Number": payment_number,
                "Date": date_str,
                "Vendor Name": party_name,
                "Mode": payment_mode,
                "Paid Through": paid_through,
                "Amount": f"{party_amt:.2f}",
                "Exchange Rate": "1",
                "Reference Number": notes[:50],
                "Description": notes,
                "Bill Number": "",
                "Bill Date": "",
                "Amount Applied to Bill": "",
                "Bank Charges": "0",
                "Tax Account": "",
                "Branch Name": "Head Office"
            })



    from config.constants import VENDOR_PAYMENT_HEADERS
    _write_split_csv(base_csv, VENDOR_PAYMENT_HEADERS, vendor_payment_rows, "Vendor Payments")
    logger.info(f"Total vendor payment rows written: {len(vendor_payment_rows)}")
    return vendor_payment_rows
