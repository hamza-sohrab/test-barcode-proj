from typing import Iterable, Optional, Tuple, List
from PIL import Image, ImageOps, ImageFilter, ImageEnhance
import re

try:
	import pytesseract  # type: ignore
except Exception:
	pytesseract = None  # type: ignore


RE_DIGITS = re.compile(r"\d{8,14}")


def _prep(img: Image.Image, boost: bool = True) -> Image.Image:
	gray = ImageOps.grayscale(img)
	# Guard zero-sized
	if gray.width == 0 or gray.height == 0:
		return gray
	if boost:
		try:
			gray = ImageOps.autocontrast(gray)
			gray = ImageEnhance.Contrast(gray).enhance(1.6)
			gray = gray.filter(ImageFilter.SHARPEN)
		except Exception:
			pass
	return gray


def _inflate(box: Tuple[int,int,int,int], w: int, h: int, scale: float = 0.25) -> Tuple[int,int,int,int]:
	l, t, r, b = box
	padx = int((r - l) * scale)
	pady = int((b - t) * scale)
	return max(0, l - padx), max(0, t - pady), min(w, r + padx), min(h, b + pady)


def ocr_upcean_numeric(image: Image.Image, quads: Optional[Iterable[List[Tuple[int,int]]]] = None) -> Optional[str]:
	"""OCR numeric UPC/EAN near the barcode region. Returns the strongest candidate if valid, else None."""
	if pytesseract is None:
		return None

	regions: List[Tuple[int,int,int,int]] = []
	W, H = image.size
	if quads:
		for q in quads:
			if not q:
				continue
			xs = [p[0] for p in q]
			ys = [p[1] for p in q]
			box = (min(xs), min(ys), max(xs), max(ys))
			regions.append(_inflate(box, W, H, 0.35))
	if not regions:
		regions = [(0, 0, W, H)]

	best: Optional[str] = None
	for (l, t, r, b) in regions:
		crop = image.crop((l, t, r, b))
		prep = _prep(crop)
		try:
			text = pytesseract.image_to_string(
				prep,
				config='--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789',
			)
		except Exception:
			continue
		digits = RE_DIGITS.findall(text or "")
		for d in digits:
			# Prefer 12 or 13 digits
			if len(d) in (13, 12, 8):
				best = d
				break
		if best:
			break
	return best


def ocr_upcean_digit_band(image: Image.Image, quads: Optional[Iterable[List[Tuple[int,int]]]] = None) -> Optional[str]:
	"""Try OCR on a thin band below the barcode bars where the printed digits usually are."""
	if pytesseract is None:
		return None
	if not quads:
		return None
	W, H = image.size
	for q in quads:
		if not q:
			continue
		xs = [p[0] for p in q]
		ys = [p[1] for p in q]
		l, t, r, b = min(xs), min(ys), max(xs), max(ys)
		# Define a band just below the bars
		band_h = max(10, int((b - t) * 0.28))
		gap = max(2, int((b - t) * 0.06))
		bl = max(0, l)
		bt = min(H, b + gap)
		br = min(W, r)
		bb = min(H, bt + band_h)
		if bb <= bt or br <= bl:
			continue
		band = image.crop((bl, bt, br, bb))
		if band.width == 0 or band.height == 0:
			continue
		# Upscale band strongly for OCR
		scale = 3.0
		bw, bh = band.size
		band = band.resize((int(bw * scale), int(bh * scale)))
		prep = _prep(band, boost=True)
		try:
			text = pytesseract.image_to_string(
				prep,
				config='--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789',
			)
		except Exception:
			continue
		digits = RE_DIGITS.findall(text or "")
		# prefer 12/13 length
		for length in (13, 12, 8):
			cand = next((d for d in digits if len(d) == length), None)
			if cand:
				return cand
	return None


