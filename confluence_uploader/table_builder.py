from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Row:
	barcode_type: str
	item_name: Optional[str]
	barcode_value: str
	attachment_filename: str
	notes: Optional[str] = None


def build_table(rows: List[Row]) -> str:
	"""Return Confluence storage-format HTML for the table with images.

	Columns: Barcode Type / Category | Item Name | Barcode Value | Barcode Images | Notes
	"""
	def cell(text: str) -> str:
		return f"<td>{text}</td>"

	def img_cell(filename: str) -> str:
		return (
			"<td>"
			"<ac:image ac:thumbnail=\"true\">"
			f"<ri:attachment ri:filename=\"{filename}\"/>"
			"</ac:image>"
			"</td>"
		)

	head = (
		"<tr>"
		"<th><strong>Barcode Type / Category</strong></th>"
		"<th><strong>Item Name</strong></th>"
		"<th><strong>Barcode Value</strong></th>"
		"<th><strong>Barcode Images</strong></th>"
		"<th><strong>Notes</strong></th>"
		"</tr>"
	)
	body_rows = _build_rows_html(rows)
	return f"<table>{head}{body_rows}</table>"


def build_rows(rows: List[Row]) -> str:
	"""Return only the <tr> rows for appending to an existing table."""
	return _build_rows_html(rows)


def _build_rows_html(rows: List[Row]) -> str:
	def cell(text: str) -> str:
		return f"<td>{text}</td>"

	def img_cell(filename: str) -> str:
		return (
			"<td>"
			"<ac:image ac:thumbnail=\"true\">"
			f"<ri:attachment ri:filename=\"{filename}\"/>"
			"</ac:image>"
			"</td>"
		)

	body_rows: List[str] = []
	for r in rows:
		body_rows.append(
			"<tr>"
			f"{cell(r.barcode_type)}"
			f"{cell(r.item_name or '')}"
			f"{cell(r.barcode_value)}"
			f"{img_cell(r.attachment_filename)}"
			f"{cell(r.notes or '')}"
			"</tr>"
		)
	return "".join(body_rows)
