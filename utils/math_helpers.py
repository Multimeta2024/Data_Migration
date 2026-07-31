# utils/math_helpers.py

import re

def clean_float(val_str: str) -> float:
    """Safely converts string to float, removing commas."""
    if not val_str:
        return 0.0
    if isinstance(val_str, (int, float)):
        return float(val_str)
    val_str = str(val_str).replace(",", "").strip()
    try:
        return float(val_str)
    except ValueError:
        return 0.0

def parse_qty_unit(qty_str: str) -> tuple:
    """Parses a quantity string (e.g. '20110.000 Kgs') into a float and unit name."""
    if not qty_str:
        return 1.0, "count"
    qty_str = qty_str.strip()
    match = re.match(r"^\s*([-\d.]+)\s*(.*)$", qty_str)
    if match:
        try:
            qty_num = float(match.group(1))
            unit = match.group(2).strip() or "count"
            return qty_num, unit
        except ValueError:
            pass
    return 1.0, "count"

def parse_rate(rate_str: str) -> float:
    """Extracts the base numerical rate from strings like '26.00/Kgs'."""
    if not rate_str:
        return 0.0
    rate_str = rate_str.strip()
    match = re.match(r"^\s*([-\d.]+)", rate_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0

def parse_due_days(terms_str: str) -> int:
    """Extracts credit days count from terms string (e.g. '60 Days' -> 60)."""
    if not terms_str:
        return 0
    match = re.search(r"(\d+)\s*Days", terms_str, re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)", terms_str)
    if match:
        return int(match.group(1))
    return 0
