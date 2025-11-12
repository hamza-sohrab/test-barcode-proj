from typing import Optional
import requests
import re

RE_SPACES = re.compile(r"\s+")


def _clean_name(name: str) -> str:
	t = RE_SPACES.sub(" ", (name or "")).strip()
	return t


def lookup_product_name(upc: str, timeout: float = 6.0) -> Optional[str]:
	"""Try to resolve a UPC/EAN to a product name using OpenFoodFacts."""
	code = "".join(ch for ch in upc if ch.isdigit())
	if not code:
		return None
	try:
		r = requests.get(f"https://world.openfoodfacts.org/api/v2/product/{code}", timeout=timeout)
		if r.status_code == 200:
			j = r.json()
			prod = j.get("product") or {}
			brand = prod.get("brands") or prod.get("brand_owner") or ""
			name = prod.get("product_name") or prod.get("generic_name") or ""
			full = f"{brand} {name}".strip()
			clean = _clean_name(full or name)
			return clean or None
	except Exception:
		pass
	return None
