from typing import Optional, List
import re
import requests
from urllib.parse import urlparse

RE_UPC_ONLY = re.compile(r"\b\d{8,14}\b")
RE_WORD = re.compile(r"[A-Za-z]{3,}")
PREFERRED_DOMAINS = (
	"walmart.com",
	"target.com",
	"amazon.com",
	"instacart.com",
	"costco.com",
	"kroger.com",
	"heb.com",
	"samsclub.com",
	"albertsons.com",
	"wholefoodsmarket.com",
)


def _clean_title(title: str) -> str:
	t = re.sub(r"<.*?>", "", title or "")
	t = re.sub(r"\s*[|\-–~»·:]+\s*.*$", "", t).strip()
	return t


def _looks_like_product(title: str) -> bool:
	if not title or len(title) < 4:
		return False
	if RE_UPC_ONLY.search(title):
		return False
	return bool(RE_WORD.search(title))


def _score_result(title: str, link: Optional[str]) -> int:
	score = 0
	if link:
		host = urlparse(link).netloc.lower()
		if any(dom in host for dom in PREFERRED_DOMAINS):
			score += 3
	score += min(len(title) // 10, 4)
	return score


def deep_lookup_product_name(upc: str, serpapi_api_key: Optional[str] = None,
							  google_cse_id: Optional[str] = None,
							  google_api_key: Optional[str] = None,
							  timeout: float = 8.0) -> Optional[str]:
	code = "".join(ch for ch in upc if ch.isdigit())
	if not code:
		return None

	queries: List[str] = [
		f"{code}",
		f"UPC {code}",
		f"barcode {code}",
		f"product {code}",
	]
	return deep_lookup_queries(queries, serpapi_api_key=serpapi_api_key, google_cse_id=google_cse_id, google_api_key=google_api_key, timeout=timeout)


def deep_lookup_queries(queries: List[str], serpapi_api_key: Optional[str] = None,
						 google_cse_id: Optional[str] = None,
						 google_api_key: Optional[str] = None,
						 timeout: float = 8.0) -> Optional[str]:
	best_title: Optional[str] = None
	best_score = -1

	# 1) SerpAPI
	if serpapi_api_key:
		for q in queries:
			try:
				r = requests.get(
					"https://serpapi.com/search.json",
					params={"engine": "google", "q": q, "api_key": serpapi_api_key},
					timeout=timeout,
				)
				if r.status_code == 200:
					j = r.json()
					for item in j.get("organic_results", []):
						title = _clean_title(item.get("title") or "")
						link = item.get("link")
						if not _looks_like_product(title):
							continue
						s = _score_result(title, link)
						if s > best_score:
							best_score = s
							best_title = title
			except Exception:
				pass
		if best_title:
			return best_title

	# 2) Google CSE
	if google_api_key and google_cse_id:
		for q in queries:
			try:
				r = requests.get(
					"https://www.googleapis.com/customsearch/v1",
					params={"key": google_api_key, "cx": google_cse_id, "q": q},
					timeout=timeout,
				)
				if r.status_code == 200:
					j = r.json()
					for item in j.get("items", []) or []:
						title = _clean_title(item.get("title") or "")
						link = item.get("link")
						if not _looks_like_product(title):
							continue
						s = _score_result(title, link)
						if s > best_score:
							best_score = s
							best_title = title
			except Exception:
				pass
		if best_title:
			return best_title

	return None
