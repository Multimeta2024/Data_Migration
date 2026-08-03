# mappers/item_mapper.py
"""
Extracts Stock Items from Tally and maps them to the Zoho Books
Items import CSV template format (29 columns).

Tally data pulled per stock item:
  - Name, Parent group, Description
  - Base unit of measure
  - HSN/SAC code (from GST details)
  - Standard selling rate & purchase rate
  - Opening stock quantity, rate, value
  - GST details (CGST/SGST/IGST rates and applicability)
  - Whether it is Goods or Service
  - Vendor (first preferred vendor if set)
"""

import os
import csv
import logging
from lxml import etree

from config.constants import ITEM_HEADERS, ITEM_OPENING_STOCK_HEADERS, TALLY_UNIT_TO_ZOHO
from core.xml_parser import sanitize_xml
from utils.math_helpers import clean_float

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tally TDL Query
# ---------------------------------------------------------------------------

def query_stock_items(tally_client) -> str:
    """
    Fetch all Stock Items from Tally with full detail.
    No date filter needed — stock item master data is not period-specific.
    """
    payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>StockItemsCollection</ID>
    </HEADER>
    <BODY>
        <DESC>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="StockItemsCollection" ISMODIFY="No">
                        <TYPE>StockItem</TYPE>
                        <FETCH>Name,Parent,Description,BaseUnits,ReservedName</FETCH>
                        <FETCH>OpeningBalance,OpeningRate,OpeningValue</FETCH>
                        <FETCH>StandardCostPrice,StandardSellingPrice</FETCH>
                        <FETCH>GSTAPPLICABLE,GSTTYPEOFSUPPLY</FETCH>
                        <FETCH>HSNDETAILS.*,GSTDETAILS.*</FETCH>
                        <FETCH>PURCHASEPRICINGDETAILS.*,SELLINGPRICINGDETAILS.*</FETCH>
                        <FETCH>LanguageName.*</FETCH>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>"""
    return tally_client.send_request(payload)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _txt(elem, tag: str) -> str:
    """Safe text extraction from an XML element child."""
    child = elem.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _clean_unit(tally_unit: str) -> str:
    """Normalise a Tally UOM string to a Zoho-compatible unit."""
    if not tally_unit:
        return "pcs"
    key = tally_unit.strip().lower()
    if "/" in key:
        key = key.split("/")[0].strip()
    return TALLY_UNIT_TO_ZOHO.get(key, key[:10])


def _parse_qty_rate(raw_qty: str, raw_rate: str):
    """
    Tally stores OpeningBalance as '10 Nos' or '-6.00 Nos' and OpeningRate as '350/Nos'.
    Returns (qty_float, rate_float).
    """
    qty = 0.0
    rate = 0.0
    if raw_qty:
        parts = raw_qty.strip().split()
        try:
            qty = float(parts[0])
        except (ValueError, IndexError):
            qty = 0.0
    if raw_rate:
        rate_part = raw_rate.split("/")[0].strip()
        try:
            rate = float(rate_part)
        except ValueError:
            rate = 0.0
    return qty, rate


def _parse_gst_details(item_elem) -> dict:
    """
    Extract GST rates (CGST, SGST, IGST) and HSN from GSTDETAILS / HSNDETAILS.
    """
    result = {
        "hsn": "",
        "cgst_rate": 0.0,
        "sgst_rate": 0.0,
        "igst_rate": 0.0,
        "gst_applicable": "",
        "supply_type": "goods",
    }

    gst_app = _txt(item_elem, "GSTAPPLICABLE").lower()
    result["gst_applicable"] = gst_app

    supply_type_raw = _txt(item_elem, "GSTTYPEOFSUPPLY").lower()
    if "service" in supply_type_raw:
        result["supply_type"] = "service"
    else:
        result["supply_type"] = "goods"

    for hsn_detail in item_elem.findall(".//HSNDETAILS.LIST"):
        hsn_code = _txt(hsn_detail, "HSNCODE") or _txt(hsn_detail, "HSN")
        if hsn_code:
            result["hsn"] = hsn_code
            break

    for gst_detail in item_elem.findall(".//GSTDETAILS.LIST"):
        duty_head = _txt(gst_detail, "GSTRATEDUTYHEAD").upper()
        rate_str = _txt(gst_detail, "GSTRATE")
        try:
            rate_val = float(rate_str) if rate_str else 0.0
        except ValueError:
            rate_val = 0.0

        if duty_head == "CGST":
            result["cgst_rate"] = rate_val
        elif duty_head in ("SGST", "SGST/UTGST", "UTGST"):
            result["sgst_rate"] = rate_val
        elif duty_head == "IGST":
            result["igst_rate"] = rate_val

    return result


def _build_tax_columns(gst: dict) -> dict:
    """
    Build Zoho inter-state and intra-state tax columns.
    """
    gst_app = gst.get("gst_applicable", "")
    cgst = gst.get("cgst_rate", 0.0)
    sgst = gst.get("sgst_rate", 0.0)
    igst = gst.get("igst_rate", 0.0)

    intra_total = int(round(cgst + sgst))
    inter_total = int(round(igst)) if igst > 0 else intra_total

    taxability_type = ""
    exemption_reason = ""
    inter_tax_name = ""
    inter_tax_type = ""
    inter_tax_rate = ""
    intra_tax_name = ""
    intra_tax_type = ""
    intra_tax_rate = ""

    if gst_app in ("notapplicable", "exempt"):
        taxability_type = "NON TAXABLE EXEMPTION"
    elif gst_app == "nongst":
        taxability_type = "Non-GST Supply"
    elif intra_total == 0 and inter_total == 0:
        taxability_type = ""
    else:
        if inter_total > 0:
            inter_tax_name = f"IGST{inter_total}"
            inter_tax_type = "Simple"
            inter_tax_rate = str(inter_total)
        if intra_total > 0:
            intra_tax_name = f"GST{intra_total}"
            intra_tax_type = "Group"
            intra_tax_rate = str(intra_total)

    return {
        "Taxability Type": taxability_type,
        "Exemption Reason": exemption_reason,
        "Inter State Tax Name": inter_tax_name,
        "Inter State Tax Type": inter_tax_type,
        "Inter State Tax Rate": inter_tax_rate,
        "Intra State Tax Name": intra_tax_name,
        "Intra State Tax Type": intra_tax_type,
        "Intra State Tax Rate": intra_tax_rate,
    }


def _get_selling_rate(item_elem, std_selling: float) -> float:
    if std_selling and std_selling > 0:
        return std_selling

    for sp in item_elem.findall(".//SELLINGPRICINGDETAILS.LIST"):
        rate_str = _txt(sp, "RATE")
        if rate_str:
            rate_part = rate_str.split("/")[0].strip()
            try:
                val = float(rate_part)
                if val > 0:
                    return val
            except ValueError:
                pass
    return 0.0


def _get_purchase_rate(item_elem, std_cost: float) -> float:
    if std_cost and std_cost > 0:
        return std_cost

    for pp in item_elem.findall(".//PURCHASEPRICINGDETAILS.LIST"):
        rate_str = _txt(pp, "RATE")
        if rate_str:
            rate_part = rate_str.split("/")[0].strip()
            try:
                val = float(rate_part)
                if val > 0:
                    return val
            except ValueError:
                pass
    return 0.0


# ---------------------------------------------------------------------------
# Main mapper
# ---------------------------------------------------------------------------

def run_item_mapping(tally_client, out_dir: str) -> list:
    """
    Fetches all Tally Stock Items, maps them to Zoho Books Items import
    CSV format and Item Opening Stock import CSV format.
    """
    base_csv = os.path.join(out_dir, "zoho_items_import.csv")
    op_stock_csv = os.path.join(out_dir, "zoho_items_opening_stock_import.csv")

    logger.info("Querying Stock Items from Tally...")
    xml_data = query_stock_items(tally_client)
    xml_cleaned = sanitize_xml(xml_data)

    parser = etree.XMLParser(recover=True)
    root = etree.fromstring(xml_cleaned.encode("utf-8", errors="ignore"), parser=parser)

    items_raw = root.findall(".//STOCKITEM")
    logger.info(f"Total stock items found in Tally: {len(items_raw)}")

    rows = []
    opening_stock_rows = []
    seen_item_names = {}

    for item_elem in items_raw:
        # --- Name ---
        raw_name = _txt(item_elem, "NAME")
        if not raw_name:
            name_el = item_elem.find(".//LANGUAGENAME.LIST/NAME.LIST/NAME")
            if name_el is not None and name_el.text:
                raw_name = name_el.text.strip()
        if not raw_name:
            raw_name = item_elem.get("NAME", "").strip()
        if not raw_name:
            continue

        # Deduplicate item names so every row in CSV has a unique Item Name
        if raw_name in seen_item_names:
            seen_item_names[raw_name] += 1
            name = f"{raw_name} - {seen_item_names[raw_name]}"
            logger.info(f"Deduplicated item name '{raw_name}' -> '{name}'")
        else:
            seen_item_names[raw_name] = 1
            name = raw_name

        parent = _txt(item_elem, "PARENT")
        description = _txt(item_elem, "DESCRIPTION")
        if not description:
            description = name

        raw_unit = _txt(item_elem, "BASEUNITS")
        zoho_unit = _clean_unit(raw_unit)

        std_selling_raw = _txt(item_elem, "STANDARDSELLINGPRICE")
        std_cost_raw = _txt(item_elem, "STANDARDCOSTPRICE")

        std_selling_str = std_selling_raw.split("/")[0].strip() if std_selling_raw else "0"
        std_cost_str = std_cost_raw.split("/")[0].strip() if std_cost_raw else "0"

        try:
            std_selling = float(std_selling_str)
        except ValueError:
            std_selling = 0.0
        try:
            std_cost = float(std_cost_str)
        except ValueError:
            std_cost = 0.0

        selling_rate = _get_selling_rate(item_elem, std_selling)
        purchase_rate = _get_purchase_rate(item_elem, std_cost)

        ob_qty_raw = _txt(item_elem, "OPENINGBALANCE")
        ob_rate_raw = _txt(item_elem, "OPENINGRATE")
        ob_value_raw = _txt(item_elem, "OPENINGVALUE")

        ob_qty, ob_rate = _parse_qty_rate(ob_qty_raw, ob_rate_raw)
        ob_qty = abs(ob_qty)
        ob_rate = abs(ob_rate)
        ob_value = abs(clean_float(ob_value_raw))

        if ob_rate == 0.0 and ob_qty > 0 and ob_value > 0:
            ob_rate = ob_value / ob_qty
        if ob_value == 0.0 and ob_qty > 0 and ob_rate > 0:
            ob_value = ob_qty * ob_rate

        gst = _parse_gst_details(item_elem)
        tax_cols = _build_tax_columns(gst)
        supply_type = gst.get("supply_type", "goods")

        product_type = supply_type

        def _fmt_rate(v):
            if v is None or float(v) == 0.0:
                return "0"
            f = abs(float(v))
            return str(int(f)) if f == int(f) else f"{f:.2f}"

        def _fmt_qty(v):
            if v is None or float(v) <= 0.0:
                return ""
            f = abs(float(v))
            return str(int(f)) if f == int(f) else f"{f:.2f}"

        # Now that Inventory Tracking is enabled in Zoho Books, goods items are imported
        # with Item Type = 'Inventory' so Zoho enables inventory tracking and registers Initial Stock.
        if supply_type == "service":
            item_type = "Sales and Purchases"
            sales_account = "Sales"
            purchase_account = "Cost of Goods Sold"
            inventory_account = ""
            init_stock = ""
            init_rate = ""
            warehouse_name = ""
        else:
            item_type = "Inventory"
            sales_account = "Sales"
            purchase_account = "Cost of Goods Sold"
            inventory_account = "Inventory Asset"
            init_stock = _fmt_qty(ob_qty) if ob_qty > 0 else "0"
            init_rate = _fmt_rate(ob_rate) if ob_qty > 0 else "0"
            warehouse_name = "Head Office"

        row = {
            "Item Name":          name,
            "SKU":                "",
            "HSN/SAC":            gst.get("hsn", ""),
            "Description":        description,
            "Rate":               _fmt_rate(selling_rate),
            "Product Type":       product_type,
            "Account":            sales_account,
            "Usage unit":         zoho_unit,
            "Purchase Description": description,
            "Purchase Rate":      _fmt_rate(purchase_rate),
            "Item Type":          item_type,
            "Purchase Account":   purchase_account,
            "Inventory Account":  inventory_account,
            "Reorder Point":      "",
            "Vendor":             "",
            "Initial Stock":      init_stock,
            "Initial Stock Rate": init_rate,
            "Stock On Hand":      init_stock,
            "Status":             "Active",
            **tax_cols,
            "Warehouse Name":     warehouse_name,
            "CF.custom_field":    "",
        }
        rows.append(row)

        if ob_qty > 0:
            opening_stock_rows.append({
                "Item Name":           name,
                "SKU":                 "",
                "Opening Stock":       _fmt_qty(ob_qty),
                "Opening Stock Value": _fmt_rate(ob_value),
                "TrackSerialNumber":   "FALSE",
                "Track Batches":       "FALSE",
                "Enable Bin Tracking":  "FALSE",
                "Location Name":       "Head Office",
                "Batch Reference#":    "",
                "Manufacturer Batch#": "",
                "Manufactured Date":   "",
                "Expiry Date":         "",
                "Quantity In":         "",
                "Bin Name":            "",
                "Bin Quantity":        "",
                "Serial Numbers":      ""
            })

    _write_csv_file(base_csv, ITEM_HEADERS, rows)
    logger.info(f"Items import file generated: {base_csv} ({len(rows)} items)")

    if opening_stock_rows:
        _write_csv_file(op_stock_csv, ITEM_OPENING_STOCK_HEADERS, opening_stock_rows)
        logger.info(f"Item Opening Stock import file generated: {op_stock_csv} ({len(opening_stock_rows)} items)")

    return rows


def _write_csv_file(path: str, headers: list, rows: list):
    """Write CSV file; on PermissionError write to _unlocked fallback."""
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

