# mappers/payment_mapper.py

import os
import csv
import logging
import re
from lxml import etree

from config.constants import PAYMENT_HEADERS
from utils.date_helpers import format_date, get_fy_batches, get_fy_short
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

def resolve_default_bank_cash_account(bank_cash_accounts: set) -> str:
    if "Cash" in bank_cash_accounts:
        return "Cash"
    if "Petty Cash" in bank_cash_accounts:
        return "Petty Cash"
    for acct in sorted(bank_cash_accounts):
        if "cash" in acct.lower():
            return acct
    for acct in sorted(bank_cash_accounts):
        if "petty" in acct.lower():
            return acct
    for acct in sorted(bank_cash_accounts):
        if "refund" not in acct.lower():
            return acct
    return list(bank_cash_accounts)[0] if bank_cash_accounts else "Cash"

EXCLUDED_BANK_CASH_KEYWORDS = {
    "charge", "charges", "fee", "fees", "interest", "commission", "discount",
    "expense", "expenses", "tax", "tds", "gst", "round", "off", "loan", "card"
}

def is_valid_bank_cash_ledger(lname: str, bank_cash_accounts: set) -> bool:
    if not lname:
        return False
    if lname in bank_cash_accounts:
        return True
    lname_lower = lname.lower()
    if any(ex in lname_lower for ex in EXCLUDED_BANK_CASH_KEYWORDS):
        return False
    if any(kw in lname_lower for kw in ("bank", "cash", "idfc", "axis", "kvb", "hdfc", "icici", "sbi", "kotak")):
        return True
    return False

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

    # Load Bank and Cash account names from COA
    coa_file = os.path.join(out_dir, "zoho_coa_import.csv")
    unlocked_coa = os.path.join(out_dir, "zoho_coa_import_unlocked.csv")
    if os.path.exists(unlocked_coa):
        if not os.path.exists(coa_file) or os.path.getmtime(unlocked_coa) >= os.path.getmtime(coa_file):
            coa_file = unlocked_coa
    bank_cash_accounts = set()
    if os.path.exists(coa_file):
        with open(coa_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("Account Type") in ("Bank", "Cash", "Credit Card"):
                    aname = r.get("Account Name", "").strip()
                    if aname:
                        bank_cash_accounts.add(aname)

    default_deposit_to = resolve_default_bank_cash_account(bank_cash_accounts)

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
                "Deposit To": default_deposit_to,
                "Reference Number": "Opening Customer Advance",
                "Invoice Number": "",
                "Amount Applied to Invoice": "",
                "Invoice Amount": "",
                "Withholding Tax Amount": "0",
                "Branch Name": "Head Office"
            })
        logger.info(f"Pre-populated {len(customer_advances)} opening customer advances into payments CSV.")

    # Load valid invoice numbers, customer ownership, and invoice balances from zoho_invoices_import.csv
    inv_file = os.path.join(out_dir, "zoho_invoices_import.csv")
    unlocked_inv = os.path.join(out_dir, "zoho_invoices_import_unlocked.csv")
    if os.path.exists(unlocked_inv):
        if not os.path.exists(inv_file) or os.path.getmtime(unlocked_inv) >= os.path.getmtime(inv_file):
            inv_file = unlocked_inv
    invoice_customer_map = {}
    invoice_balance_map = {}
    if os.path.exists(inv_file):
        with open(inv_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                inum = r.get("Invoice Number", "").strip()
                cname = r.get("Customer Name", "").strip()
                if inum and cname:
                    invoice_customer_map[inum] = cname
                    qty = clean_float(r.get("Quantity", "0"))
                    price = clean_float(r.get("Item Price", "0"))
                    tax_pct = clean_float(r.get("Item Tax %", "0"))
                    line_total = qty * price * (1.0 + tax_pct / 100.0)
                    invoice_balance_map[inum] = invoice_balance_map.get(inum, 0.0) + line_total
    logger.info(f"Loaded {len(invoice_customer_map)} valid invoices with balance tracking for payment matching.")

    # Load valid customers from zoho_customers_import.csv
    cust_file = os.path.join(out_dir, "zoho_customers_import.csv")
    unlocked_cust = os.path.join(out_dir, "zoho_customers_import_unlocked.csv")
    if os.path.exists(unlocked_cust):
        if not os.path.exists(cust_file) or os.path.getmtime(unlocked_cust) >= os.path.getmtime(cust_file):
            cust_file = unlocked_cust
    valid_customers = set()
    if os.path.exists(cust_file):
        with open(cust_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                dname = r.get("Display Name", "").strip()
                if dname:
                    valid_customers.add(dname)
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

        date_node = v.find("DATE")
        date_str = format_date(date_node.text) if date_node is not None else ""
        fy_tag = get_fy_short(date_str)
        vch_clean = vch_no_raw.replace("REC-", "").replace("REC", "")
        digits_only = re.sub(r'\D', '', vch_clean)
        payment_prefix = f"REC-{fy_tag}-" if fy_tag else "REC-"
        payment_suffix = digits_only if digits_only else "1"

        narration_node = v.find("NARRATION")
        notes = (narration_node.text or "").strip() if narration_node is not None else ""

        ledger_entries = v.findall(".//LEDGERENTRIES.LIST") + v.findall(".//ALLLEDGERENTRIES.LIST")
        
        deposit_to = None
        deposit_to_priority = 0
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
                if lname in bank_cash_accounts:
                    deposit_to = lname
                    deposit_to_priority = 2
                elif deposit_to_priority < 2 and is_valid_bank_cash_ledger(lname, bank_cash_accounts):
                    deposit_to = lname
                    deposit_to_priority = 1

        if not deposit_to or deposit_to not in bank_cash_accounts:
            matched_acct = None
            if deposit_to:
                for bca in bank_cash_accounts:
                    if bca.lower() == deposit_to.lower():
                        matched_acct = bca
                        break
            deposit_to = matched_acct if matched_acct else default_deposit_to

        payment_mode = "Cash" if "cash" in deposit_to.lower() else "Bank Transfer"

        if bill_allocations:
            valid_allocs = []
            for ba in bill_allocations:
                inv_no = format_invoice_number(ba["bill_name"])
                inv_owner = invoice_customer_map.get(inv_no)
                if inv_owner and inv_owner.strip().lower() == party_name.strip().lower():
                    rem_bal = invoice_balance_map.get(inv_no, 0.0)
                    if rem_bal > 0.01:
                        alloc_amt = min(ba["amount"], rem_bal)
                        invoice_balance_map[inv_no] = max(0.0, rem_bal - alloc_amt)
                        valid_allocs.append((inv_no, alloc_amt))
                    else:
                        logger.info(f"  Receipt {vch_no_raw}: Invoice '{inv_no}' balance due is 0. Allocation skipped.")
                else:
                    logger.info(f"  Receipt {vch_no_raw}: Invoice '{ba['bill_name']}' -> '{inv_no}' owner '{inv_owner}' does not match receipt party '{party_name}'. Allocation skipped.")

            if valid_allocs:
                alloc_sum = sum(amt for _, amt in valid_allocs)
                p_amt = max(party_amt, alloc_sum)
                for inv_no, alloc_amt in valid_allocs:
                    payment_rows.append({
                        "Payment Number Prefix": payment_prefix,
                        "Payment Number Suffix": payment_suffix,
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
                        "Amount": f"{p_amt:.2f}",
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
                # No valid FY invoices matched or remaining balance — import as unapplied credit / advance
                payment_rows.append({
                    "Payment Number Prefix": payment_prefix,
                    "Payment Number Suffix": payment_suffix,
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
                "Payment Number Prefix": payment_prefix,
                "Payment Number Suffix": payment_suffix,
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

    coa_file = os.path.join(out_dir, "zoho_coa_import.csv")
    unlocked_coa = os.path.join(out_dir, "zoho_coa_import_unlocked.csv")
    if os.path.exists(unlocked_coa):
        if not os.path.exists(coa_file) or os.path.getmtime(unlocked_coa) >= os.path.getmtime(coa_file):
            coa_file = unlocked_coa
    bank_cash_accounts = set()
    if os.path.exists(coa_file):
        with open(coa_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("Account Type") in ("Bank", "Cash", "Credit Card"):
                    aname = r.get("Account Name", "").strip()
                    if aname:
                        bank_cash_accounts.add(aname)

    default_paid_through = resolve_default_bank_cash_account(bank_cash_accounts)

    # Pre-populate opening vendor advances
    if vendor_advances:
        for idx, adv in enumerate(vendor_advances, start=1):
            vendor_payment_rows.append({
                "Payment Number": f"VADV-{idx}",
                "Date": adv.get("Date", ""),
                "Vendor Name": adv.get("Vendor Name", ""),
                "Mode": adv.get("Mode", "Cash"),
                "Paid Through": default_paid_through,
                "Amount": adv.get("Amount", ""),
                "Exchange Rate": "1",
                "Reference Number": "Opening Vendor Advance",
                "Description": adv.get("Description", "Opening Vendor Advance"),
                "Bill Number": "",
                "Bill Date": "",
                "Bill Amount": "",
                "Bank Charges": "0",
                "Tax Account": "",
                "Branch Name": "Head Office"
            })
        logger.info(f"Pre-populated {len(vendor_advances)} opening vendor advances into vendor payments CSV.")

    # Load valid vendors from zoho_vendors_import.csv
    vend_file = os.path.join(out_dir, "zoho_vendors_import.csv")
    unlocked_vend = os.path.join(out_dir, "zoho_vendors_import_unlocked.csv")
    if os.path.exists(unlocked_vend):
        if not os.path.exists(vend_file) or os.path.getmtime(unlocked_vend) >= os.path.getmtime(vend_file):
            vend_file = unlocked_vend
    valid_vendors = set()
    if os.path.exists(vend_file):
        with open(vend_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                vname = r.get("Display Name", "").strip()
                if vname:
                    valid_vendors.add(vname)
    logger.info(f"Loaded {len(valid_vendors)} valid vendor contacts for vendor payment filtering.")

    # Load valid bill numbers, vendor ownership, and bill balances from zoho_bills_import.csv
    bill_file = os.path.join(out_dir, "zoho_bills_import.csv")
    unlocked_bill = os.path.join(out_dir, "zoho_bills_import_unlocked.csv")
    if os.path.exists(unlocked_bill):
        if not os.path.exists(bill_file) or os.path.getmtime(unlocked_bill) >= os.path.getmtime(bill_file):
            bill_file = unlocked_bill
    bill_vendor_map = {}
    bill_balance_map = {}
    if os.path.exists(bill_file):
        with open(bill_file, "r", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                bnum = r.get("Bill Number", "").strip()
                vname = r.get("Vendor Name", "").strip()
                if bnum and vname:
                    bill_vendor_map[bnum] = vname
                    qty = clean_float(r.get("Quantity", "0"))
                    price = clean_float(r.get("Rate", r.get("Item Price", "0")))
                    tax_pct = clean_float(r.get("Tax Percentage", r.get("Item Tax %", "0")))
                    line_total = qty * price * (1.0 + tax_pct / 100.0)
                    bill_balance_map[bnum] = bill_balance_map.get(bnum, 0.0) + line_total
    logger.info(f"Loaded {len(bill_vendor_map)} valid bills with balance tracking for vendor payment matching.")

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

        date_node = v.find("DATE")
        date_str = format_date(date_node.text) if date_node is not None else ""
        fy_tag = get_fy_short(date_str)
        vch_clean = vch_no_raw.replace("PAY-", "").replace("PAY", "")
        payment_number = f"PAY-{fy_tag}-{vch_clean}" if fy_tag else f"PAY-{vch_clean}"

        narration_node = v.find("NARRATION")
        notes = (narration_node.text or "").strip() if narration_node is not None else ""

        ledger_entries = v.findall(".//LEDGERENTRIES.LIST") + v.findall(".//ALLLEDGERENTRIES.LIST")
        
        paid_through = None
        paid_through_priority = 0
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
                if lname in bank_cash_accounts:
                    paid_through = lname
                    paid_through_priority = 2
                elif paid_through_priority < 2 and is_valid_bank_cash_ledger(lname, bank_cash_accounts):
                    paid_through = lname
                    paid_through_priority = 1

        if not paid_through or paid_through not in bank_cash_accounts:
            matched_acct = None
            if paid_through:
                for bca in bank_cash_accounts:
                    if bca.lower() == paid_through.lower():
                        matched_acct = bca
                        break
            paid_through = matched_acct if matched_acct else default_paid_through

        payment_mode = "Cash" if "cash" in paid_through.lower() else "Bank Transfer"

        if bill_allocations:
            valid_allocs = []
            for ba in bill_allocations:
                bill_no = format_invoice_number(ba["bill_name"])
                bill_owner = bill_vendor_map.get(bill_no)
                if bill_owner and bill_owner.strip().lower() == party_name.strip().lower():
                    rem_bal = bill_balance_map.get(bill_no, 0.0)
                    if rem_bal > 0.01:
                        alloc_amt = min(ba["amount"], rem_bal)
                        bill_balance_map[bill_no] = max(0.0, rem_bal - alloc_amt)
                        valid_allocs.append((bill_no, alloc_amt))
                    else:
                        logger.info(f"  Payment {vch_no_raw}: Bill '{bill_no}' balance due is 0. Allocation skipped.")
                else:
                    logger.info(f"  Payment {vch_no_raw}: Bill '{ba['bill_name']}' -> '{bill_no}' owner '{bill_owner}' does not match vendor '{party_name}'. Allocation skipped.")

            if valid_allocs:
                alloc_sum = sum(amt for _, amt in valid_allocs)
                p_amt = max(party_amt, alloc_sum)
                for bill_no, alloc_amt in valid_allocs:
                    vendor_payment_rows.append({
                        "Payment Number": payment_number,
                        "Date": date_str,
                        "Vendor Name": party_name,
                        "Mode": payment_mode,
                        "Paid Through": paid_through,
                        "Amount": f"{p_amt:.2f}",
                        "Exchange Rate": "1",
                        "Reference Number": notes[:50],
                        "Description": notes,
                        "Bill Number": bill_no,
                        "Bill Date": "",
                        "Bill Amount": f"{alloc_amt:.2f}",
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
                    "Bill Amount": "",
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
                "Bill Amount": "",
                "Bank Charges": "0",
                "Tax Account": "",
                "Branch Name": "Head Office"
            })




    from config.constants import VENDOR_PAYMENT_HEADERS
    _write_split_csv(base_csv, VENDOR_PAYMENT_HEADERS, vendor_payment_rows, "Vendor Payments")
    logger.info(f"Total vendor payment rows written: {len(vendor_payment_rows)}")
    return vendor_payment_rows
