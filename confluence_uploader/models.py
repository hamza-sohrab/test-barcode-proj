from dataclasses import dataclass
from typing import Optional


@dataclass
class RowDraft:
	barcode_type: str
	barcode_value: str  # display value
	item_name: Optional[str]
	notes: Optional[str] = None

