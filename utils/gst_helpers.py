# utils/gst_helpers.py

import re
from config.constants import STATE_TO_CODE, GST_STATE_MAP

_GSTIN_COMPOSITION_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]C[0-9A-Z]$')
_GSTIN_REGULAR_RE = re.compile(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$')
_GSTIN_UIN_RE = re.compile(r'^0007[A-Z0-9]{11}$')

def get_state_code(state_str: str) -> str:
    """Resolves standard 2-letter state code from string description."""
    if not state_str:
        return ""
    s = state_str.strip().lower()
    if s in STATE_TO_CODE:
        return STATE_TO_CODE[s]
    # Check if already 2-char code
    if len(state_str.strip()) == 2 and state_str.strip().isalpha():
        return state_str.strip().upper()
    
    s_clean = "".join(s.split())
    for k, v in STATE_TO_CODE.items():
        if "".join(k.split()) == s_clean:
            return v
    return state_str.strip().upper()[:5]

def infer_gst_treatment(gstin: str) -> str:
    """Infers Zoho GST treatment string based on the shape of a GSTIN."""
    if not gstin:
        return "business_unregistered"
    gstin_stripped = "".join(gstin.split()).upper()
    if _GSTIN_COMPOSITION_RE.match(gstin_stripped):
        return "business_gst_registered_composition"
    if _GSTIN_UIN_RE.match(gstin_stripped):
        return "consumer"
    if _GSTIN_REGULAR_RE.match(gstin_stripped):
        return "business_registered_regular"
    return "business_unregistered"
