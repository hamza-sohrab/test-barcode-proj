from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, UnidentifiedImageError, ImageOps, ImageEnhance, ImageFilter
import numpy as np
import zxingcpp

# Optional fallback deps
try:
	import cv2  # type: ignore
except Exception:
	cv2 = None  # type: ignore
try:
	from pyzbar.pyzbar import decode as zbar_decode  # type: ignore
except Exception:
	zbar_decode = None  # type: ignore

# Register HEIC/HEIF with Pillow if available
try:
	import pillow_heif  # type: ignore
	pillow_heif.register_heif_opener()
except Exception:
	pillow_heif = None  # type: ignore

import os
import sys
import subprocess
import tempfile
import shutil


FRIENDLY_FORMAT = {
	"BarcodeFormat.UPCA": "UPC-A",
	"BarcodeFormat.UPCE": "UPC-E",
	"BarcodeFormat.EAN13": "EAN-13",
	"BarcodeFormat.EAN8": "EAN-8",
	"BarcodeFormat.CODE128": "Code 128",
	"BarcodeFormat.CODE39": "Code 39",
	"BarcodeFormat.ITF": "ITF",
	"BarcodeFormat.QRCode": "QR Code",
	"BarcodeFormat.DataMatrix": "Data Matrix",
	"BarcodeFormat.RSS14": "GS1 DataBar",
	"BarcodeFormat.RSS_EXPANDED": "GS1 DataBar Expanded",
}

ZBAR_FRIENDLY = {
	"CODE128": "Code 128",
	"EAN13": "EAN-13",
	"EAN8": "EAN-8",
	"UPCA": "UPC-A",
	"UPCE": "UPC-E",
}


@dataclass
class DetectedBarcode:
	barcode_type: str
	barcode_value: str
	# Bounding quadrilateral in image coordinates (list of (x,y))
	quad: List[tuple]
	# Optional: detection method used (e.g., "zxing-cpp (aggressive)")
	detection_method: Optional[str] = None


def _open_via_sips(path: str) -> Image.Image:
	"""On macOS, convert HEIC to JPEG via sips and open the result."""
	if sys.platform != "darwin":
		raise UnidentifiedImageError("sips fallback only on macOS")
	if shutil.which("sips") is None:
		raise UnidentifiedImageError("sips not available")
	with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
		tmp_path = tmp.name
	try:
		proc = subprocess.run(["sips", "-s", "format", "jpeg", path, "--out", tmp_path], capture_output=True)
		if proc.returncode != 0 or not os.path.exists(tmp_path):
			raise UnidentifiedImageError(f"sips failed: {proc.stderr.decode(errors='ignore')}")
		img = Image.open(tmp_path).convert("RGB")
		return img
	finally:
		try:
			os.unlink(tmp_path)
		except Exception:
			pass


def load_image(path: str) -> Image.Image:
	try:
		img = Image.open(path)
		return img.convert("RGB")
	except UnidentifiedImageError:
		ext = os.path.splitext(path)[1].lower()
		if ext in (".heic", ".heif"):
			# Fallback to sips conversion on macOS
			return _open_via_sips(path)
		raise


def _extract_quad(position) -> List[tuple]:
	"""Return a list of (x,y) tuples for the barcode corners.

	Handles different zxing-cpp python bindings where `position` may expose
	attributes like top_left/topRight or a `points` sequence.
	"""
	points: List[tuple] = []
	try:
		# Common attribute names across versions
		for names in [
			("top_left", "top_right", "bottom_right", "bottom_left"),
			("topLeft", "topRight", "bottomRight", "bottomLeft"),
		]:
			pts: List[tuple] = []
			for n in names:
				if hasattr(position, n):
					p = getattr(position, n)
					if hasattr(p, "x") and hasattr(p, "y"):
						pts.append((p.x, p.y))
			if pts:
				points = pts
				break
		# Fallback to iterable collection of points
		if not points and hasattr(position, "points"):
			try:
				points = [(p.x, p.y) for p in position.points]  # type: ignore[attr-defined]
			except Exception:
				points = []
	except Exception:
		points = []
	return points


def _friendly_format(fmt_obj) -> str:
	text = str(fmt_obj)
	return FRIENDLY_FORMAT.get(text, text.replace("BarcodeFormat.", "").replace("QRCode", "QR Code"))


def _to_detected(results) -> List[DetectedBarcode]:
	detected: List[DetectedBarcode] = []
	for r in results:
		fmt = _friendly_format(r.format)
		text = r.text or ""
		quad = _extract_quad(getattr(r, "position", None)) if hasattr(r, "position") else []
		if text:
			detected.append(DetectedBarcode(barcode_type=fmt, barcode_value=text, quad=quad))
	return detected


def _read_barcodes_with_opts(arr, formats=None):
    try:
        if formats is not None:
            return zxingcpp.read_barcodes(arr, formats=formats, try_harder=True)
        return zxingcpp.read_barcodes(arr, try_harder=True)
    except TypeError:
        # Older bindings without try_harder
        if formats is not None:
            return zxingcpp.read_barcodes(arr, formats=formats)
        return zxingcpp.read_barcodes(arr)


def _try_decode(img: Image.Image) -> List[DetectedBarcode]:
    arr = np.array(img)
    results = _read_barcodes_with_opts(arr)
    return _to_detected(results)


def _try_decode_formats(img: Image.Image, formats_mask) -> List[DetectedBarcode]:
    arr = np.array(img)
    try:
        results = _read_barcodes_with_opts(arr, formats=formats_mask)
        return _to_detected(results)
    except Exception:
        return []


def _try_decode_with_map(img: Image.Image, offset: Tuple[int,int], scale: float) -> List[DetectedBarcode]:
	arr = np.array(img)
	results = _read_barcodes_with_opts(arr)
	detected: List[DetectedBarcode] = []
	ox, oy = offset
	inv = 1.0 / scale if scale != 0 else 1.0
	for r in results:
		fmt = _friendly_format(r.format)
		text = r.text or ""
		quad_raw = _extract_quad(getattr(r, "position", None)) if hasattr(r, "position") else []
		quad = []
		for x, y in quad_raw:
			qx = ox + int(x * inv)
			qy = oy + int(y * inv)
			quad.append((qx, qy))
		if text:
			detected.append(DetectedBarcode(barcode_type=fmt, barcode_value=text, quad=quad))
	return detected


def _try_decode_with_map_formats(img: Image.Image, offset: Tuple[int,int], scale: float, formats_mask) -> List[DetectedBarcode]:
	arr = np.array(img)
	try:
		results = _read_barcodes_with_opts(arr, formats=formats_mask)
	except Exception:
		return []
	detected: List[DetectedBarcode] = []
	ox, oy = offset
	inv = 1.0 / scale if scale != 0 else 1.0
	for r in results:
		fmt = _friendly_format(r.format)
		text = r.text or ""
		quad_raw = _extract_quad(getattr(r, "position", None)) if hasattr(r, "position") else []
		quad = []
		for x, y in quad_raw:
			qx = ox + int(x * inv)
			qy = oy + int(y * inv)
			quad.append((qx, qy))
		if text:
			detected.append(DetectedBarcode(barcode_type=fmt, barcode_value=text, quad=quad))
	return detected


def _region_boxes(w: int, h: int) -> List[Tuple[int,int,int,int]]:
	"""Generate candidate crop boxes (l,t,r,b) to zoom into likely barcode areas."""
	boxes: List[Tuple[int,int,int,int]] = []
	# Center crop ~70%
	cw, ch = int(w * 0.7), int(h * 0.7)
	cl, ct = (w - cw) // 2, (h - ch) // 2
	boxes.append((cl, ct, cl + cw, ct + ch))
	# Quadrants (~55%)
	qw, qh = int(w * 0.55), int(h * 0.55)
	for xl in (0, w - qw):
		for yt in (0, h - qh):
			boxes.append((xl, yt, xl + qw, yt + qh))
	# Horizontal band center (~60% height)
	hh = int(h * 0.6)
	ht = (h - hh) // 2
	boxes.append((0, ht, w, ht + hh))
	# Vertical band center (~60% width)
	vw = int(w * 0.6)
	vl = (w - vw) // 2
	boxes.append((vl, 0, vl + vw, h))
	return boxes


def _grid_boxes(w: int, h: int, grid: int = 5) -> List[Tuple[int,int,int,int]]:
	boxes: List[Tuple[int,int,int,int]] = []
	cell_w = w // grid
	cell_h = h // grid
	for gy in range(grid):
		for gx in range(grid):
			l = gx * cell_w
			t = gy * cell_h
			r = w if gx == grid - 1 else (gx + 1) * cell_w
			b = h if gy == grid - 1 else (gy + 1) * cell_h
			# expand each cell by 30% to include margins
			exp_x = int((r - l) * 0.3)
			exp_y = int((b - t) * 0.3)
			el = max(0, l - exp_x)
			et = max(0, t - exp_y)
			er = min(w, r + exp_x)
			eb = min(h, b + exp_y)
			if er - el > 40 and eb - et > 40:
				boxes.append((el, et, er, eb))
	return boxes


def _opencv_pyzbar_linear_fallback(img: Image.Image) -> List[DetectedBarcode]:
	"""Try to decode Code128/UPC/EAN using OpenCV preprocessing + ZBar.
	Returns empty list on failure or when dependencies are not available.
	"""
	if cv2 is None or zbar_decode is None:
		return []
	arr = np.array(img)
	gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
	# Enhance contrast and suppress noise
	gray = cv2.convertScaleAbs(gray, alpha=1.4, beta=10)
	gray = cv2.GaussianBlur(gray, (3, 3), 0)
	# Binarize
	th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
	results = zbar_decode(th)
	detected: List[DetectedBarcode] = []
	for r in results:
		fmt = ZBAR_FRIENDLY.get(r.type)
		if not fmt:
			continue
		val = r.data.decode(errors="ignore").strip()
		if not val:
			continue
		# Build quad from rect if available
		quad = []
		try:
			(x, y, w, h) = r.rect
			quad = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
		except Exception:
			quad = []
		detected.append(DetectedBarcode(barcode_type=fmt, barcode_value=val, quad=quad))
	return detected


def _opencv_1d_enhanced(img: Image.Image, debug_dir: Optional[str] = None) -> List[DetectedBarcode]:
    """Enhanced 1D pipeline using gradients + morphology before ZBar.
    Tries 0 and 90-degree orientations.
    """
    if cv2 is None or zbar_decode is None:
        return []
    arr = np.array(img)
    for rot in (0, 90):
        frame = arr
        if rot == 90:
            frame = cv2.rotate(arr, cv2.ROTATE_90_CLOCKWISE)
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        # Emphasize vertical gradients (typical for 1D barcodes)
        gradX = cv2.Sobel(gray, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
        gradX = cv2.convertScaleAbs(gradX)
        # Smooth then threshold
        blurred = cv2.blur(gradX, (9, 9))
        th = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        # Close gaps between bars
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 7))
        closed = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
        closed = cv2.erode(closed, None, iterations=2)
        closed = cv2.dilate(closed, None, iterations=2)
        if debug_dir:
            try:
                tag = f"enhanced_rot{rot}"
                cv2.imwrite(os.path.join(debug_dir, f"{tag}_gradX.png"), gradX)
                cv2.imwrite(os.path.join(debug_dir, f"{tag}_blur.png"), blurred)
                cv2.imwrite(os.path.join(debug_dir, f"{tag}_th.png"), th)
                cv2.imwrite(os.path.join(debug_dir, f"{tag}_closed.png"), closed)
            except Exception:
                pass
        # Decode with ZBar
        results = zbar_decode(closed)
        detected: List[DetectedBarcode] = []
        for r in results:
            fmt = ZBAR_FRIENDLY.get(r.type)
            if not fmt:
                continue
            val = r.data.decode(errors="ignore").strip()
            if not val:
                continue
            detected.append(DetectedBarcode(barcode_type=fmt, barcode_value=val, quad=[]))
        if detected:
            return detected
    return []


def _force_upcean_search(img: Image.Image, debug_dir: Optional[str] = None, aggressive: bool = False) -> List[DetectedBarcode]:
    """Force a UPC/EAN-only search with dense grid and high scaling regardless of earlier results."""
    fmt_mask = (
        zxingcpp.BarcodeFormat.UPCA
        | zxingcpp.BarcodeFormat.UPCE
        | zxingcpp.BarcodeFormat.EAN13
        | zxingcpp.BarcodeFormat.EAN8
    )
    W, H = img.size
    grid_n = 13 if aggressive else 9
    for (l, t, r, b) in _grid_boxes(W, H, grid=grid_n):
        crop = img.crop((l, t, r, b))
        cw, ch = crop.size
        max_dim = max(cw, ch)
        scale = 1.0
        target = 3600.0 if aggressive else 2600.0
        if max_dim < target:
            scale = target / float(max_dim)
            crop = crop.resize((int(cw * scale), int(ch * scale)))
        for rot in (0, 90):
            rot_img = crop.rotate(rot, expand=True)
            if debug_dir:
                try:
                    fname = f"force_upcean_l{l}_t{t}_r{r}_b{b}_rot{rot}.jpg"
                    rot_img.save(os.path.join(debug_dir, fname), format="JPEG", quality=90)
                except Exception:
                    pass
            # Try zxing-cpp first (masked to UPC/EAN)
            res = _try_decode_with_map_formats(rot_img, offset=(l, t), scale=scale, formats_mask=fmt_mask)
            if res:
                return [d for d in res if d.barcode_type in {"UPC-A", "UPC-E", "EAN-13", "EAN-8"}]
            # ZBar fallback on the same crop (helps some small UPCs)
            try:
                import cv2  # type: ignore
                from pyzbar.pyzbar import decode as zbar_decode  # type: ignore
                arr = np.array(rot_img)
                gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                # Mild binarization and sharpen to help ZBar
                th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel)
                zb = zbar_decode(th)
                for r in zb:
                    typ = r.type.upper()
                    if typ not in {"UPCA", "UPCE", "EAN13", "EAN8"}:
                        continue
                    val = r.data.decode(errors="ignore").strip()
                    if not val:
                        continue
                    map_type = {"UPCA": "UPC-A", "UPCE": "UPC-E", "EAN13": "EAN-13", "EAN8": "EAN-8"}[typ]
                    return [DetectedBarcode(barcode_type=map_type, barcode_value=val, quad=[])]
            except Exception:
                pass
    return []


def detect_barcodes(path: str, max_side: Optional[int] = None, preloaded_image: Optional[Image.Image] = None, debug_dir: Optional[str] = None, aggressive: bool = False) -> List[DetectedBarcode]:
	"""Detect barcodes using zxingcpp with multiple transforms/rotations for robustness.

	If preloaded_image is provided, it will be used instead of re-opening the file.
	"""
	img = preloaded_image or load_image(path)
	# Prepare debug directory if requested
	if debug_dir:
		try:
			os.makedirs(debug_dir, exist_ok=True)
		except Exception:
			pass
	# Downscale only if extremely large
	base = img
	if max_side is not None:
		w, h = img.size
		scale = max(w, h) / float(max_side)
		if scale > 1.0:
			new_size = (int(w / scale), int(h / scale))
			base = img.resize(new_size)
	
	# PRE-CHECK: Detect if barcode is vertical, then rotate and scan UPC/EAN
	# This prevents vertical barcodes from being misread as DataBar
	# Step 1: Try quick detection on base image to check orientation
	arr = np.array(base)
	try:
		quick_scan = _read_barcodes_with_opts(arr)
		if quick_scan:
			# Check if barcode is vertical by examining its orientation
			for result in quick_scan:
				if hasattr(result, 'position') and result.position:
					pos = result.position
					# Get the four corner points
					points = [(pos.top_left.x, pos.top_left.y),
					         (pos.top_right.x, pos.top_right.y),
					         (pos.bottom_right.x, pos.bottom_right.y),
					         (pos.bottom_left.x, pos.bottom_left.y)]
					
					# Calculate width and height of bounding box
					xs = [p[0] for p in points]
					ys = [p[1] for p in points]
					width = max(xs) - min(xs)
					height = max(ys) - min(ys)
					
					# If height > width, barcode is vertical
					if height > width * 1.3:  # 30% threshold to account for noise
						# Barcode is vertical - try rotations for UPC/EAN
						upc_formats = (
							zxingcpp.BarcodeFormat.UPCA | zxingcpp.BarcodeFormat.UPCE |
							zxingcpp.BarcodeFormat.EAN13 | zxingcpp.BarcodeFormat.EAN8
						)
						for angle in [90, -90]:
							try:
								rotated = base.rotate(angle, expand=True)
								upc_results = _try_decode_formats(rotated, upc_formats)
								if upc_results:
									for r in upc_results:
										r.detection_method = f"upc-vertical-rotated-{angle}"
									return upc_results
							except Exception:
								pass
						# If rotation didn't help, continue with normal detection
						break
	except Exception:
		pass  # Continue with normal detection if orientation check fails

	variants: List[Image.Image] = []
	variants.append(base)
	# Rotations
	variants.extend([base.rotate(90, expand=True), base.rotate(180, expand=True), base.rotate(270, expand=True)])
	# Grayscale + autocontrast
	gray = ImageOps.autocontrast(base.convert("L")).convert("RGB")
	variants.append(gray)
	# Contrast boosted
	variants.append(ImageEnhance.Contrast(base).enhance(1.6))
	# Sharpened
	variants.append(base.filter(ImageFilter.SHARPEN))

	if debug_dir:
		# Save top-level variants
		try:
			base.save(os.path.join(debug_dir, "00_base.jpg"), format="JPEG", quality=90)
			variants[1].save(os.path.join(debug_dir, "01_rot90.jpg"), format="JPEG", quality=90)
			variants[2].save(os.path.join(debug_dir, "02_rot180.jpg"), format="JPEG", quality=90)
			variants[3].save(os.path.join(debug_dir, "03_rot270.jpg"), format="JPEG", quality=90)
			gray.save(os.path.join(debug_dir, "04_gray.jpg"), format="JPEG", quality=90)
			variants[-2].save(os.path.join(debug_dir, "05_contrast.jpg"), format="JPEG", quality=90)
			variants[-1].save(os.path.join(debug_dir, "06_sharpen.jpg"), format="JPEG", quality=90)
		except Exception:
			pass

	# Optimized aggressive: try only the MOST effective strategies with early stopping
	if aggressive:
		# Strategy 1: Try a few small angle corrections (most effective angles only)
		angles = [-4, 4, -8]  # Reduced from 8 angles to 3 most effective
		for a in angles:
			rot = base.rotate(a, expand=True)
			res = _try_decode(rot)
			if res:
				return res  # Early stop on first success
		
		# Strategy 2: Try upscaled version immediately (often works for small barcodes)
		w, h = base.size
		if max(w, h) < 1800:
			scaled = base.resize((int(w * 2.0), int(h * 2.0)))
			res = _try_decode(scaled)
			if res:
				return res  # Early stop

	for v in variants:
		res = _try_decode(v)
		if res:
			return res

	# As a last resort, upscale smaller images and retry
	w, h = base.size
	if max(w, h) < 1200:
		scaled = base.resize((int(w * (2.2 if aggressive else 1.8)), int(h * (2.2 if aggressive else 1.8))))
		res = _try_decode(scaled)
		if res:
			return res

	# Skip expensive regional boxes - go straight to smart grid if aggressive
	# Only do a minimal 3x3 grid scan for difficult cases
	if aggressive:
		W, H = img.size
		grid_n = 3  # 3x3 = 9 cells total
		for (l, t, r, b) in _grid_boxes(W, H, grid=grid_n):
			crop = img.crop((l, t, r, b))
			cw, ch = crop.size
			max_dim = max(cw, ch)
			scale = 1.0
			if max_dim < 1600:
				scale = 1600.0 / float(max_dim)
				crop = crop.resize((int(cw * scale), int(ch * scale)))
			# Only try 0 rotation for speed (skip 90)
			res = _try_decode_with_map(crop, offset=(l, t), scale=scale)
			if res:
				return res

	# Quick 1D-only fallback on base image only (skip grid for speed)
	try:
		fmt_mask = (zxingcpp.BarcodeFormat.Code128 | zxingcpp.BarcodeFormat.UPCA |
				   zxingcpp.BarcodeFormat.UPCE | zxingcpp.BarcodeFormat.EAN13 |
				   zxingcpp.BarcodeFormat.EAN8)
		res = _try_decode_formats(base, fmt_mask)
		if res:
			return res
	except Exception:
		pass

	# Additional aggressive strategies for difficult barcodes
	if aggressive:
		# Strategy 1: Try UPC/EAN-only formats FIRST (before DataBar)
		# This ensures we don't miss UPCs when both UPC and DataBar exist
		try:
			fmt_mask = (
				zxingcpp.BarcodeFormat.UPCA | zxingcpp.BarcodeFormat.UPCE |
				zxingcpp.BarcodeFormat.EAN13 | zxingcpp.BarcodeFormat.EAN8
			)
			# Try on enhanced contrast
			enhanced = ImageEnhance.Contrast(base).enhance(1.8)
			res = _try_decode_formats(enhanced, fmt_mask)
			if res:
				for r in res:
					r.detection_method = "upc-contrast-enhanced"
				return res
			# Try on upscaled
			w, h = base.size
			if max(w, h) < 2200:
				upscaled = base.resize((int(w * 2.2), int(h * 2.2)))
				res = _try_decode_formats(upscaled, fmt_mask)
				if res:
					for r in res:
						r.detection_method = "upc-upscaled"
					return res
			# Try triple sharpening for difficult UPC barcodes (like through plastic wrap)
			triple_sharp = base.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
			res = _try_decode_formats(triple_sharp, fmt_mask)
			if res:
				for r in res:
					r.detection_method = "upc-triple-sharpened (difficult)"
				return res
		except Exception:
			pass
		
		# Strategy 2: Double sharpening
		double_sharp = base.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
		res = _try_decode(double_sharp)
		if res:
			for r in res:
				r.detection_method = "double-sharpened (difficult)"
			return res
		
		# Strategy 3: High-contrast enhancement
		enhanced = ImageEnhance.Contrast(base).enhance(2.0)
		sharpened = enhanced.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
		res = _try_decode(sharpened)
		if res:
			for r in res:
				r.detection_method = "high-contrast-enhanced (difficult)"
			return res
		
		# Strategy 4: Very high resolution upscale for small barcodes
		w, h = base.size
		if max(w, h) < 2000:
			huge = base.resize((int(w * 2.5), int(h * 2.5)))
			res = _try_decode(huge)
			if res:
				for r in res:
					r.detection_method = "large-upscaled (difficult)"
				return res
		
		# Strategy 5: Code128-specific high resolution (for manager markdowns)
		# Try larger upscale for Code128 only to catch difficult barcodes
		if max(w, h) >= 2000:
			upscaled_for_code128 = base.resize((int(w * 1.5), int(h * 1.5)))
			fmt_mask_code128 = zxingcpp.BarcodeFormat.Code128
			res = _try_decode_formats(upscaled_for_code128, fmt_mask_code128)
			if res:
				for r in res:
					r.detection_method = "code128-large-upscaled (difficult)"
				return res

	# Final fallback: Code128-focused with OpenCV preprocessing (most reliable for difficult Code128)
	# Downscale to max 2400px for speed (this function is very slow on large images)
	if aggressive:
		code128_img = base
		w, h = base.size
		if max(w, h) > 2400:
			scale = 2400.0 / max(w, h)
			code128_img = base.resize((int(w * scale), int(h * scale)))
		
		code128_result = _code128_focused(code128_img, debug_dir, aggressive=True)
		if code128_result:
			for r in code128_result:
				if not hasattr(r, 'detection_method'):
					r.detection_method = "code128-focused-opencv (final fallback)"
			return code128_result

	return []


def _pyzbar_multi_techniques(img: Image.Image, aggressive: bool = False) -> List[DetectedBarcode]:
	"""Run pyzbar across several OpenCV-style pre-processing variants, scales and rotations."""
	if zbar_decode is None:
		return []
	import cv2  # type: ignore
	arr = np.array(img)
	gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if len(arr.shape) == 3 else arr
	# Preprocessing variants
	def contrast_stretch(g):
		mn, mx = np.min(g), np.max(g)
		mx = max(mx, mn + 1)
		return np.uint8(255.0 * (g - mn) / float(mx - mn))
	try:
		clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
	except Exception:
		clahe = gray
	binarized = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
	blurred = cv2.GaussianBlur(gray, (5, 5), 0)
	sharpen_kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
	sharpened = cv2.filter2D(gray, -1, sharpen_kernel)
	contrast = contrast_stretch(gray)
	try:
		adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
	except Exception:
		adaptive = gray
	variants = [gray, binarized, blurred, contrast, cv2.equalizeHist(gray), adaptive, sharpened, clahe]
	# scales and rotations
	scales = [1.0, 0.75]
	angles = [0, 90, 180, 270]
	if aggressive:
		scales = [1.2, 1.0, 0.85, 0.7]
		angles = [0, 90, 180, 270]
	seen: set[tuple[str, str]] = set()
	results: List[DetectedBarcode] = []
	for base in variants:
		for s in scales:
			h, w = base.shape[:2]
			new_w, new_h = max(16, int(w * s)), max(16, int(h * s))
			try:
				resized = cv2.resize(base, (new_w, new_h))
			except Exception:
				continue
			for a in angles:
				if a == 0:
					rot = resized
				else:
					M = cv2.getRotationMatrix2D((new_w / 2, new_h / 2), a, 1.0)
					rot = cv2.warpAffine(resized, M, (new_w, new_h))
				try:
					decoded = zbar_decode(rot)
				except Exception:
					continue
				for r in decoded:
					fmt = ZBAR_FRIENDLY.get(r.type)
					if not fmt:
						continue
					val = r.data.decode(errors="ignore").strip()
					if not val:
						continue
					key = (fmt, val)
					if key in seen:
						continue
					seen.add(key)
					results.append(DetectedBarcode(barcode_type=fmt, barcode_value=val, quad=[]))
	return results


def _code128_focused(img: Image.Image, debug_dir: Optional[str] = None, aggressive: bool = False) -> List[DetectedBarcode]:
    """Targeted Code128 fallback: try color channels + black-hat morphology and decode only Code128.
    
    This is a comprehensive approach that tries multiple preprocessing strategies.
    """
    if zbar_decode is None:
        return []
    try:
        import cv2  # type: ignore
        from pyzbar.pyzbar import ZBarSymbol  # type: ignore
    except Exception:
        return []

    arr = np.array(img)
    channels: List[np.ndarray] = []
    if len(arr.shape) == 3:
        b, g, r = cv2.split(arr)
        channels.extend([r, g, b])
        try:
            hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
            h, s, v = cv2.split(hsv)
            channels.append(v)
        except Exception:
            pass
    else:
        channels.append(arr)

    # Optimized combinations: comprehensive enough for reliability, ordered by effectiveness
    scales = [1.8, 1.5, 1.2] if aggressive else [1.4]  # Cover range, 1.8 often most effective
    kernels = [(31, 5)]  # Single most effective kernel size
    angles = [0, -3, 3, -6, 6, -9, 9] if aggressive else [0]  # Common skew angles

    for ch in channels:
        # Normalize contrast
        try:
            ch = cv2.equalizeHist(ch)
        except Exception:
            pass
        
        for sx, sy in kernels:
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (sx, sy))
            try:
                blackhat = cv2.morphologyEx(ch, cv2.MORPH_BLACKHAT, kernel)
            except Exception:
                blackhat = ch
            
            # Light blur and binarize
            bh = cv2.GaussianBlur(blackhat, (3, 3), 0)
            th = cv2.threshold(bh, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            
            for inv in (False, True):
                img_bin = cv2.bitwise_not(th) if inv else th
                for s in scales:
                    h, w = img_bin.shape[:2]
                    new_w, new_h = max(48, int(w * s)), max(48, int(h * s))
                    try:
                        cand = cv2.resize(img_bin, (new_w, new_h))
                    except Exception:
                        cand = img_bin
                    
                    for ang in angles:
                        if ang != 0:
                            M = cv2.getRotationMatrix2D((new_w / 2, new_h / 2), ang, 1.0)
                            rot_img = cv2.warpAffine(cand, M, (new_w, new_h))
                        else:
                            rot_img = cand
                        
                        # Decode with pyzbar Code128-only (no DataBar warnings)
                        try:
                            decoded = zbar_decode(rot_img, symbols=[ZBarSymbol.CODE128])
                        except Exception:
                            decoded = []
                        
                        for r in decoded:
                            if r.type == "CODE128":
                                val = r.data.decode(errors="ignore").strip()
                                if val and len(val) > 10:
                                    return [DetectedBarcode(barcode_type="Code 128", barcode_value=val, quad=[])]
    
    return []
