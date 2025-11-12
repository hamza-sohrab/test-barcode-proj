from dataclasses import dataclass
from typing import List, Optional, Tuple
import re

from PIL import Image

from .unified_barcode_detector import DetectedBarcode, identify_item_type
from .ocr_item_name import ocr_item_name, ocr_plu_code, ocr_plu_code_fallback, ocr_plu_code_boost, ocr_bold_name
from .deep_lookup import deep_lookup_product_name, deep_lookup_queries
from .free_lookup import duckduckgo_lookup, duckduckgo_lookup_queries
from .lookup import lookup_product_name
from .gs1_parser import extract_gtin
from .models import RowDraft
from .caper_normalizer import normalize_candidates
from .ocr_upcean import ocr_upcean_numeric, ocr_upcean_digit_band

RE_CODE = re.compile(r"\b\d{8,14}\b")
DIGITS_ONLY = re.compile(r"\d+")
BAD_TERMS = (
	"upc", "ean", "isbn", "barcode", "lookup", "search", "generator", "validator", "database"
)
ALLOWED_WEB_TYPES = {"UPC-A", "EAN-13", "UPC-E", "EAN-8"}

LINEAR_TYPES = {"UPC-A", "EAN-13", "UPC-E", "EAN-8", "Code 128", "Code 39", "ITF", "GS1 DataBar", "GS1 DataBar Expanded"}


@dataclass
class ProcessOptions:
	ocr: bool = False
	lookup: bool = False
	free_lookup: bool = False
	deep_lookup: bool = False
	plu_all: bool = False
	plu_boost: bool = False
	allow_gs1_web: bool = False
	serp_key: Optional[str] = None
	cse_id: Optional[str] = None
	google_key: Optional[str] = None
	mark_uncertain: bool = True  # Add note if barcode detected but uncertain


def _is_gs1_databar(barcode_type: str, value: str) -> bool:
	# Only treat DataBar types as GS1 for display/PLU logic; do not infer by value prefix
	return "DataBar" in (barcode_type or "")


def _validate_databar_checksum(value: str) -> bool:
	"""Validate DataBar checksum to detect false positives.
	
	DataBar values often start with "01" (Application Identifier for GTIN).
	We extract the GTIN-14 and validate its check digit.
	Returns True if valid, False if invalid (likely a misread).
	"""
	if not value:
		return False
	
	# Strip AI parentheses if present (e.g., "(01)12345...")
	clean = value.replace("(", "").replace(")", "")
	
	# Extract just digits
	digits_only = ''.join(c for c in clean if c.isdigit())
	
	if len(digits_only) < 14:
		return False  # Too short
	
	# If starts with "01" (GTIN AI), extract the 14-digit GTIN after it
	gtin = None
	if digits_only.startswith("01") and len(digits_only) >= 16:
		gtin = digits_only[2:16]  # Skip "01", take next 14 digits
	elif len(digits_only) == 14:
		gtin = digits_only[:14]
	else:
		# For other lengths, try first 14 digits
		gtin = digits_only[:14]
	
	if len(gtin) != 14:
		return False
	
	try:
		# GTIN-14 check digit (same as EAN/UPC algorithm)
		# From LEFT, positions at even indices (0,2,4...) multiply by 3
		# positions at odd indices (1,3,5...) multiply by 1
		total = 0
		for i in range(13):
			if i % 2 == 0:
				total += int(gtin[i]) * 3
			else:
				total += int(gtin[i])
		
		check_digit = (10 - (total % 10)) % 10
		return check_digit == int(gtin[13])
	except (ValueError, IndexError):
		return False


def _is_price_embedded(barcode_type: str, value: str) -> bool:
	if barcode_type == "UPC-A" and value.startswith("2"):
		return True
	if barcode_type == "EAN-13" and value[:2] in {"20","21","22","23","24","25","26","27","28","29"}:
		return True
	return False


def _validate_name(candidate: Optional[str], barcode_value: str) -> Optional[str]:
	if not candidate:
		return None
	c = candidate.strip()
	if not c:
		return None
	lc = c.lower()
	if any(term in lc for term in BAD_TERMS):
		return None
	# Reject exact code echoes or mostly numeric tokens
	if c == barcode_value or RE_CODE.search(c) and not re.search(r"[A-Za-z]", c):
		return None
	# Basic length
	letters_only = re.sub(r"[^A-Za-z]", "", c)
	if len(letters_only) < 4:
		return None
	# Alpha ratio
	alnum = re.sub(r"[^A-Za-z0-9]", "", c)
	if not alnum:
		return None
	alpha_ratio = len(letters_only) / float(len(alnum))
	if alpha_ratio < 0.65:
		return None
	# Average word length
	words = [w for w in re.split(r"\s+", c) if w]
	avg_len = sum(len(re.sub(r"[^A-Za-z]", "", w)) for w in words) / float(len(words)) if words else 0
	if avg_len < 3:
		return None
	
	# Reject gibberish: single short all-caps words (like "NTNU", "XYZ", etc.)
	# These are likely OCR misreads from packaging labels/barcodes
	if len(words) == 1 and len(letters_only) <= 6 and c.isupper():
		return None
	
	return c


def _display_value_for(b: DetectedBarcode) -> Tuple[str, Optional[str]]:
	"""Return (display_value, gtin) for the row.
	Only normalize DataBar with "01" prefix, keep others raw.
	"""
	is_gs1 = _is_gs1_databar(b.barcode_type, b.barcode_value)
	display = b.barcode_value
	gtin: Optional[str] = None
	
	# Only normalize DataBar - add "01" prefix for GTIN
	if is_gs1:
		# Keep full AI element string if present (e.g., (01)...(3922)...(16)...)
		if b.barcode_value.startswith("("):
			return b.barcode_value, extract_gtin(b.barcode_value)
		# Else, try to derive GTIN and show 01+GTIN
		gtin = extract_gtin(b.barcode_value)
		if not gtin:
			m = DIGITS_ONLY.match(b.barcode_value)
			if m and len(m.group(0)) >= 14:
				gtin = m.group(0)[:14]
		if gtin and len(gtin) == 14:
			display = "01" + gtin
	
	# For UPC/EAN, return raw without normalization
	return display, gtin


def _checksum_ean13(s: str) -> bool:
	if len(s) != 13 or not s.isdigit():
		return False
	sum_odd = sum(int(s[i]) for i in range(0, 12, 2))
	sum_even = sum(int(s[i]) for i in range(1, 12, 2))
	check = (10 - ((sum_odd + 3 * sum_even) % 10)) % 10
	return check == int(s[12])


def _checksum_ean8(s: str) -> bool:
	if len(s) != 8 or not s.isdigit():
		return False
	sum_odd = sum(int(s[i]) for i in range(0, 7, 2))
	sum_even = sum(int(s[i]) for i in range(1, 7, 2))
	check = (10 - ((3 * sum_odd + sum_even) % 10)) % 10
	return check == int(s[7])


def _checksum_upca(s: str) -> bool:
	if len(s) != 12 or not s.isdigit():
		return False
	sum_odd = sum(int(s[i]) for i in range(0, 11, 2))
	sum_even = sum(int(s[i]) for i in range(1, 11, 2))
	check = (10 - (((sum_odd * 3) + sum_even) % 10)) % 10
	return check == int(s[11])


def _is_valid_upcean(barcode_type: str, value: str) -> bool:
	if barcode_type == "EAN-13":
		return _checksum_ean13(value)
	if barcode_type == "EAN-8":
		return _checksum_ean8(value)
	if barcode_type == "UPC-A":
		return _checksum_upca(value)
	# Skip strict validation for UPC-E here
	return True


def _quad_area(b: DetectedBarcode) -> int:
	if not b.quad:
		return 0
	xs = [p[0] for p in b.quad]
	ys = [p[1] for p in b.quad]
	w = max(xs) - min(xs)
	h = max(ys) - min(ys)
	return max(0, w) * max(0, h)


def _bbox_from_quad(b: DetectedBarcode) -> Optional[tuple[int,int,int,int]]:
	if not b.quad:
		return None
	xs = [p[0] for p in b.quad]
	ys = [p[1] for p in b.quad]
	return (min(xs), min(ys), max(xs), max(ys))


def _overlap_ratio_1d(a1: int, a2: int, b1: int, b2: int) -> float:
	"""Return intersection length divided by min segment length (0..1)."""
	left = max(a1, b1)
	right = min(a2, b2)
	inter = max(0, right - left)
	la = max(0, a2 - a1)
	lb = max(0, b2 - b1)
	min_len = max(1, min(la, lb))
	return inter / float(min_len)


def _prefer_topmost_stacked(barcodes: List[DetectedBarcode]) -> List[DetectedBarcode]:
	"""If multiple barcodes are stacked vertically with strong horizontal overlap,
	keep only the top-most one in each stack.
	"""
	indexed_boxes: List[tuple[int, Optional[tuple[int,int,int,int]]]] = [
		(i, _bbox_from_quad(b)) for i, b in enumerate(barcodes)
	]
	# Sort by top (min_y); barcodes without quads go last and won't be filtered
	order = sorted(indexed_boxes, key=lambda t: (t[1][1] if t[1] else 10**9))
	dropped: set[int] = set()
	for k, (i, box_i) in enumerate(order):
		if box_i is None or i in dropped:
			continue
		ix1, iy1, ix2, iy2 = box_i
		for j, box_j in order[k+1:]:
			if j in dropped or box_j is None:
				continue
			jx1, jy1, jx2, jy2 = box_j
			# Strong horizontal overlap, minimal vertical overlap ⇒ stacked
			h_ov = _overlap_ratio_1d(ix1, ix2, jx1, jx2)
			v_ov = _overlap_ratio_1d(iy1, iy2, jy1, jy2)
			if h_ov >= 0.6 and v_ov <= 0.1:
				# Drop the lower one (larger top y)
				if iy1 <= jy1:
					dropped.add(j)
				else:
					dropped.add(i)
					break
	return [b for idx, b in enumerate(barcodes) if idx not in dropped]


def _type_pref(t: str) -> int:
	# Prefer UPC-A > EAN-13 > UPC-E > EAN-8
	order = {"UPC-A": 4, "EAN-13": 3, "UPC-E": 2, "EAN-8": 1}
	return order.get(t, 0)


def _dedupe_and_filter(barcodes: List[DetectedBarcode]) -> List[DetectedBarcode]:
	# NORMALIZATION DISABLED: Keep first of each barcode type (raw values)
	# Drop exact duplicates and invalid UPC/EAN
	seen: set[tuple[str, str]] = set()
	seen_types: set[str] = set()  # Track types to keep only first of each
	unique: List[DetectedBarcode] = []
	for b in barcodes:
		key = (b.barcode_type, b.barcode_value)
		if key in seen:
			continue  # Skip exact duplicates
		if b.barcode_type in {"EAN-13", "EAN-8", "UPC-A"} and not _is_valid_upcean(b.barcode_type, b.barcode_value):
			continue  # Skip invalid UPC/EAN
		
		# For UPC/EAN types, keep only the FIRST occurrence of each type
		# This ensures we get raw values instead of normalized alternates
		if b.barcode_type in {"UPC-A", "EAN-13", "UPC-E", "EAN-8"}:
			if b.barcode_type in seen_types:
				continue  # Skip subsequent detections of same type
			seen_types.add(b.barcode_type)
		
		seen.add(key)
		unique.append(b)
	return unique


def process_image_to_rows(image: Image.Image, barcodes: List[DetectedBarcode], opts: ProcessOptions) -> List[RowDraft]:
	# Exclude Data Matrix and QR Code at generation time
	barcodes = [b for b in barcodes if b.barcode_type not in {"Data Matrix", "QR Code", "QRCode"}]

	# If only GS1/DataBar present, try OCR to recover a small printed UPC/EAN and prefer it
	has_upcean = any(b.barcode_type in {"UPC-A","UPC-E","EAN-13","EAN-8"} for b in barcodes)
	has_gs1_only = (not has_upcean) and any("DataBar" in (b.barcode_type or "") for b in barcodes)
	if has_gs1_only and opts.ocr:
		gs1_quads = [b.quad for b in barcodes if "DataBar" in (b.barcode_type or "")]
		upc_ocr = ocr_upcean_digit_band(image, quads=gs1_quads) or ocr_upcean_numeric(image, quads=gs1_quads)
		if upc_ocr and (len(upc_ocr) in (12, 13, 8)):
			upc_type = "EAN-13" if len(upc_ocr) == 13 else ("UPC-A" if len(upc_ocr) == 12 else "EAN-8")
			barcodes = [DetectedBarcode(barcode_type=upc_type, barcode_value=upc_ocr, quad=[])]
	# De-duplicate and drop invalid UPC/EAN reads within this image first
	barcodes = _dedupe_and_filter(barcodes)
	# If both Code128 and DataBar are present, prefer Code128 and drop DataBar entries
	has_code128 = any("Code" in (b.barcode_type or "") and "128" in b.barcode_type for b in barcodes)
	has_databar = any("DataBar" in (b.barcode_type or "") for b in barcodes)
	has_upcean_types = any(b.barcode_type in {"UPC-A", "UPC-E", "EAN-13", "EAN-8"} for b in barcodes)
	if has_code128 and has_databar:
		barcodes = [b for b in barcodes if "DataBar" not in (b.barcode_type or "")]
	# If both Code128 and UPC/EAN are present, prefer Code128 (it often encodes the UPC + additional data)
	if has_code128 and has_upcean_types:
		barcodes = [b for b in barcodes if b.barcode_type not in {"UPC-A", "UPC-E", "EAN-13", "EAN-8"}]
	rows: List[RowDraft] = []
	for b in barcodes:
		is_gs1 = _is_gs1_databar(b.barcode_type, b.barcode_value)
		is_price = _is_price_embedded(b.barcode_type, b.barcode_value)
		display_value, gtin = _display_value_for(b)

		name: Optional[str] = None
		notes: Optional[str] = None

		# Price-embedded items: derive name from sticker bold text only; skip web
		if is_price and opts.ocr:
			name = ocr_bold_name(image, b.quad)

		# PLU extraction disabled - not needed for barcode scanning workflow
		# Users should rely on barcode values directly
		# if not name:
		# 	... PLU extraction code removed ...

		# Non-PLU resolution if still no name: ONLY for UPC/EAN types (not Code128/GS1)
		allow_web_for_type = b.barcode_type in ALLOWED_WEB_TYPES
		if not name and allow_web_for_type and not is_price:
			# Try Caper-style normalized candidates first (UPC/EAN resilient lookups)
			# Limit to first 2 candidates for speed (raw + primary normalized variant covers most cases)
			candidates = normalize_candidates(b.barcode_value, b.barcode_type)[:2]
			for cand in candidates:
				if opts.deep_lookup and (opts.serp_key or (opts.cse_id and opts.google_key)) and not name:
					name = deep_lookup_product_name(cand, serpapi_api_key=opts.serp_key, google_cse_id=opts.cse_id, google_api_key=opts.google_key, timeout=2.0)
				if not name and opts.free_lookup:
					name = duckduckgo_lookup(cand, timeout=2.0)
				if not name and opts.lookup:
					name = lookup_product_name(cand, timeout=2.0)
				if name:
					break
			if not name and opts.ocr:
				name = ocr_item_name(image, b.quad)

		name = _validate_name(name, b.barcode_value)
		
		# Add note for price-embedded barcodes
		if is_price:
			notes = "Price-Embedded"
		
		# Add note ONLY for difficult detections (required aggressive fallbacks)
		# Check if detection was difficult by looking at the detection_method
		if opts.mark_uncertain and not notes:
			detection_method = getattr(b, 'detection_method', None)
			# Flag if it required aggressive fallback strategies (double sharp, high contrast, large upscale)
			difficult_indicators = [
				'double', 'Double', 'sharp', 'huge', 'upscale', 
				'enhanced', 'fallback', 'grid', 'crop', 'rotation'
			]
			is_difficult = any(indicator in (detection_method or '') for indicator in difficult_indicators)
			
			if is_difficult:
				notes = "Difficult barcode detection - multiple barcodes may exist, please verify"
		
		rows.append(RowDraft(barcode_type=b.barcode_type, barcode_value=display_value, item_name=name, notes=notes))
	return rows
