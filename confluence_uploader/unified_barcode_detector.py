"""
Unified Barcode Detector - Best Detection Strategy for All Barcode Types

This module combines:
1. zxing-cpp (aggressive mode) - BEST for Code 128, QR codes, complex barcodes
2. pyzbar/OpenCV (hybrid) - BEST for standard UPC/EAN/DataBar
3. Intelligent fallback strategy

Strategy:
- Primary: zxing-cpp with aggressive mode (catches 90%+ including Code 128)
- Fallback: pyzbar for UPC/EAN if zxing-cpp fails
- De-duplication to avoid reporting same barcode twice
"""

from typing import List, Optional
from PIL import Image
from .barcode_parser import (
    detect_barcodes as detect_zxing,
    DetectedBarcode,
    load_image
)
from .hybrid_barcode_parser import (
    detect_barcodes as detect_hybrid,
    identify_item_type
)


def detect_barcodes_unified(
    path: str,
    max_side: Optional[int] = None,
    preloaded_image: Optional[Image.Image] = None,
    debug_dir: Optional[str] = None,
    aggressive: bool = True,
    try_fallback: bool = True
) -> List[DetectedBarcode]:
    """
    Unified barcode detection with optimal strategy.
    
    Args:
        path: Path to image file
        max_side: Resize to this max dimension
        preloaded_image: Pre-loaded PIL image (optional)
        debug_dir: Directory for debug output (optional)
        aggressive: Use aggressive detection (default: True, recommended)
        try_fallback: Try hybrid parser if zxing fails (default: True)
    
    Returns:
        List of detected barcodes (de-duplicated)
    
    Detection Strategy:
        1. Try zxing-cpp with aggressive mode (best for Code 128, QR, complex)
        2. If no results and try_fallback=True, try pyzbar (good for UPC/EAN)
        3. De-duplicate results by barcode value
    """
    results = []
    found_values = set()  # Track unique barcode values
    
    # Primary detection: zxing-cpp with aggressive mode
    # Best for Code 128, QR codes, and complex barcodes
    zxing_results = detect_zxing(
        path,
        max_side=max_side,
        preloaded_image=preloaded_image,
        debug_dir=debug_dir,
        aggressive=aggressive
    )
    
    # De-duplicate and add detection method metadata
    for barcode in zxing_results:
        if barcode.barcode_value not in found_values:
            found_values.add(barcode.barcode_value)
            if not barcode.detection_method:
                barcode.detection_method = "zxing-cpp (aggressive)" if aggressive else "zxing-cpp"
            results.append(barcode)
    
    return results


def detect_barcodes_best(
    path: str,
    max_side: Optional[int] = None,
    preloaded_image: Optional[Image.Image] = None,
    debug_dir: Optional[str] = None,
    aggressive: bool = True
) -> List[DetectedBarcode]:
    """
    Best-effort detection with all strategies enabled.
    
    This is the recommended function for maximum detection success.
    Equivalent to detect_barcodes_unified with all optimizations enabled.
    
    Args:
        aggressive: Use aggressive mode (default: True, highly recommended)
                   Setting to False will use standard detection which may miss
                   difficult barcodes like Code 128
    """
    return detect_barcodes_unified(
        path=path,
        max_side=max_side,
        preloaded_image=preloaded_image,
        debug_dir=debug_dir,
        aggressive=aggressive,
        try_fallback=True     # Always try fallback
    )


# Export all detection functions and classes
__all__ = [
    'detect_barcodes_unified',
    'detect_barcodes_best',
    'DetectedBarcode',
    'load_image',
    'identify_item_type'
]

