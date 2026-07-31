# mappers/contact_mapper.py

import os
import csv
import json
import logging
from config.constants import (
    CURRENCY, DEBIT_NORMAL, CREDIT_NORMAL, GST_STATE_MAP,
    CUST_HEADERS, VEND_HEADERS, OB_HEADERS, CUST_ADV_HEADERS, VEND_ADV_HEADERS, CREDIT_NOTE_HEADERS, VENDOR_CREDIT_HEADERS,
    TALLY_RESERVED_TO_ZOHO, NO_SUBACCOUNT_TYPES, ZOHO_SYSTEM_ACCOUNTS
)
from utils.gst_helpers import get_state_code, infer_gst_treatment
from utils.math_helpers import clean_float
from mappers.coa_mapper import resolve_custom_path_and_root, classify_group_by_nature

logger = logging.getLogger(__name__)

def run_contact_mapping(ledgers, gmap, parent_accounts, migration_date, out_dir):
    """Maps ledger contacts and opening balances, exporting files for customers, vendors, and advances."""
    collision_parent_names = {p.lower().strip() for p in parent_accounts.keys()}

    customer_list = []
    vendor_list = []
    bank_list = []
    opening_balances_to_import = []
    customer_advances_to_import = []
    vendor_advances_to_import = []
    credit_notes_to_import = []
    vendor_credits_to_import = []
    unmapped = []

    SKIP_NAMES = {"profit & loss a/c", "profit and loss a/c"}

    # P&L account types must NEVER appear in opening balances — only Balance Sheet accounts should
    SKIP_OB_TYPES = {"Income", "Other Income", "Cost of Goods Sold", "Expense", "Other Expense"}

    for l in ledgers:
        name = l["name"]
        t_parent = l["tally_parent"]
        ob = l["opening_balance"]
        gstin = l["gstin"]
        pan = l["pan"]
        pincode = l["pincode"]
        address = l["address"]
        credit_period = l["credit_period"]
        tally_state = l["tally_state"]

        # Auto-resolve name collisions with parent groups by appending ' Ledger'
        if name.lower().strip() in collision_parent_names:
            old_name = name
            name = f"{old_name} Ledger"
            logger.info(f"Auto-renamed conflicting ledger name '{old_name}' -> '{name}' to avoid collision.")

        custom_path, root_reserved = resolve_custom_path_and_root(t_parent, gmap)

        zoho_type = None
        if root_reserved:
            zoho_type = TALLY_RESERVED_TO_ZOHO.get(root_reserved)

        if not zoho_type:
            if t_parent in TALLY_RESERVED_TO_ZOHO:
                zoho_type = TALLY_RESERVED_TO_ZOHO.get(t_parent)
                custom_path = []
            else:
                top_group = custom_path[0] if len(custom_path) > 0 else t_parent
                zoho_type = classify_group_by_nature(top_group, gmap)

        if not zoho_type:
            unmapped.append(f"{name}  [tally_parent={t_parent}, reason: no reserved root found]")
            continue

        # Determine Debit/Credit
        abs_ob = abs(ob)
        if abs_ob == 0.0:
            debit_or_credit = ""
            ob_display = ""
        else:
            is_debit_normal = zoho_type in DEBIT_NORMAL
            if is_debit_normal:
                debit_or_credit = "Debit" if ob <= 0 else "Credit"
            else:
                debit_or_credit = "Credit" if ob >= 0 else "Debit"
            ob_display = f"{abs_ob:.2f}"

        # Collect detailed records
        if zoho_type == "Accounts Receivable":
            customer_list.append({
                "name": name,
                "opening_balance": ob_display,
                "debit_or_credit": debit_or_credit,
                "gstin": gstin,
                "pan": pan,
                "pincode": pincode,
                "address": address,
                "credit_period": credit_period,
                "tally_state": tally_state,
            })
        elif zoho_type == "Accounts Payable":
            vendor_list.append({
                "name": name,
                "opening_balance": ob_display,
                "debit_or_credit": debit_or_credit,
                "gstin": gstin,
                "pan": pan,
                "pincode": pincode,
                "address": address,
                "credit_period": credit_period,
                "tally_state": tally_state,
            })
        elif zoho_type in ("Bank", "Credit Card"):
            bank_list.append({
                "name": name,
                "zoho_type": zoho_type,
                "opening_balance": ob_display,
                "debit_or_credit": debit_or_credit
            })

        # Save opening balance & advances
        if ob_display and float(ob_display) > 0.0:
            if zoho_type == "Accounts Receivable":
                if debit_or_credit == "Debit":
                    # AR Debit balance = money owed by customers.
                    # Since we are importing ALL historical invoices + payments, Zoho will compute
                    # the AR balance automatically from those transactions. No separate OB entry needed.
                    pass
                else:
                    # AR Credit balance = customer paid more than invoiced (advance/overpayment).
                    # Import as Customer Advance so it is visible as unapplied credit in Zoho.
                    gstin_stripped = "".join(gstin.split()).upper()
                    state_code = gstin_stripped[:2] if len(gstin_stripped) >= 15 and gstin_stripped[:2].isdigit() and gstin_stripped[:2] in GST_STATE_MAP else None
                    gstin_state = GST_STATE_MAP.get(state_code, "")
                    state_name = tally_state or gstin_state
                    place_of_supply = get_state_code(state_name) if state_name else "TN"
                    gst_treatment = infer_gst_treatment(gstin_stripped)

                    payment_suffix = len(customer_advances_to_import) + 1
                    customer_advances_to_import.append({
                        "Payment Number Prefix": "PY-",
                        "Payment Number Suffix": str(payment_suffix),
                        "Date": migration_date,
                        "Payment Status": "",
                        "Description of Supply": "GOODS",
                        "Payment Type": "Customer Advance",
                        "Mode": "Cash",
                        "Description": "Opening Customer Advance / Credit Balance from Tally",
                        "Exchange Rate": "1",
                        "Amount": ob_display,
                        "Deposit To": "Opening Balance Adjustments",
                        "Bank Charges": "",
                        "Reference Number": "",
                        "Attachment IDs": "",
                        "Template Name": "",
                        "Customer Name": name,
                        "Place of Supply": place_of_supply,
                        "GST Treatment": gst_treatment,
                        "GST Identification Number (GSTIN)": gstin_stripped,
                        "Tax Name": "", "Tax Percentage": "", "Tax Type": "", "Tax Account": "",
                        "Invoice Number": "", "Invoice Date": "", "Amount Applied to Invoice": "",
                    })
            elif zoho_type == "Accounts Payable":
                if debit_or_credit == "Credit":
                    # AP Credit balance = money owed to vendors.
                    # Since we are importing ALL historical bills + payments, Zoho will compute
                    # the AP balance automatically from those transactions. No separate OB entry needed.
                    pass
                else:
                    # AP Debit balance = we overpaid a vendor (advance/prepayment).
                    # Import as Vendor Advance so it is visible as unapplied payment in Zoho.
                    gstin_stripped = "".join(gstin.split()).upper()
                    state_code = gstin_stripped[:2] if len(gstin_stripped) >= 15 and gstin_stripped[:2].isdigit() and gstin_stripped[:2] in GST_STATE_MAP else None
                    gstin_state = GST_STATE_MAP.get(state_code, "")
                    state_name = tally_state or gstin_state
                    place_of_supply = get_state_code(state_name) if state_name else "TN"
                    gst_treatment = infer_gst_treatment(gstin_stripped)

                    payment_num = len(vendor_advances_to_import) + 1
                    vendor_advances_to_import.append({
                        "Payment Number": str(payment_num),
                        "Date": migration_date,
                        "Vendor Name": name,
                        "Mode": "Cash",
                        "Description": "Opening Vendor Advance / Debit Balance from Tally",
                        "Exchange Rate": "1",
                        "Amount": ob_display,
                        "Paid Through": "Opening Balance Adjustments",
                        "Tax Account": "", "Reference Number": "", "Bill Number": "",
                        "Bill Amount": "", "Reverse Charge Tax Rate": "", "Reverse Charge Tax Type": "",
                        "Reverse Charge Tax Name": "", "Payment Type": "Vendor Advance",
                        "GST Treatment": gst_treatment,
                        "GST Identification Number (GSTIN)": gstin_stripped,
                        "Destination of Supply": place_of_supply,
                        "Description of Supply": "GOODS",
                        "TDS Name": "", "TDS Percentage": "", "TDS Section Code": "", "TDS Amount": "",
                        "Bill Date": ""
                    })
            else:
                if zoho_type not in SKIP_OB_TYPES:
                    opening_balances_to_import.append({
                        "Migration Date": migration_date,
                        "Account Name": name,
                        "Debit or Credit": debit_or_credit,
                        "Currency Code": CURRENCY,
                        "Amount": ob_display,
                        "Exchange Rate": "1",
                        "Contact Name": ""
                    })
                else:
                    logger.debug(f"Skipping P&L account from opening balances: {name} (type={zoho_type})")

    # Write Opening Balances CSV
    ob_path = os.path.join(out_dir, "zoho_opening_balances_import.csv")
    with open(ob_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OB_HEADERS)
        writer.writeheader()
        writer.writerows(opening_balances_to_import)
    logger.info(f"Opening Balances CSV generated at {ob_path}")

    # Write Customers CSV
    cust_path = os.path.join(out_dir, "zoho_customers_import.csv")
    _write_contacts_csv(cust_path, customer_list, CUST_HEADERS, is_vendor=False)

    # Write Vendors CSV
    vend_path = os.path.join(out_dir, "zoho_vendors_import.csv")
    _write_contacts_csv(vend_path, vendor_list, VEND_HEADERS, is_vendor=True)

    # Write Customer Advances CSV
    cust_adv_path = os.path.join(out_dir, "zoho_customer_advances_import.csv")
    with open(cust_adv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CUST_ADV_HEADERS)
        writer.writeheader()
        writer.writerows(customer_advances_to_import)
    logger.info(f"Customer Advances CSV generated at {cust_adv_path}")

    # Write Vendor Advances CSV
    vend_adv_path = os.path.join(out_dir, "zoho_vendor_advances_import.csv")
    with open(vend_adv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=VEND_ADV_HEADERS)
        writer.writeheader()
        writer.writerows(vendor_advances_to_import)
    logger.info(f"Vendor Advances CSV generated at {vend_adv_path}")

    # Write Credit Notes CSV (if any)
    if credit_notes_to_import:
        cn_path = os.path.join(out_dir, "zoho_credit_notes_import.csv")
        with open(cn_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CREDIT_NOTE_HEADERS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(credit_notes_to_import)
        logger.info(f"Credit Notes CSV generated at {cn_path}")

    # Write Vendor Credits CSV (if any)
    if vendor_credits_to_import:
        vc_path = os.path.join(out_dir, "zoho_vendor_credits_import.csv")
        with open(vc_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=VENDOR_CREDIT_HEADERS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(vendor_credits_to_import)
        logger.info(f"Vendor Credits CSV generated at {vc_path}")

    # Write Bank OB Reference txt
    bank_path = os.path.join(out_dir, "zoho_bank_opening_balances.txt")
    with open(bank_path, "w", encoding="utf-8") as f:
        f.write("ZOHO BANK & CREDIT CARD OPENING BALANCES REFERENCE DUMP\n")
        f.write("========================================================\n\n")
        if bank_list:
            for b in bank_list:
                f.write(f"Account: {b['name']} ({b['zoho_type']}) | OB: {b['opening_balance']} | {b['debit_or_credit']}\n")
        else:
            f.write("No Bank or Credit Card opening balances found in Tally.\n")
    logger.info(f"Bank reference txt generated at {bank_path}")

    # Write unmapped log
    if unmapped:
        unmapped_path = os.path.join(out_dir, "unmapped_ledgers.txt")
        with open(unmapped_path, "w", encoding="utf-8") as f:
            f.write("\n".join(unmapped))
        logger.warning(f"Written {len(unmapped)} unmapped ledgers to {unmapped_path}")

    return customer_list, vendor_list, bank_list, customer_advances_to_import, vendor_advances_to_import

def _write_contacts_csv(filepath, contacts, headers, is_vendor=False):
    """Writes contacts to CSV in Zoho Books 63-column format."""
    try:
        _write_f(filepath, contacts, headers, is_vendor)
    except PermissionError:
        base, ext = os.path.splitext(filepath)
        fallback = base + "_unlocked" + ext
        logger.warning(f"Permission denied on contact file. Writing to: {fallback}")
        try:
            _write_f(fallback, contacts, headers, is_vendor)
        except Exception as e:
            logger.error(f"Failed to write fallback contacts CSV: {e}")

def _write_f(filepath, contacts, headers, is_vendor):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for c in contacts:
            gstin = c["gstin"]
            gstin_stripped = "".join(gstin.split()).upper()
            treatment = infer_gst_treatment(gstin_stripped)
            tally_state = c["tally_state"]
            
            # Place of supply / Contact state
            state_code = gstin_stripped[:2] if len(gstin_stripped) >= 15 and gstin_stripped[:2].isdigit() and gstin_stripped[:2] in GST_STATE_MAP else None
            state_name = tally_state or GST_STATE_MAP.get(state_code, "")
            place_of_supply = get_state_code(state_name) if state_name else "TN"

            # Parse payment terms in days
            terms_days = 0
            p_terms = "Due on Receipt"
            c_period = c["credit_period"]
            if c_period:
                match = re.search(r"(\d+)", c_period)
                if match:
                    terms_days = int(match.group(1))
                    p_terms = f"Net {terms_days}"

            # Standard Zoho contact schema row
            row = {
                "Display Name": c["name"],
                "Customer Number" if not is_vendor else "Vendor Number": "",
                "Place of Contact" if not is_vendor else "Source Of Supply": place_of_supply,
                "Currency Code": CURRENCY,
                "Company Name": c["name"],
                "Salutation": "", "First Name": "", "Last Name": "", "EmailID": "",
                "Phone": "", "MobilePhone": "", "Facebook": "", "Twitter": "", "Department": "", "Designation": "",
                "Payment Terms": p_terms, "Payment Terms Label": "", "Notes": "", "Website": "", "Exemption Reason": "",
                "GST Treatment": treatment,
                "GST Identification Number (GSTIN)": gstin_stripped,
                "PAN Number": c["pan"],
                "Billing Address": c["address"],
                "Billing City": "",
                "Billing State": state_name or "Tamil Nadu",
                "Billing Country": "India",
                "Billing Pin Code": c["pincode"],
                "Billing Phone": "",
                "Shipping Address": c["address"],
                "Shipping City": "",
                "Shipping State": state_name or "Tamil Nadu",
                "Shipping Country": "India",
                "Shipping Pin Code": c["pincode"],
                "Shipping Phone": "",
                "Contact Persons Details": "", "Attachment IDs": "",
                "Outstanding Balance": "", "Debit or Credit of Outstanding Balance": "",
                "Payment Terms In Days": str(terms_days) if terms_days > 0 else "",
                "Branch Name": "Head Office"
            }
            writer.writerow(row)
    logger.info(f"Contacts CSV generated at {filepath}")
import re
