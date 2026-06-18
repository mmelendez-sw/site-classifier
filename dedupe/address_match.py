"""Street-line normalization and fuzzy matching for dedupe."""

from __future__ import annotations

import html
import re
from typing import Any

from rapidfuzz import fuzz

# US street-type and direction abbreviations (token-level expansion).
_TOKEN_EXPANSIONS: dict[str, str] = {
    "N": "NORTH",
    "S": "SOUTH",
    "E": "EAST",
    "W": "WEST",
    "NE": "NORTHEAST",
    "NW": "NORTHWEST",
    "SE": "SOUTHEAST",
    "SW": "SOUTHWEST",
    "ST": "STREET",
    "STREET": "STREET",
    "AVE": "AVENUE",
    "AV": "AVENUE",
    "AVENUE": "AVENUE",
    "BLVD": "BOULEVARD",
    "BOULEVARD": "BOULEVARD",
    "RD": "ROAD",
    "ROAD": "ROAD",
    "DR": "DRIVE",
    "DRIVE": "DRIVE",
    "LN": "LANE",
    "LANE": "LANE",
    "CT": "COURT",
    "COURT": "COURT",
    "PL": "PLACE",
    "PLACE": "PLACE",
    "TER": "TERRACE",
    "TERRACE": "TERRACE",
    "PKWY": "PARKWAY",
    "PARKWAY": "PARKWAY",
    "HWY": "HIGHWAY",
    "HIGHWAY": "HIGHWAY",
    "CIR": "CIRCLE",
    "CIRCLE": "CIRCLE",
    "TRL": "TRAIL",
    "TRAIL": "TRAIL",
}

_HOUSE_NUMBER_RE = re.compile(r"^(\d+[A-Z0-9-]*)\b", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9\s]+")
_WS_RE = re.compile(r"\s+")

# Mismatch cap when house numbers disagree (same pin, different building is unlikely).
_HOUSE_NUMBER_MISMATCH_CAP = 45


def normalize_sf_address(value: Any) -> str:
    """Normalize a Salesforce or ingest address string for display."""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", ", ", text, flags=re.IGNORECASE)
    return _WS_RE.sub(" ", text).strip()


def extract_street_line(address: str | None) -> str:
    """Return the street portion of an address (drop city, state, zip, country)."""
    text = normalize_sf_address(address)
    if not text:
        return ""

    # Prefer content before the first comma when the tail looks like locality metadata.
    if "," in text:
        head, tail = text.split(",", 1)
        tail_upper = tail.upper()
        if re.search(r"\b[A-Z]{2}\b", tail_upper) or re.search(r"\b\d{5}\b", tail_upper):
            text = head

    # Drop trailing state + zip when still embedded in the street segment.
    text = re.sub(r",?\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r",?\s*\d{5}(?:-\d{4})?\s*$", "", text)
    return _WS_RE.sub(" ", text).strip()


def canonicalize_street_tokens(street: str) -> str:
    """Uppercase, expand abbreviations, and collapse whitespace."""
    text = normalize_sf_address(street).upper()
    text = _NON_ALNUM_RE.sub(" ", text)
    tokens = []
    for token in _WS_RE.split(text):
        if not token:
            continue
        tokens.append(_TOKEN_EXPANSIONS.get(token, token))
    return " ".join(tokens)


def extract_house_number(street: str) -> str | None:
    """Return the leading house number when present."""
    match = _HOUSE_NUMBER_RE.match(canonicalize_street_tokens(street))
    if not match:
        return None
    return match.group(1).upper()


def address_match_score(incoming_address: str, candidate_address: str) -> int:
    """Score two addresses on normalized street lines with a house-number gate."""
    left = canonicalize_street_tokens(extract_street_line(incoming_address))
    right = canonicalize_street_tokens(extract_street_line(candidate_address))
    if not left or not right:
        return 0

    score = int(round(fuzz.WRatio(left, right)))

    left_num = extract_house_number(left)
    right_num = extract_house_number(right)
    if left_num and right_num and left_num != right_num:
        score = min(score, _HOUSE_NUMBER_MISMATCH_CAP)

    return max(0, min(100, score))
