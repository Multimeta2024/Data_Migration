# mappers/coa_mapper.py

import os
import json
import csv
import logging
from config.settings import OUTPUT_DIR
from config.constants import (
    CURRENCY, TALLY_RESERVED_TO_ZOHO, NO_SUBACCOUNT_TYPES,
    ZOHO_SYSTEM_ACCOUNTS, COA_HEADERS, DEBIT_NORMAL
)
from utils.math_helpers import clean_float

logger = logging.getLogger(__name__)

def build_group_map(groups: list) -> dict:
    """
    Returns dict keyed by group name (lowercase) with value:
      { name, parent, reserved_name }
    """
    gmap = {}
    for g in groups:
        key = g["name"].strip().lower()
        gmap[key] = g
    
    # Inject missing groups that exist in the company's Tally
    _EXTRA_GROUPS = [
        {"name": "Petty Cash",           "parent": "Cash-in-hand",          "reserved_name": ""},
        {"name": "Petty Cash CO",        "parent": "Cash-in-hand",          "reserved_name": ""},
        {"name": "R&D Agri Value Chain", "parent": "Research & Development","reserved_name": ""},
        {"name": "R&D Coonoor Ployhouse Exp","parent": "R&D Agri Value Chain","reserved_name": ""},
        {"name": "R&D Pilot Projects",   "parent": "Research & Development","reserved_name": ""},
        {"name": "Software",             "parent": "R&D Agri Value Chain",  "reserved_name": ""},
        {"name": "Investment in Shares-311100 Equity Shares@Rs.43",
                                         "parent": "Long-Term Investments",  "reserved_name": ""},
    ]
    for eg in _EXTRA_GROUPS:
        key = eg["name"].lower()
        if key not in gmap:
            eg.setdefault("is_revenue", False)
            eg.setdefault("is_deemed_positive", True)
            gmap[key] = eg
    return gmap

def classify_group_by_nature(group_name: str, gmap: dict) -> str:
    """Classify a custom group using Tally nature flags (ISREVENUE / ISDEEMEDPOSITIVE)."""
    g_info = gmap.get(group_name.lower())
    if g_info:
        is_revenue = g_info.get("is_revenue", False)
        is_deemed = g_info.get("is_deemed_positive", True)
        if is_revenue:
            return "Expense" if is_deemed else "Income"
        else:
            return "Other Asset" if is_deemed else "Other Liability"
    return None

def resolve_root_reserved(group_name: str, gmap: dict, visited: set = None) -> str:
    """
    Walk up the group tree from group_name until we find a group whose
    name or reserved_name is present in TALLY_RESERVED_TO_ZOHO.
    """
    if visited is None:
        visited = set()
    key = group_name.strip().lower()
    if key in visited:
        return ""   # cycle guard
    visited.add(key)

    if group_name.strip() in TALLY_RESERVED_TO_ZOHO:
        return group_name.strip()

    g = gmap.get(key)
    if g is None:
        return ""

    rn = g.get("reserved_name", "").strip()
    if rn and rn in TALLY_RESERVED_TO_ZOHO:
        return rn

    if g["name"].strip() in TALLY_RESERVED_TO_ZOHO:
        return g["name"].strip()

    parent = g.get("parent", "").strip()
    if not parent or parent.lower() == "primary":
        return ""
    return resolve_root_reserved(parent, gmap, visited)

def resolve_custom_path_and_root(group_name: str, gmap: dict) -> tuple:
    """
    Given a ledger's direct Tally parent (group name):
      - Recursively walk up parent tree
      - Build list of custom groups
      - Identify root reserved group
    """
    visited = set()
    chain = []
    current = group_name.strip()
    root_reserved = ""
    while current and current.lower() != "primary":
        curr_key = current.lower()
        if curr_key in visited:
            break
        visited.add(curr_key)

        if current in TALLY_RESERVED_TO_ZOHO:
            root_reserved = current
            break

        g = gmap.get(curr_key)
        if g:
            rn = g.get("reserved_name", "").strip()
            if rn and rn in TALLY_RESERVED_TO_ZOHO:
                root_reserved = rn
                break
            if g["name"].strip() in TALLY_RESERVED_TO_ZOHO:
                root_reserved = g["name"].strip()
                break
            
            chain.append(g["name"].strip())
            current = g.get("parent", "").strip()
        else:
            if current in TALLY_RESERVED_TO_ZOHO:
                root_reserved = current
            break

    chain.reverse()
    return chain, root_reserved

def parse_ledgers(ledgers_path: str) -> list:
    """Parses raw ledgers from JSON dump."""
    with open(ledgers_path, encoding="utf-8") as f:
        data = json.load(f)

    raw_ledgers = (
        data.get("parsed_json", {})
            .get("ENVELOPE", {})
            .get("BODY", {})
            .get("DATA", {})
            .get("COLLECTION", {})
            .get("LEDGER", [])
    )
    if not isinstance(raw_ledgers, list):
        raw_ledgers = [raw_ledgers]

    ledgers = []
    for item in raw_ledgers:
        if not isinstance(item, dict):
            continue

        lang = item.get("LANGUAGENAME.LIST", {})
        name_list = lang.get("NAME.LIST", {}) if isinstance(lang, dict) else {}
        name = ""
        if isinstance(name_list, dict):
            name = name_list.get("NAME", "")
        elif isinstance(name_list, list) and name_list:
            name = name_list[0].get("NAME", "") if isinstance(name_list[0], dict) else ""
        if not name:
            name = item.get("RESERVEDNAME", "") or item.get("NAME", "")
        name = str(name).strip()
        if not name:
            continue

        parent_raw = item.get("PARENT", {})
        parent = parent_raw.get("_text", "").strip() if isinstance(parent_raw, dict) else str(parent_raw).strip()

        cb_raw = item.get("CLOSINGBALANCE", {})
        cb_str = cb_raw.get("_text", "0") if isinstance(cb_raw, dict) else str(cb_raw)
        cb_val = clean_float(cb_str)

        gstin_raw = item.get("PARTYGSTIN", {})
        gstin = gstin_raw.get("_text", "").strip() if isinstance(gstin_raw, dict) else str(gstin_raw).strip()

        pan_raw = item.get("INCOMETAXNUMBER", {})
        pan = pan_raw.get("_text", "").strip() if isinstance(pan_raw, dict) else str(pan_raw).strip()

        pincode_raw = item.get("PINCODE", {})
        pincode = pincode_raw.get("_text", "").strip() if isinstance(pincode_raw, dict) else str(pincode_raw).strip()

        sn_raw = item.get("LEDGERSTATENAME", {}) or item.get("STATENAME", {})
        tally_state = sn_raw.get("_text", "").strip() if isinstance(sn_raw, dict) else str(sn_raw).strip()

        addr_list_raw = item.get("ADDRESS.LIST", {})
        address_parts = []
        if isinstance(addr_list_raw, dict):
            addr_data = addr_list_raw.get("ADDRESS", [])
            if isinstance(addr_data, list):
                for a in addr_data:
                    if isinstance(a, dict) and "_text" in a:
                        address_parts.append(a["_text"].strip())
                    elif isinstance(a, str):
                        address_parts.append(a.strip())
            elif isinstance(addr_data, dict):
                val = addr_data.get("_text", "").strip()
                if val:
                    address_parts.append(val)
            elif isinstance(addr_data, str):
                address_parts.append(addr_data.strip())
        address_str = ", ".join(address_parts)

        cp_raw = item.get("CREDITPERIOD", {})
        credit_period = cp_raw.get("_text", "").strip() if isinstance(cp_raw, dict) else str(cp_raw).strip()
        if credit_period.lower() in ("", "0", "0 days"):
            credit_period = ""

        ob_raw = item.get("OPENINGBALANCE", {})
        ob_str = ob_raw.get("_text", "0") if isinstance(ob_raw, dict) else str(ob_raw)
        ob_val = clean_float(ob_str)

        ledgers.append({
            "name": name,
            "tally_parent": parent,
            "opening_balance": cb_val,       # closing balance for the full extraction period
            "tally_opening_balance": ob_val,  # company's very first opening balance
            "gstin": gstin,
            "pan": pan,
            "pincode": pincode,
            "address": address_str,
            "credit_period": credit_period,
            "tally_state": tally_state,
        })

    return ledgers

def run_coa_mapping(ledgers, gmap, out_dir):
    """Maps custom parents and normal ledgers into zoho Chart of Accounts import template."""
    csv_path = os.path.join(out_dir, "zoho_coa_import.csv")
    
    rows = []
    parent_accounts = {}
    
    # 1. Pre-pass to discover all parent accounts
    for l in ledgers:
        t_parent = l["tally_parent"]
        custom_path, root_reserved = resolve_custom_path_and_root(t_parent, gmap)
        zoho_type = TALLY_RESERVED_TO_ZOHO.get(root_reserved)
        if not zoho_type:
            zoho_type = classify_group_by_nature(t_parent, gmap) or "Expense"
        if zoho_type not in NO_SUBACCOUNT_TYPES:
            if len(custom_path) > 0:
                p0 = custom_path[0]
                if p0.lower().strip() not in ZOHO_SYSTEM_ACCOUNTS:
                    if p0 not in parent_accounts:
                        parent_accounts[p0] = {"parent": "", "zoho_type": zoho_type}
                for idx in range(len(custom_path) - 1):
                    p_curr = custom_path[idx]
                    p_child = custom_path[idx + 1]
                    if p_child.lower().strip() not in ZOHO_SYSTEM_ACCOUNTS:
                        if p_child not in parent_accounts:
                            parent_accounts[p_child] = {"parent": p_curr, "zoho_type": zoho_type}

    collision_parent_names = {p.lower().strip() for p in parent_accounts.keys()}

    # 2. Process ledgers into COA rows
    for l in ledgers:
        name = l["name"]
        t_parent = l["tally_parent"]
        
        # Resolve group hierarchy
        custom_path, root_reserved = resolve_custom_path_and_root(t_parent, gmap)
        
        # Base classification from root reserved group
        zoho_type = TALLY_RESERVED_TO_ZOHO.get(root_reserved)
        if not zoho_type:
            # Fallback to nature flags classification
            zoho_type = classify_group_by_nature(t_parent, gmap) or "Expense"

        # Determine nesting parent
        zoho_parent = None
        if zoho_type not in NO_SUBACCOUNT_TYPES:
            if len(custom_path) > 0:
                zoho_parent = custom_path[-1]

        if name.lower().strip() in ZOHO_SYSTEM_ACCOUNTS:
            continue
            
        # Exclude A/R and A/P from COA (managed in Contacts module)
        if zoho_type in ("Accounts Receivable", "Accounts Payable"):
            continue

        # Auto-resolve name collisions with parent groups by appending ' Ledger'
        if name.lower().strip() in collision_parent_names:
            old_name = name
            name = f"{old_name} Ledger"
            p_info = parent_accounts.get(old_name)
            if p_info and p_info.get("zoho_type") == zoho_type:
                if not zoho_parent:
                    zoho_parent = old_name
            else:
                if zoho_parent == old_name:
                    zoho_parent = None
            logger.info(f"Auto-renamed conflicting COA ledger name '{old_name}' -> '{name}' to avoid collision with parent group.")

        # Determine opening balance sign for this account type
        # Debit-normal types: Assets, Expenses → positive Tally OB (<=0 in Tally's sign convention) = Debit
        # Credit-normal types: Liabilities, Income → positive Tally OB (>=0) = Credit
        ob_val = l.get("tally_opening_balance", 0.0)
        abs_ob = abs(ob_val)
        if abs_ob > 0:
            is_debit_normal = zoho_type in DEBIT_NORMAL
            if is_debit_normal:
                ob_dc = "Debit" if ob_val <= 0 else "Credit"
            else:
                ob_dc = "Credit" if ob_val >= 0 else "Debit"
            ob_display = f"{abs_ob:.2f}"
        else:
            ob_dc = ""
            ob_display = ""

        rows.append({
            "Account Name":    name,
            "Account Code":    "",
            "Description":     f"Tally Group: {t_parent}",
            "Account Type":    zoho_type,
            "Parent Account":  zoho_parent or "",
            "Account #":       "",
            "Currency":        CURRENCY,
            "Opening Balance": ob_display,
            "Debit or Credit": ob_dc,
            "_is_parent":      False,
        })

    # Prepare parent account rows
    parent_levels = {}
    def get_level(p_name):
        if p_name not in parent_accounts:
            return 0
        if p_name in parent_levels:
            return parent_levels[p_name]
        parent_link = parent_accounts[p_name]["parent"]
        if not parent_link:
            parent_levels[p_name] = 0
            return 0
        lvl = 1 + get_level(parent_link)
        parent_levels[p_name] = lvl
        return lvl

    for p_name in parent_accounts:
        get_level(p_name)

    sorted_parents = sorted(parent_accounts.keys(), key=lambda k: parent_levels.get(k, 0))
    parent_rows = []
    for parent_name in sorted_parents:
        if parent_name.lower().strip() in ZOHO_SYSTEM_ACCOUNTS:
            continue
        p_info = parent_accounts[parent_name]
        parent_rows.append({
            "Account Name":    parent_name,
            "Account Code":    "",
            "Description":     f"Tally Group (parent account)",
            "Account Type":    p_info["zoho_type"],
            "Parent Account":  p_info["parent"],
            "Account #":       "",
            "Currency":        CURRENCY,
            "Opening Balance": "",
            "Debit or Credit": "",
            "_is_parent":      True,
        })

    # Merge ledger balances into parent rows that share the same name
    parent_row_index = {r["Account Name"].lower().strip(): i for i, r in enumerate(parent_rows)}
    for ledger_row in rows:
        key = ledger_row["Account Name"].lower().strip()
        if key in parent_row_index:
            idx = parent_row_index[key]
            if ledger_row.get("Opening Balance"):
                parent_rows[idx]["Opening Balance"] = ledger_row["Opening Balance"]
                parent_rows[idx]["Debit or Credit"] = ledger_row["Debit or Credit"]

    all_rows = parent_rows + rows

    # De-duplicate by Account Name
    seen_names = set()
    deduped_rows = []
    dup_count = 0
    for row in all_rows:
        key = row["Account Name"].lower().strip()
        if key in seen_names:
            dup_count += 1
            continue
        seen_names.add(key)
        deduped_rows.append(row)
    if dup_count:
        logger.warning(f"Removed {dup_count} duplicate account names.")

    # Write COA CSV
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COA_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped_rows)
    logger.info(f"COA CSV generated at {csv_path}")

    # Write COA XLSX
    xlsx_path = os.path.join(out_dir, "zoho_coa_import.xlsx")
    try:
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Chart of Accounts"
        ws.append(COA_HEADERS)
        for row in deduped_rows:
            ws.append([row.get(fn, "") for fn in COA_HEADERS])
        wb.save(xlsx_path)
        logger.info(f"COA Excel generated at {xlsx_path}")
    except PermissionError:
        base, ext = os.path.splitext(xlsx_path)
        fallback = base + "_unlocked" + ext
        logger.warning(f"Permission denied on COA Excel file. Writing to: {fallback}")
        try:
            wb.save(fallback)
        except Exception as e:
            logger.error(f"Failed to write fallback XLSX: {e}")
    except Exception as e:
        logger.error(f"Failed to generate XLSX file: {e}")

    return deduped_rows, parent_accounts
