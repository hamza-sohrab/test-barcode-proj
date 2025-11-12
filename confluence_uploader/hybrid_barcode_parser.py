"""
Hybrid Barcode Parser
Combines:
1. Aggressive detection strategies from Barcode_Scanner_App (colleague's project)
2. Production-grade normalization from caper-repo
3. Confluence workflow compatibility

This is the best-of-both-worlds implementation.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, UnidentifiedImageError
import numpy as np
import cv2
import os
import sys
import subprocess
import tempfile
import shutil

# Optional: pyzbar for barcode detection (not required for identify_item_type)
try:
    from pyzbar.pyzbar import decode as zbar_decode
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False
    zbar_decode = None

# Register HEIC/HEIF with Pillow if available
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False


@dataclass
class DetectedBarcode:
    barcode_type: str
    barcode_value: str
    quad: List[tuple]  # Bounding quadrilateral [(x,y), ...]
    detection_method: Optional[str] = None


# Map ZBar barcode type names to friendly names
ZBAR_FRIENDLY = {
    "CODE128": "Code 128",
    "EAN13": "EAN-13",
    "EAN8": "EAN-8",
    "UPCA": "UPC-A",
    "UPCE": "UPC-E",
    "CODE39": "Code 39",
    "ITF14": "ITF",
    "I25": "ITF",
    "DATABAR": "GS1 DataBar",
    "DATABAR_EXP": "GS1 DataBar Expanded",
    "QRCODE": "QR Code",
}


def _open_via_sips(path: str) -> Image.Image:
    """On macOS, convert HEIC to JPEG via sips and open the result."""
    if sys.platform != "darwin":
        raise UnidentifiedImageError("sips fallback only on macOS")
    if shutil.which("sips") is None:
        raise UnidentifiedImageError("sips not available")
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            ["sips", "-s", "format", "jpeg", path, "--out", tmp_path],
            capture_output=True
        )
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
    """Load image with HEIC support."""
    try:
        img = Image.open(path)
        return img.convert("RGB")
    except UnidentifiedImageError:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".heic", ".heif"):
            return _open_via_sips(path)
        raise


def _scan_image_aggressive(image: np.ndarray) -> List[DetectedBarcode]:
    """
    Aggressive barcode detection using colleague's proven strategies.
    Combines 8 preprocessing techniques + rotations with early stopping.
    """
    original_image = image.copy()
    results = []
    found_barcodes = set()  # Track (type, value) to avoid duplicates
    
    # Convert to grayscale
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image.copy()
    
    height, width = gray.shape
    
    # Detection techniques ordered by speed/effectiveness (from colleague's analysis)
    detection_techniques = [
        {
            "name": "original",
            "image": gray,
            "description": "Original grayscale",
            "scales": [1.0, 0.75]
        },
        {
            "name": "binarized",
            "image": cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1],
            "description": "Otsu thresholding",
            "scales": [1.0]
        },
        {
            "name": "blurred",
            "image": cv2.GaussianBlur(gray, (5, 5), 0),
            "description": "Gaussian blur",
            "scales": [1.0]
        },
        {
            "name": "contrast_stretch",
            "image": np.uint8(255.0 * (gray - np.min(gray)) / max(1, np.max(gray) - np.min(gray))),
            "description": "Contrast stretching",
            "scales": [1.0]
        },
        {
            "name": "hist_eq",
            "image": cv2.equalizeHist(gray),
            "description": "Histogram equalization",
            "scales": [1.0]
        },
        {
            "name": "adaptive",
            "image": cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2),
            "description": "Adaptive thresholding",
            "scales": [1.0]
        },
        {
            "name": "sharpened",
            "image": cv2.filter2D(gray, -1, np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])),
            "description": "Sharpening",
            "scales": [1.0]
        },
        {
            "name": "clahe",
            "image": cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8)).apply(gray),
            "description": "CLAHE",
            "scales": [1.0]
        }
    ]
    
    # Prioritize standard orientation, use rotations only if needed
    angles = [0, 90, 180, 270]
    
    # Process each technique until we find a barcode (early stopping)
    for technique in detection_techniques:
        if results:  # Early exit if barcode found
            break
        
        scales = technique.get("scales", [1.0])
        
        for scale in scales:
            if results:  # Early exit
                break
            
            # Calculate new dimensions
            new_height = int(height * scale)
            new_width = int(width * scale)
            
            if new_height <= 10 or new_width <= 10:
                continue
            
            # Resize image
            try:
                resized = cv2.resize(technique["image"], (new_width, new_height))
            except Exception:
                continue
            
            # Try different rotations
            for angle in angles:
                if results:  # Early exit
                    break
                
                # Rotate if needed
                if angle != 0:
                    try:
                        rotation_matrix = cv2.getRotationMatrix2D(
                            (new_width/2, new_height/2), angle, 1.0
                        )
                        rotated = cv2.warpAffine(resized, rotation_matrix, (new_width, new_height))
                    except Exception:
                        continue
                else:
                    rotated = resized
                
                # Apply barcode detection with pyzbar
                try:
                    barcodes = zbar_decode(rotated)
                    
                    if barcodes:
                        for barcode in barcodes:
                            try:
                                barcode_value = barcode.data.decode('utf-8')
                                barcode_type = ZBAR_FRIENDLY.get(barcode.type, barcode.type)
                                
                                # Skip duplicates
                                key = (barcode_type, barcode_value)
                                if key in found_barcodes:
                                    continue
                                
                                found_barcodes.add(key)
                                
                                # Extract quad if available
                                quad = []
                                try:
                                    (x, y, w, h) = barcode.rect
                                    quad = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                                except Exception:
                                    quad = []
                                
                                results.append(DetectedBarcode(
                                    barcode_type=barcode_type,
                                    barcode_value=barcode_value,
                                    quad=quad,
                                    detection_method=f"{technique['name']} (scale={scale}, angle={angle})"
                                ))
                            except Exception:
                                continue
                except Exception:
                    continue
    
    # Try specialized QR code detection only if no barcodes found
    if not results:
        try:
            qr_detector = cv2.QRCodeDetector()
            val, pts, qr_code = qr_detector.detectAndDecode(gray)
            
            if val:
                key = ("QR Code", val)
                if key not in found_barcodes:
                    results.append(DetectedBarcode(
                        barcode_type="QR Code",
                        barcode_value=val,
                        quad=[],
                        detection_method="OpenCV QR Detector"
                    ))
        except Exception:
            pass
    
    return results


def detect_barcodes(
    path: str,
    max_side: Optional[int] = None,
    preloaded_image: Optional[Image.Image] = None
) -> List[DetectedBarcode]:
    """
    Detect barcodes using aggressive multi-strategy approach.
    
    Args:
        path: Path to image file
        max_side: Optional max dimension for downscaling
        preloaded_image: Optional pre-loaded PIL image
    
    Returns:
        List of detected barcodes
    """
    # Load image
    if preloaded_image:
        img = preloaded_image
    else:
        img = load_image(path)
    
    # Downscale if needed
    if max_side is not None:
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
    
    # Convert to numpy array for OpenCV
    img_array = np.array(img)
    
    # Use aggressive detection
    results = _scan_image_aggressive(img_array)
    
    return results


def identify_item_type(barcode_value: str, barcode_type: str) -> Optional[str]:
    """
    Identify item type based on barcode (from colleague's implementation).
    Returns: "Produce", "Price-Embedded", "Manager Markdown", or "Generic"
    """
    import re
    
    clean_barcode = re.sub(r'[^0-9a-zA-Z]', '', barcode_value)
    
    # GS1 DataBar = Produce
    if barcode_type == "GS1 DataBar":
        return "Produce"
    
    # CODE128 Manager Markdowns
    if barcode_type == "Code 128" and clean_barcode.startswith('01') and len(clean_barcode) > 14:
        return "Manager Markdown"
    
    # Price-embedded patterns
    PRICE_EMBEDDED_PATTERNS = {
        '2': {  # EAN-13 format
            'length': 13,
            'price_start': 6,
            'price_end': 11,
            'price_divisor': 100
        }
    }
    
    if barcode_type in ("EAN-13", "UPC-A"):
        for prefix, pattern in PRICE_EMBEDDED_PATTERNS.items():
            if clean_barcode.startswith(prefix) and len(clean_barcode) == pattern['length']:
                try:
                    price_digits = clean_barcode[pattern['price_start']:pattern['price_end']]
                    price = int(price_digits) / pattern['price_divisor']
                    if 0 < price < 1000:
                        return f"Price-Embedded (${price:.2f})"
                except Exception:
                    continue
    
    # PLU codes
    if re.match(r'^[3-9]\d{3}$', clean_barcode):  # 4-digit PLU
        return "Produce"
    if re.match(r'^(83|84|94)\d{3}$', clean_barcode):  # 5-digit PLU
        return "Produce"
    
    return "Generic"
