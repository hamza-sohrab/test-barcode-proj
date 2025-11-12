from __future__ import annotations

from typing import List, Optional
import re


_EAN13_PRICE_EMBEDDED = re.compile(
    r"^(?P<prefix>2)(?P<itemCode>\d{5})(?P<itemCodeCheckDigit>\d)(?P<price>\d{5})(?P<checkDigit>\d)$"
)
_DATABAR_EXPANDED = re.compile(r"^(?P<prefix>01)(?P<gtin>\d{13})(?P<checkDigit>.)(?P<attributes>.+)$")


def _digits_only(s: str) -> str:
    """Extract only digits from a string."""
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _left_pad_to_13(s: str) -> str:
    """Pad digits to 13 characters with leading zeros."""
    d = _digits_only(s)
    if len(d) >= 13:
        return d[:13]
    return ("0" * (13 - len(d))) + d


def _remove_check_digit_and_pad(s: str) -> str:
    """Remove the last digit (check digit) and pad to 13 digits."""
    d = _digits_only(s)
    if not d:
        return d
    core = d[:-1]
    return _left_pad_to_13(core)


def _to_padded_raw_barcode(s: str) -> str:
    """Pad raw barcode to 13 digits without removing check digit."""
    d = _digits_only(s)
    return _left_pad_to_13(d)


def _calculate_check_digit(s: str) -> Optional[int]:
    """Calculate GTIN check digit using the standard algorithm."""
    if not s or not s.isdigit():
        return None
    try:
        # For GTIN-12/GTIN-13: sum odd positions * 3 + even positions
        total = sum(int(s[i]) * (3 if i % 2 == 0 else 1) for i in range(len(s)))
        return (10 - (total % 10)) % 10
    except Exception:
        return None


def _is_valid_check_digit(barcode: str) -> bool:
    """Validate the check digit of a barcode."""
    if len(barcode) < 2:
        return False
    core = barcode[:-1]
    check = _calculate_check_digit(core)
    return check is not None and str(check) == barcode[-1]


def _expand_upce_to_upca(upce: str) -> Optional[str]:
    """Expand UPC-E (6-8 digits) to UPC-A (12 digits).
    
    This implements the standard UPC-E expansion algorithm.
    """
    # Normalize to 7 digits (add leading 0 if 6 digits, add trailing 0 if 7)
    digits = _digits_only(upce)
    if len(digits) == 6:
        digits = "0" + digits + "0"
    elif len(digits) == 7:
        digits = digits + "0"
    elif len(digits) != 8:
        return None
    
    # Check if starts with 0 or 1 (valid UPC-E)
    if digits[0] not in ('0', '1'):
        return None
    
    number_system = digits[0]
    last_digit = digits[6]
    manufacturer = digits[1:6]
    check = digits[7] if len(digits) == 8 else "0"
    
    # Expansion rules based on last digit
    if last_digit in ('0', '1', '2'):
        expanded = number_system + manufacturer[:2] + last_digit + "0000" + manufacturer[2:5] + check
    elif last_digit == '3':
        expanded = number_system + manufacturer[:3] + "00000" + manufacturer[3:5] + check
    elif last_digit == '4':
        expanded = number_system + manufacturer[:4] + "00000" + manufacturer[4] + check
    else:  # 5-9
        expanded = number_system + manufacturer + "0000" + last_digit + check
    
    return expanded


def normalize_candidates(value: str, barcode_type: str) -> List[str]:
    """Return prioritized lookup candidates following Caper production normalization rules.
    
    This is the enhanced version based on production code from caper-repo.
    
    Rules:
    - Always include the raw digits as first candidate
    - EAN-13 price-embedded (2 + 5 digits + check + 5 price digits + check): 
      Generate "002" + itemCode padded to 13
    - UPC-A/EAN-13 already normalized with 002 prefix:
      Add no-price variant (last 5 digits zeroed)
    - UPC-E (6-8 digits): Expand to UPC-A, then normalize
    - EAN-8 (8 digits): Remove check digit and pad to 13
    - DataBar (14-16 digits): Include 14-digit GTIN and 13-digit (remove check + pad)
    - DataBar Expanded (starting with 01): Extract GTIN-14 from AI string
    - Code 128 (9-11 digits): Add both remove-check-digit-and-pad and pad-to-13 variants
    - Code 128 (12 digits without valid check): Treat as EAN-13 (pad to 13)
    - Code 128 (12 digits with valid check): Treat as UPC-A (remove check + pad)
    """
    candidates: List[str] = []
    raw = _digits_only(value)
    
    if not raw:
        return candidates
    
    # Always start with raw digits
    candidates.append(raw)
    
    # EAN-13 price-embedded detection (raw barcode, not normalized)
    if barcode_type == "EAN-13" and len(raw) == 13:
        m = _EAN13_PRICE_EMBEDDED.match(raw)
        if m:
            item_code = m.group("itemCode")  # 5 digits
            # lookup: "002" + itemCode, pad to 13 with trailing zeros
            lookup = ("002" + item_code).ljust(13, "0")
            if lookup not in candidates:
                candidates.append(lookup)
            # Also add a variant without price (already normalized with 002 prefix)
            no_price = (raw[:8] + "00000")
            if no_price not in candidates:
                candidates.append(no_price)
            return candidates
    
    # UPC-E expansion
    if barcode_type in ("UPC-E", "UPCE") and 6 <= len(raw) <= 8:
        upca = _expand_upce_to_upca(raw)
        if upca:
            normalized = _remove_check_digit_and_pad(upca)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
    
    # EAN-8 normalization
    if barcode_type == "EAN-8" and len(raw) == 8:
        normalized = _remove_check_digit_and_pad(raw)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    
    # DataBar / GS1 handling
    if barcode_type in ("GS1 DataBar", "GS1 DataBar Expanded", "DataBar"):
        # DataBar Expanded with AI elements
        if value.startswith("01") or value.startswith("(01)"):
            m = _DATABAR_EXPANDED.match(raw)
            if m:
                gtin14 = m.group("gtin")  # Extract 13-digit GTIN from AI
                if gtin14 and gtin14 not in candidates:
                    candidates.append(gtin14)
        
        # 16-digit DataBar (2-digit prefix + 14-digit GTIN)
        if len(raw) == 16 and raw.startswith("01"):
            gtin14 = raw[2:]
            if gtin14 and gtin14 not in candidates:
                candidates.append(gtin14)
            # Also add 13-digit variant
            gtin13 = _remove_check_digit_and_pad(gtin14)
            if gtin13 and gtin13 not in candidates:
                candidates.append(gtin13)
        
        # 14-digit DataBar
        elif len(raw) == 14:
            if raw not in candidates:
                candidates.append(raw)
            gtin13 = _remove_check_digit_and_pad(raw)
            if gtin13 and gtin13 not in candidates:
                candidates.append(gtin13)
    
    # Code 128 handling (variable length)
    if barcode_type == "Code 128":
        # 9-11 digits: multi-lookup for catalog inconsistencies
        if 9 <= len(raw) <= 11:
            v1 = _remove_check_digit_and_pad(raw)
            v2 = _to_padded_raw_barcode(raw)
            for v in (v1, v2):
                if v and v not in candidates:
                    candidates.append(v)
        
        # 12 digits: determine if UPC-A or EAN-13 based on check digit validity
        elif len(raw) == 12:
            # Not price-embedded (doesn't start with 2)
            if not raw.startswith("2"):
                has_valid_check = _is_valid_check_digit(raw)
                if has_valid_check:
                    # Valid check digit = UPC-A (remove check + pad)
                    v = _remove_check_digit_and_pad(raw)
                    if v and v not in candidates:
                        candidates.append(v)
                else:
                    # Invalid check = EAN-13 without check digit (pad to 13)
                    v = _to_padded_raw_barcode(raw)
                    if v and v not in candidates:
                        candidates.append(v)
    
    # UPC-A/EAN-13 normalized price-embedded (starts with 002)
    if len(raw) == 13 and raw.startswith("002"):
        # Add no-price variant: keep first 8 digits, zero out last 5
        no_price = raw[:8] + "00000"
        if no_price not in candidates:
            candidates.append(no_price)
    
    # Standard UPC-A/EAN-13 normalization
    if barcode_type in ("UPC-A", "UPCA") and len(raw) == 12:
        normalized = _remove_check_digit_and_pad(raw)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    
    if barcode_type == "EAN-13" and len(raw) == 13 and not raw.startswith("2"):
        # Non-price-embedded EAN-13
        normalized = _remove_check_digit_and_pad(raw)
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    
    return candidates


def extract_price_from_barcode(value: str, barcode_type: str) -> Optional[int]:
    """Extract embedded price from price-embedded barcodes.
    
    Returns price in cents (e.g., 12345 = $123.45) or None if not price-embedded.
    """
    raw = _digits_only(value)
    
    # EAN-13 price-embedded
    if barcode_type == "EAN-13" and len(raw) == 13:
        m = _EAN13_PRICE_EMBEDDED.match(raw)
        if m:
            price_str = m.group("price")  # 5 digits
            return int(price_str)
    
    # UPC-A price-embedded (normalized with 002 prefix)
    if len(raw) == 13 and raw.startswith("002"):
        price_str = raw[-5:-1]  # Last 4 meaningful digits (exclude check)
        return int(price_str)
    
    return None


def is_price_embedded(value: str, barcode_type: str) -> bool:
    """Check if a barcode is price-embedded."""
    raw = _digits_only(value)
    
    # UPC-A starting with 2
    if barcode_type in ("UPC-A", "UPCA") and raw.startswith("2"):
        return True
    
    # EAN-13 starting with 20-29
    if barcode_type == "EAN-13" and len(raw) >= 2 and raw[:2] in {
        "20", "21", "22", "23", "24", "25", "26", "27", "28", "29"
    }:
        return True
    
    # Normalized format with 002 prefix
    if len(raw) == 13 and raw.startswith("002"):
        return True
    
    return False
