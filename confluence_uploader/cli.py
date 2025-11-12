import argparse
import os as _os
import sys as _sys

# Auto-switch to local venv interpreter if heavy deps are missing
def _ensure_local_venv():
	if _os.environ.get("VIRTUAL_ENV"):
		return
	try:
		import zxingcpp  # type: ignore  # noqa: F401
		import cv2  # type: ignore  # noqa: F401
	except Exception:
		_project_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), _os.pardir))
		_venv_python = _os.path.join(_project_root, ".venv", "bin", "python")
		if _os.path.exists(_venv_python):
			_os.execv(_venv_python, [_venv_python, "-m", "confluence_uploader.cli", *_sys.argv[1:]])

_ensure_local_venv()
import io
import os
import getpass
import re
from typing import List, Optional

from dotenv import load_dotenv
from PIL import Image
from tqdm import tqdm

from .image_discovery import discover_images
from .unified_barcode_detector import detect_barcodes_best as detect_barcodes, load_image
from .confluence_client import ConfluenceAuth, ConfluenceClient, infer_page_id_from_url
from .table_builder import Row, build_table, build_rows
from .processor import process_image_to_rows, ProcessOptions
from .models import RowDraft

RE_CODE = re.compile(r"\b\d{8,14}\b")
DEFAULT_BASE_URL = "https://instacart.atlassian.net/wiki"
HEADER_MARKER = "<th><strong>Barcode Type / Category</strong></th>"


def parse_args() -> argparse.Namespace:
	p = argparse.ArgumentParser(description="Upload barcode images to Confluence with a table")
	p.add_argument("--src", required=True, help="Folder or .zip containing images")
	p.add_argument("--page", help="Confluence page URL (extracts page id)")
	p.add_argument("--page-id", help="Confluence page id (overrides --page)")
	# Lookups ON by default; provide --no-* to disable
	p.add_argument("--ocr", dest="ocr", action="store_true", default=True, help="Enable OCR (default: on)")
	p.add_argument("--no-ocr", dest="ocr", action="store_false")
	p.add_argument("--lookup", dest="lookup", action="store_true", default=True, help="Enable OpenFoodFacts lookup (default: on)")
	p.add_argument("--no-lookup", dest="lookup", action="store_false")
	p.add_argument("--deep-lookup", dest="deep_lookup", action="store_true", default=True, help="Enable deep web lookup (default: on)")
	p.add_argument("--no-deep-lookup", dest="deep_lookup", action="store_false")
	p.add_argument("--free-lookup", dest="free_lookup", action="store_true", default=True, help="Enable keyless lookup (default: on)")
	p.add_argument("--no-free-lookup", dest="free_lookup", action="store_false")
	p.add_argument("--plu-all", action="store_true", help="Also parse PLU for non-GS1 barcodes (produce stickers)")
	p.add_argument("--plu-boost", action="store_true", help="Use heavier PLU OCR (slower)")
	p.add_argument("--allow-gs1-web", action="store_true", help="Allow web lookups for GS1/DataBar when PLU missing")
	p.add_argument("--max-size", type=int, default=3200, help="Resize images to this max dimension before barcode detection/upload (default: 3200)")
	p.add_argument("--limit", type=int, default=0, help="Process only first N images")
	p.add_argument("--no-prompt", action="store_true", help="Fail if required settings are missing instead of prompting")
	p.add_argument("--dry-run", action="store_true", help="Do not upload; print results locally for verification")
	p.add_argument("--debug-dumps", help="Directory to save debug scan variants/crops (no upload)")
	p.add_argument("--aggressive", dest="aggressive", action="store_true", default=True, help="Use aggressive scanning (denser grid, higher scaling, extra fallbacks) (default: on)")
	p.add_argument("--no-aggressive", dest="aggressive", action="store_false")
	# Optional manual ROI assist: x,y,w,h; optionally apply only to files whose basename contains filter text
	p.add_argument("--roi", help="Manual ROI crop as x,y,w,h (e.g., 1555,837,370,496)")
	p.add_argument("--roi-filter", help="Apply ROI only to files whose NAME contains this text")
	return p.parse_args()


def _load_env_chain() -> None:
	load_dotenv()
	if os.path.exists(".env.local"):
		load_dotenv(dotenv_path=".env.local", override=True)
	elif os.path.exists("env.local"):
		load_dotenv(dotenv_path="env.local", override=True)


def prompt_if_empty(prompt_text: str, secret: bool = False) -> str:
	while True:
		val = getpass.getpass(prompt_text) if secret else input(prompt_text)
		val = (val or "").strip()
		if val:
			return val
		print("A value is required. Please try again.")


def _persist_credentials(base: str, email: str, token: str) -> None:
	"""Save credentials to env.local in the project root so future runs don't prompt."""
	try:
		project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
		path = os.path.join(project_root, "env.local")
		lines = [
			f"CONFLUENCE_BASE_URL={base}\n",
			f"CONFLUENCE_EMAIL={email}\n",
			f"CONFLUENCE_API_TOKEN={token}\n",
		]
		with open(path, "w") as f:
			f.writelines(lines)
	except Exception:
		# Non-fatal if we can't persist
		pass


def resolve_auth(no_prompt: bool) -> ConfluenceAuth:
	_load_env_chain()
	base = os.environ.get("CONFLUENCE_BASE_URL", DEFAULT_BASE_URL).strip()
	email = os.environ.get("CONFLUENCE_EMAIL", "").strip()
	token = os.environ.get("CONFLUENCE_API_TOKEN", "").strip()
	if base and email and token:
		return ConfluenceAuth(base_url=base, email=email, token=token)
	if no_prompt:
		raise SystemExit("Missing CONFLUENCE_EMAIL or CONFLUENCE_API_TOKEN and --no-prompt was set")
	print("Confluence credentials not found in environment. Please enter them now.")
	# Base URL has a default; no prompt needed unless user wants to override via env
	if not email:
		email = prompt_if_empty("Confluence email: ")
	if not token:
		token = prompt_if_empty("Confluence API token (input hidden): ", secret=True)
	# Persist for subsequent runs
	_persist_credentials(base, email, token)
	return ConfluenceAuth(base_url=base, email=email, token=token)


def resolve_page_id(args: argparse.Namespace) -> str:
	page_id = args.page_id
	if not page_id and args.page:
		page_id = infer_page_id_from_url(args.page or "")
	if not page_id:
		page_id = os.environ.get("CONFLUENCE_PAGE_ID", "").strip()
	if page_id:
		return page_id
	if args.no_prompt:
		raise SystemExit("Provide --page or --page-id or set CONFLUENCE_PAGE_ID; interactive prompts disabled by --no-prompt")
	while True:
		val = input("Confluence page URL or numeric page ID: ").strip()
		if not val:
			print("A value is required. Please try again.")
			continue
		pid = infer_page_id_from_url(val)
		if pid:
			return pid
		if val.isdigit():
			return val
		print("Could not extract page ID from input. Please provide a valid page URL or numeric ID.")


def build_opts(args: argparse.Namespace) -> ProcessOptions:
	_load_env_chain()
	serp = os.environ.get("SERPAPI_API_KEY", "").strip() or None
	cse = os.environ.get("GOOGLE_CSE_ID", "").strip() or None
	gkey = os.environ.get("GOOGLE_API_KEY", "").strip() or None
	return ProcessOptions(
		ocr=args.ocr,
		lookup=args.lookup,
		free_lookup=args.free_lookup,
		deep_lookup=args.deep_lookup,
		plu_all=args.plu_all,
		plu_boost=args.plu_boost,
		allow_gs1_web=args.allow_gs1_web,
		serp_key=serp,
		cse_id=cse,
		google_key=gkey,
	)


def main() -> None:
	args = parse_args()

	client: Optional[ConfluenceClient] = None
	page_id: Optional[str] = None
	existing_html: str = ""
	if not args.dry_run:
		auth = resolve_auth(args.no_prompt)
		client = ConfluenceClient(auth)
		page_id = resolve_page_id(args)
		# Fetch existing page content to de-duplicate by barcode value
		try:
			page = client.get_page(page_id)
			existing_html = page.get("body",{}).get("storage",{}).get("value","") or ""
		except Exception:
			existing_html = ""

	opts = build_opts(args)

	paths = discover_images(args.src)
	if args.limit:
		paths = paths[: args.limit]
	if not paths:
		raise SystemExit("No images found.")

	rows_out: List[Row] = []
	seen_barcodes: set[str] = set()
	seen_image_bases: set[str] = set()  # Track base filenames to dedupe HEIC/JPEG pairs
	for path in tqdm(paths, desc="Scanning images"):
		# Check if this is a duplicate image name (e.g., "item.HEIC" and "item.jpeg")
		base_name = os.path.splitext(os.path.basename(path))[0]
		if base_name in seen_image_bases:
			continue  # Skip duplicate image (different format of same item)
		seen_image_bases.add(base_name)
		
		img = load_image(path)
		# Optional manual ROI assist
		if args.roi:
			try:
				if not args.roi_filter or (os.path.basename(path).find(args.roi_filter) >= 0):
					x, y, w, h = [int(v) for v in args.roi.split(",")]
					# Guard and crop
					px = max(0, x); py = max(0, y)
					img_w, img_h = img.size
					pw = max(1, min(w, img_w - px))
					ph = max(1, min(h, img_h - py))
					img = img.crop((px, py, px + pw, py + ph))
			except Exception:
				pass
		# Use per-image debug subdirectory to avoid overwriting dumps
		per_image_debug = None
		if args.debug_dumps:
			base = os.path.splitext(os.path.basename(path))[0]
			per_image_debug = os.path.join(args.debug_dumps, base)
			try:
				os.makedirs(per_image_debug, exist_ok=True)
			except Exception:
				per_image_debug = args.debug_dumps
		# Don't downscale for barcode detection - use full resolution for best accuracy
		# Only resize for upload to save bandwidth
		barcodes = detect_barcodes(path, max_side=None, preloaded_image=img, debug_dir=per_image_debug, aggressive=args.aggressive)
		if not barcodes:
			continue
		
		# Use only the first/primary barcode from each image (skip multiple barcodes on same item)
		barcodes = [barcodes[0]]
		
		drafts: List[RowDraft] = process_image_to_rows(img, barcodes, opts)
		
		# Page-level and run-level de-duplication by barcode value
		filtered: List[RowDraft] = []
		for d in drafts:
			if d.barcode_value in seen_barcodes:
				continue
			# Page-level exact match: look for <td>value</td>
			if existing_html and d.barcode_value:
				pattern = re.compile(r"<td>\s*" + re.escape(d.barcode_value) + r"\s*</td>")
				if pattern.search(existing_html):
					continue
			filtered.append(d)
		# If nothing new for this image, skip upload
		if not filtered:
			continue
		# Upload once for this image
		attachment_name = os.path.basename(path)
		if client and page_id and not args.dry_run:
			uploaded_name = client.upload_attachment(page_id, attachment_name, _image_bytes(img))
		else:
			uploaded_name = attachment_name
		for d in filtered:
			rows_out.append(
				Row(
					barcode_type=d.barcode_type,
					item_name=d.item_name,
					barcode_value=d.barcode_value,
					attachment_filename=uploaded_name,
					notes=d.notes,
				)
			)
			seen_barcodes.add(d.barcode_value)

	if not rows_out:
		raise SystemExit("No barcodes detected in provided images.")

	if args.dry_run:
		print("DRY RUN RESULTS:")
		for r in rows_out:
			print(f"type={r.barcode_type}\tvalue={r.barcode_value}\tname={r.item_name or ''}\tnotes={r.notes or ''}")
		return

	# Append into existing table if present; else add a new table
	new_rows_html = build_rows(rows_out)
	if existing_html and HEADER_MARKER in existing_html:
		# Find the table with our header and insert before its closing </table>
		head_pos = existing_html.rfind(HEADER_MARKER)
		close_pos = existing_html.find("</table>", head_pos)
		if head_pos != -1 and close_pos != -1:
			new_html = existing_html[:close_pos] + new_rows_html + existing_html[close_pos:]
			client.update_page_storage(page_id, new_html)  # type: ignore[arg-type]
			print(f"Appended {len(rows_out)} rows to existing table on page {page_id}.")
			return

	# Fallback: create a new table
	table_html = build_table(rows_out)
	client.append_storage_to_page(page_id, table_html)  # type: ignore[arg-type]
	print(f"Uploaded {len(rows_out)} barcode rows to page {page_id}.")


def _image_bytes(img: Image.Image) -> bytes:
	buf = io.BytesIO()
	img.save(buf, format="JPEG", quality=85)
	return buf.getvalue()


if __name__ == "__main__":
	main()
