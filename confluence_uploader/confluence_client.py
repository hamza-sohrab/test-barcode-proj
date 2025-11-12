import os
import re
import mimetypes
from dataclasses import dataclass
from typing import Dict, Optional

import requests


@dataclass
class ConfluenceAuth:
	base_url: str
	email: str
	token: str

	def auth(self) -> tuple:
		return (self.email, self.token)


PAGE_ID_RE = re.compile(r"/pages/(\d+)|pageId=(\d+)")


def infer_page_id_from_url(url: str) -> Optional[str]:
	m = PAGE_ID_RE.search(url)
	if not m:
		return None
	return next(g for g in m.groups() if g)


class ConfluenceClient:
	def __init__(self, auth: ConfluenceAuth):
		self.auth = auth
		self.base = auth.base_url.rstrip("/")
		self.session = requests.Session()
		self.session.auth = auth.auth()
		self.session.headers.update({"Accept": "application/json"})

	def get_page(self, page_id: str) -> Dict:
		url = f"{self.base}/rest/api/content/{page_id}?expand=body.storage,version"
		r = self.session.get(url)
		r.raise_for_status()
		return r.json()

	def update_page_storage(self, page_id: str, new_storage_value: str, title: Optional[str] = None) -> None:
		page = self.get_page(page_id)
		version = page.get("version", {}).get("number", 1)
		title_to_use = title or page.get("title", "Untitled")
		payload = {
			"id": page_id,
			"type": "page",
			"title": title_to_use,
			"version": {"number": version + 1},
			"body": {"storage": {"value": new_storage_value, "representation": "storage"}},
		}
		url = f"{self.base}/rest/api/content/{page_id}"
		r = self.session.put(url, json=payload)
		r.raise_for_status()

	def append_storage_to_page(self, page_id: str, storage_fragment: str) -> None:
		page = self.get_page(page_id)
		current = page.get("body", {}).get("storage", {}).get("value", "")
		new_body = current + "\n" + storage_fragment
		self.update_page_storage(page_id, new_body, title=page.get("title"))

	def _find_attachment_id(self, page_id: str, filename: str) -> Optional[str]:
		url = f"{self.base}/rest/api/content/{page_id}/child/attachment?filename={requests.utils.quote(filename)}"
		r = self.session.get(url)
		if r.status_code == 200:
			results = r.json().get("results", [])
			if results:
				return results[0].get("id")
		return None

	def upload_attachment(self, page_id: str, filename: str, file_bytes: bytes) -> str:
		"""Upload an attachment; if same-name exists, update it instead of failing."""
		name = os.path.basename(filename)
		mime, _ = mimetypes.guess_type(name)
		content_type = mime or "application/octet-stream"
		files = {"file": (name, file_bytes, content_type)}
		data = {"minorEdit": "true"}
		headers = {"X-Atlassian-Token": "nocheck"}
		url = f"{self.base}/rest/api/content/{page_id}/child/attachment"
		r = self.session.post(url, files=files, data=data, headers=headers)
		if r.status_code in (409, 400):
			msg = r.text.lower()
			if r.status_code == 409 or "same file name as an existing attachment" in msg:
				attachment_id = self._find_attachment_id(page_id, name)
				if attachment_id:
					update_url = f"{self.base}/rest/api/content/{page_id}/child/attachment/{attachment_id}/data"
					resp2 = self.session.post(update_url, files=files, data=data, headers=headers)
					resp2.raise_for_status()
					return name
		try:
			r.raise_for_status()
		except requests.HTTPError as e:
			raise requests.HTTPError(f"{e}\nResponse: {r.text}")
		return name

