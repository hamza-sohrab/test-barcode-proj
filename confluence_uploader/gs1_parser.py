from typing import Dict, Optional, Tuple
import re

# Patterns for (01)GTIN14 with or without parentheses, FNC1 not handled fully
AI_PATTERN = re.compile(r"\((\d{2,4})\)")
DIGITS = re.compile(r"\d+")

# Fixed-length AIs we care about
FIXED_LENGTH = {
	"01": 14,  # GTIN
	"17": 6,   # Expiry YYMMDD
	"15": 6,   # Best before YYMMDD
}

# Variable-length common AIs (terminated by FNC1 typically)
VARIABLE = {"10", "21"}  # batch/lot, serial


def parse_gs1(data: str) -> Dict[str, str]:
	"""Parse a GS1 element string, returning a dict of AI->value. Best-effort.

	Supports strings with parentheses like (01).... and attempts naive parsing
	when parentheses are missing.
	"""
	result: Dict[str, str] = {}
	if not data:
		return result

	# If parentheses present, use them
	pos = 0
	while True:
		m = AI_PATTERN.search(data, pos)
		if not m:
			break
		ai = m.group(1)
		start = m.end()
		length = FIXED_LENGTH.get(ai)
		if length is not None:
			val = data[start : start + length]
			result[ai] = val
			pos = start + length
		else:
			# variable length until next (AI) or end
			next_m = AI_PATTERN.search(data, start)
			val = data[start : next_m.start() if next_m else len(data)]
			result[ai] = val
			pos = start + len(val)

	# Fallback: no parentheses, guess at start with 01 of length 14
	if not result and data.startswith("01") and len(data) >= 16:
		gtin = data[2:16]
		result["01"] = gtin
		# attempt to find (10) batch as next variable part
		rest = data[16:]
		if rest.startswith("10"):
			# variable till end or next AI-like two digits
			val = rest[2:]
			result["10"] = val

	return result


def extract_gtin(data: str) -> Optional[str]:
	parsed = parse_gs1(data)
	return parsed.get("01")

