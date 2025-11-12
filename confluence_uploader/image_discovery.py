import os
import tempfile
import zipfile
from typing import Iterable, List

SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif"}


def discover_images(src_path: str) -> List[str]:
	"""Return absolute file paths for images in a folder or a zip archive.

	- If `src_path` is a zip, it is extracted to a temp dir that lives for the process lifetime.
	- Images are returned in sorted order for determinism.
	"""
	abspath = os.path.abspath(src_path)
	if not os.path.exists(abspath):
		raise FileNotFoundError(f"Source path not found: {abspath}")

	# If it's a zip file, extract to temp and scan
	if zipfile.is_zipfile(abspath):
		tmpdir = tempfile.mkdtemp(prefix="barcode_zip_")
		with zipfile.ZipFile(abspath) as zf:
			zf.extractall(tmpdir)
			dir_to_scan = tmpdir
	# If it's a single file and supported, return it directly
	elif os.path.isfile(abspath):
		_root, ext = os.path.splitext(abspath)
		if ext.lower() in SUPPORTED_EXT:
			return [abspath]
		else:
			return []
	else:
		dir_to_scan = abspath

	found: List[str] = []
	for root, _dirs, files in os.walk(dir_to_scan):
		# Skip macOS metadata directories
		if "__MACOSX" in root:
			continue
		
		for name in files:
			# Skip macOS resource fork files (._filename) and hidden files
			if name.startswith("._") or name.startswith("."):
				continue
			
			_, ext = os.path.splitext(name)
			if ext.lower() in SUPPORTED_EXT:
				found.append(os.path.join(root, name))

	return sorted(found)

