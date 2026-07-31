# core/xml_parser.py

import re
from lxml import etree

_illegal_xml_chars_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1F\uD800-\uDFFF\uFFFE\uFFFF]')

def clean_xml(text: str) -> str:
    """Remove illegal characters from XML."""
    return _illegal_xml_chars_RE.sub('', text)

def remove_invalid_char_refs(xml_text: str) -> str:
    """Remove numeric character references that are invalid."""
    return re.sub(r'&#(?:[0-8]|1[0-9]|2[0-9]|3[0-1]);', '', xml_text)

def remove_udf_namespace_prefixes(xml_text: str) -> str:
    """Convert un-prefixed/un-declared UDF namespace tags to prevent parsing errors."""
    return re.sub(r'<(/?UDF):([^>]+)>', r'<\1_\2>', xml_text)

def sanitize_xml(xml_text: str) -> str:
    """Run all cleaning functions on XML input."""
    cleaned = clean_xml(xml_text)
    cleaned = remove_invalid_char_refs(cleaned)
    cleaned = remove_udf_namespace_prefixes(cleaned)
    return cleaned

def etree_to_dict(t: etree._Element) -> dict:
    """Convert an lxml ElementTree to a nested dict representation."""
    d = {t.tag: {} if t.attrib else None}
    children = list(t)

    if children:
        dd = {}
        for dc in map(etree_to_dict, children):
            for k, v in dc.items():
                if k in dd:
                    if not isinstance(dd[k], list):
                        dd[k] = [dd[k]]
                    dd[k].append(v)
                else:
                    dd[k] = v
        d = {t.tag: dd}
    else:
        d = {t.tag: t.text}
    return d
