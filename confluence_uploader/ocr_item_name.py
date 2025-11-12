from typing import Optional, Tuple, List, Dict

from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import re

try:
	import pytesseract  # type: ignore
except Exception:  # pragma: no cover
	pytesseract = None  # type: ignore

PLU_RE = re.compile(r"\b(\d{4,5})\b")
PLU_WORD_RE = re.compile(r"PLU\s*(\d{4,5})", re.I)
ALPHA_RE = re.compile(r"[A-Za-z]{3,}")


def _crop_above_barcode(image: Image.Image, quad: list, pad_ratio: float = 0.25) -> Image.Image:
	# quad is list of (x,y) tuples for corners; approximate bbox
	xs = [p[0] for p in quad] if quad else [0, image.width]
	ys = [p[1] for p in quad] if quad else [image.height // 2, image.height]
	x0, x1 = max(0, int(min(xs))), min(image.width, int(max(xs)))
	y0, y1 = max(0, int(min(ys))), min(image.height, int(max(ys)))

	bbox_height = max(1, y1 - y0)
	pad = int(bbox_height * pad_ratio)
	crop_top = max(0, y0 - (bbox_height + pad))
	crop_bottom = max(0, y0 - 1)
	if crop_bottom <= crop_top:
		crop_top = max(0, y0 - bbox_height)
		crop_bottom = y0

	return image.crop((x0, crop_top, x1, crop_bottom))


def _regions_around_barcode(image: Image.Image, quad: list) -> List[Tuple[int,int,int,int]]:
	w, h = image.size
	regions: List[Tuple[int,int,int,int]] = []
	if quad:
		xs = [p[0] for p in quad]
		ys = [p[1] for p in quad]
		x0, x1 = max(0, int(min(xs))), min(w, int(max(xs)))
		y0, y1 = max(0, int(min(ys))), min(h, int(max(ys)))
		height = max(1, y1 - y0)
		width = max(1, x1 - x0)
		pad_y = int(height * 1.0)
		pad_x = int(width * 1.0)
		# Above / below bands
		regions.append((max(0, x0 - pad_x//2), max(0, y0 - pad_y), min(w, x1 + pad_x//2), max(0, y0)))
		regions.append((max(0, x0 - pad_x//2), min(h, y1), min(w, x1 + pad_x//2), min(h, y1 + pad_y)))
		# Left / right bands
		regions.append((max(0, x0 - pad_x), max(0, y0 - pad_y//4), max(0, x0), min(h, y1 + pad_y//4)))
		regions.append((min(w, x1), max(0, y0 - pad_y//4), min(w, x1 + pad_x), min(h, y1 + pad_y//4)))
	else:
		# Prioritize center cell first, then remaining 8 grid cells
		gw, gh = w // 3, h // 3
		center = (w//3, h//3, 2*w//3, 2*h//3)
		regions.append(center)
		for gy in range(3):
			for gx in range(3):
				l = gx * gw
				t = gy * gh
				r = w if gx == 2 else (gx + 1) * gw
				b = h if gy == 2 else (gy + 1) * gh
				box = (l, t, r, b)
				if box != center:
					regions.append(box)
		# Edge bands
		band = max(30, min(w, h) // 8)
		regions.append((0, 0, w, band))             # top
		regions.append((0, h - band, w, h))         # bottom
		regions.append((0, 0, band, h))             # left
		regions.append((w - band, 0, w, h))         # right
	# Top half and full image as coarse fallbacks
	regions.append((0, 0, w, h // 2))
	regions.append((0, 0, w, h))
	# Deduplicate invalid/empty
	uniq: List[Tuple[int,int,int,int]] = []
	for box in regions:
		l,t,r,b = box
		if r-l > 20 and b-t > 20 and box not in uniq:
			uniq.append(box)
	return uniq


def _preprocess_variants(im: Image.Image) -> List[Image.Image]:
	v: List[Image.Image] = []
	# Base
	v.append(im)
	# Upscale variants
	v.append(im.resize((int(im.width * 1.5), int(im.height * 1.5))))
	# Grayscale autocontrast
	g = ImageOps.autocontrast(im.convert("L"))
	v.append(g)
	# Threshold variants
	for thr in (120, 150, 180):
		v.append(g.point(lambda x, t=thr: 255 if x > t else 0))
		v.append(ImageOps.invert(g.point(lambda x, t=thr: 255 if x > t else 0)))
	# Sharpen/contrast
	v.append(im.filter(ImageFilter.SHARPEN))
	v.append(ImageEnhance.Contrast(im).enhance(1.8))
	return v


def ocr_item_name(image: Image.Image, quad: list) -> Optional[str]:
	"""Attempt to OCR text above the barcode. Returns None if OCR not available or low-confidence."""
	if pytesseract is None:
		return None
	crop = _crop_above_barcode(image, quad)
	if crop.height <= 5 or crop.width <= 5:
		return None
	try:
		text = pytesseract.image_to_string(crop, config="--psm 6")
		text = (text or "").strip()
		for line in text.splitlines():
			candidate = line.strip()
			if len(candidate) >= 4:
				return candidate
		return None
	except Exception:
		return None


def ocr_plu_code(image: Image.Image, quad: list) -> Optional[str]:
	"""Try to OCR a 4-5 digit PLU code from text above the barcode."""
	if pytesseract is None:
		return None
	crop = _crop_above_barcode(image, quad)
	if crop.height <= 5 or crop.width <= 5:
		return None
	try:
		text = pytesseract.image_to_string(crop, config="--psm 6 digits")
		text = (text or "").strip()
		m = PLU_WORD_RE.search(text) or PLU_RE.search(text)
		if m:
			return m.group(1)
		return None
	except Exception:
		return None


def ocr_plu_code_fallback(image: Image.Image) -> Optional[str]:
	"""Fallback: scan larger regions to find a 4-5 digit PLU anywhere in the image."""
	if pytesseract is None:
		return None
	try:
		w, h = image.size
		regions = [
			(0, 0, w, h // 2),  # top half
			(0, 0, w, h),       # full image
		]
		for box in regions:
			crop = image.crop(box)
			text = pytesseract.image_to_string(crop, config="--psm 6")
			text = (text or "").strip()
			m = PLU_WORD_RE.search(text) or PLU_RE.search(text)
			if m:
				return m.group(1)
		return None
	except Exception:
		return None


def ocr_plu_code_boost(image: Image.Image, quad: list) -> Optional[str]:
	"""Aggressive PLU OCR: scan multiple regions around barcode with digit-only configs and preprocessing."""
	if pytesseract is None:
		return None
	regions = _regions_around_barcode(image, quad)
	for box in regions:
		crop = image.crop(box)
		for variant in _preprocess_variants(crop):
			for cfg in (
				"--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789 -c classify_bln_numeric_mode=1",
				"--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789",
				"--oem 1 --psm 8 -c tessedit_char_whitelist=0123456789",
			):
				try:
					text = pytesseract.image_to_string(variant, config=cfg) or ""
					m = PLU_WORD_RE.search(text) or PLU_RE.search(text)
					if m:
						return m.group(1)
				except Exception:
					continue
	return None


def ocr_bold_name(image: Image.Image, quad: list) -> Optional[str]:
	"""Heuristic: prefer bold-looking lines by analyzing Tesseract word boxes and binarized density.
	Returns None if extracted line fails quality checks (to avoid gibberish)."""
	if pytesseract is None:
		return None
	best_line: Optional[str] = None
	best_score = -1.0
	for box in _regions_around_barcode(image, quad):
		crop = image.crop(box)
		try:
			data = pytesseract.image_to_data(crop, output_type=pytesseract.Output.DICT, config="--psm 6")
		except Exception:
			continue
		n = len(data.get("text", []))
		if n == 0:
			continue
		# Aggregate by (block_num, par_num, line_num)
		groups: Dict[Tuple[int,int,int], List[int]] = {}
		for i in range(n):
			if int(data.get("conf", ["-1"])[i]) < 0:
				continue
			text = (data["text"][i] or "").strip()
			if not text:
				continue
			key = (data.get("block_num", [0])[i], data.get("par_num", [0])[i], data.get("line_num", [0])[i])
			groups.setdefault(key, []).append(i)
		for key, idxs in groups.items():
			# Build line text and compute boldness score
			line_text = " ".join((data["text"][j] or "").strip() for j in idxs)
			if not ALPHA_RE.search(line_text):
				continue
			# Compute density: threshold grayscale and compute dark pixel ratio inside the union bbox
			x0 = min(data["left"][j] for j in idxs)
			y0 = min(data["top"][j] for j in idxs)
			x1 = max(data["left"][j] + data["width"][j] for j in idxs)
			y1 = max(data["top"][j] + data["height"][j] for j in idxs)
			sub = ImageOps.autocontrast(crop.convert("L")).crop((x0, y0, x1, y1))
			thr = sub.point(lambda x: 0 if x > 150 else 1)
			dark_ratio = sum(thr.getdata()) / float(max(1, thr.width * thr.height))
			score = dark_ratio * thr.height
			if score > best_score:
				best_score = score
				best_line = line_text
	# Quality gate for best_line
	if not best_line:
		return None
	line = best_line.strip()
	# Length bounds
	if len(line) < 4 or len(line) > 64:
		return None
	alpha = sum(ch.isalpha() for ch in line)
	total = sum(ch.isalnum() for ch in line)
	if total == 0:
		return None
	alpha_ratio = alpha / float(total)
	if alpha_ratio < 0.6:
		return None
	# Average word length
	words = [w for w in re.split(r"\s+", line) if w]
	avg_len = sum(len(w) for w in words) / float(len(words)) if words else 0
	if avg_len < 3:
		return None
	return line

