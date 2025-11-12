from typing import Optional, List, Tuple
import requests
import re
from urllib.parse import urlparse

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
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


def _clean(text: str) -> str:
	t = re.sub(r"<.*?>", "", text)
	t = re.sub(r"\s*[|\-–~»·:]+\s*.*$", "", t).strip()
	return t


def _valid_title(title: str) -> bool:
	if not title or len(title) < 4:
		return False
	if RE_UPC_ONLY.search(title):
		return False
	return bool(RE_WORD.search(title))


def _score(title: str, link: Optional[str]) -> int:
	s = 0
	if link:
		host = urlparse(link).netloc.lower()
		if any(dom in host for dom in PREFERRED_DOMAINS):
			s += 3
	s += min(len(title) // 10, 4)
	return s


def duckduckgo_lookup(upc: str, timeout: float = 8.0) -> Optional[str]:
	code = "".join(ch for ch in upc if ch.isdigit())
	if not code:
		return None
	queries = [f"{code}", f"UPC {code}", f"barcode {code}", f"product {code}"]
	return duckduckgo_lookup_queries(queries, timeout=timeout)


def duckduckgo_lookup_queries(queries: List[str], timeout: float = 8.0) -> Optional[str]:
	best: Tuple[int, Optional[str]] = (-1, None)
	for q in queries:
		try:
			r = requests.get("https://duckduckgo.com/html/", params={"q": q}, headers=HEADERS, timeout=timeout)
			if r.status_code == 200:
				pairs = re.findall(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r.text, flags=re.I)
				for href, raw_title in pairs:
					title = _clean(raw_title)
					if not _valid_title(title):
						continue
					s = _score(title, href)
					if s > best[0]:
						best = (s, title)
		except Exception:
			pass
	return best[1]


