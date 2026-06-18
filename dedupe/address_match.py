"""Street-line normalization and fuzzy matching for dedupe."""

from __future__ import annotations

import html
import re
from typing import Any

from rapidfuzz import fuzz

from dedupe.constants import (
    ADDRESS_COMPONENT_HOUSE_WEIGHT,
    ADDRESS_COMPONENT_STREET_WEIGHT,
    ADDRESS_COMPONENT_SUFFIX_WEIGHT,
    CITY_MISMATCH_REJECT_MIN_M,
    HOUSE_NUMBER_DELTA_REJECT,
    STREET_NAME_JACCARD_MIN,
)
from ingest.address_utils import parse_zip_from_address

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

_STREET_SUFFIX_TOKENS = {
    "STREET",
    "AVENUE",
    "BOULEVARD",
    "ROAD",
    "DRIVE",
    "LANE",
    "COURT",
    "PLACE",
    "TERRACE",
    "PARKWAY",
    "HIGHWAY",
    "CIRCLE",
    "TRAIL",
}

_HOUSE_NUMBER_TOKEN_RE = re.compile(r"^(\d+(?:-\d+)?)\b", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^A-Z0-9\s]+")
_WS_RE = re.compile(r"\s+")
_OSM_MARKERS_RE = re.compile(r"\b(?:COUNTY|UNITED STATES)\b", re.IGNORECASE)
_STATE_ZIP_TAIL_RE = re.compile(
    r",\s*([^,]+),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$",
    re.IGNORECASE,
)

# Mismatch cap when house numbers disagree (same pin, different building is unlikely).
_HOUSE_NUMBER_MISMATCH_CAP = 45
_RANGE_SUFFIX_MIN_SCORE = 85


def normalize_sf_address(value: Any) -> str:
    """Normalize a Salesforce or ingest address string for display."""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", ", ", text, flags=re.IGNORECASE)
    return _WS_RE.sub(" ", text).strip()


def strip_leading_poi(street: str) -> str:
    """Strip POI/building prefixes before the first house number (R01)."""
    text = normalize_sf_address(street)
    if not text:
        return ""

    text = re.sub(r"^fire station\s*\d+,?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^[^,\d]+(?:\b(?:bldg|building|tower|plaza|station|office|floor)\b)[^,]*,\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^[^,\d]+,\s*(?=\d)", "", text, flags=re.IGNORECASE)

    match = re.search(
        r"(?:^|[,\s]+)(\d+(?:-\d+)?)\s*,?\s*(?="
        r"(?:[NSEW]\b|[NSEW]\.|[NSEW]{1,2}\s|north|south|east|west|\d))",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        start = match.start(1) if match.start(1) > 0 else match.start()
        return text[start:].strip()

    match = re.search(r"\d", text)
    if match:
        return text[match.start() :].strip()
    return text


def is_osm_verbose_address(address: str) -> bool:
    """Detect OpenStreetMap-style verbose addresses (R02)."""
    return bool(_OSM_MARKERS_RE.search(normalize_sf_address(address)))


def collapse_osm_address(address: str) -> str:
    """Collapse OSM verbose addresses to USPS-style for scoring (R02)."""
    text = normalize_sf_address(address)
    if not is_osm_verbose_address(text):
        return text

    zip_code = parse_zip_from_address(text)
    parts = [part.strip() for part in text.split(",") if part.strip()]
    city: str | None = None
    state: str | None = None

    for index, part in enumerate(parts):
        if _OSM_MARKERS_RE.search(part):
            continue
        state_match = re.match(r"^([A-Z]{2})\b", part.upper())
        if state_match:
            state = state_match.group(1)
            if index > 0 and not re.search(r"\bCOUNTY\b", parts[index - 1], re.IGNORECASE):
                city = parts[index - 1]
            break
        if re.search(r"\bCOUNTY\b", part, re.IGNORECASE) and index > 0:
            city = parts[index - 1]

    street_parts: list[str] = []
    for part in parts:
        upper = part.upper()
        if city and upper == city.upper():
            break
        if re.search(r"\bCOUNTY\b", upper):
            break
        if _OSM_MARKERS_RE.search(part):
            break
        if re.match(r"^[A-Z]{2}\b", upper):
            break
        if re.match(r"^\d{5}(?:-\d{4})?$", upper):
            break
        street_parts.append(part)

    street = ", ".join(street_parts)
    street = strip_leading_poi(street)
    street = canonicalize_street_tokens(extract_street_line(street))

    if city and state and zip_code:
        return f"{street}, {city.upper()}, {state} {zip_code}"
    if zip_code:
        return f"{street}, {zip_code}"
    return street or text


def normalize_for_scoring(address: str) -> str:
    """Apply pre-score normalization while preserving raw strings elsewhere (R01/R02)."""
    text = normalize_sf_address(address)
    if is_osm_verbose_address(text):
        text = collapse_osm_address(text)
    else:
        text = strip_leading_poi(text)
    return text


def has_parseable_house_number(address: str | None) -> bool:
    """Return False when no leading house number exists after normalization."""
    return extract_house_number(normalize_for_scoring(address or "")) is not None


def extract_street_line(address: str | None) -> str:
    """Return the street portion of an address (drop city, state, zip, country)."""
    text = normalize_for_scoring(address)
    if not text:
        return ""

    if "," in text:
        head, tail = text.split(",", 1)
        tail_upper = tail.upper()
        if re.search(r"\b[A-Z]{2}\b", tail_upper) or re.search(r"\b\d{5}\b", tail_upper):
            text = head

    text = re.sub(r",?\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r",?\s*\d{5}(?:-\d{4})?\s*$", "", text)
    return _WS_RE.sub(" ", text).strip()


def extract_city_from_address(address: str | None) -> str | None:
    """Extract a normalized city token from a formatted address."""
    text = normalize_sf_address(address or "")
    if not text:
        return None

    if is_osm_verbose_address(text):
        parts = [part.strip() for part in text.split(",") if part.strip()]
        for index, part in enumerate(parts):
            if re.search(r"\bCOUNTY\b", part, re.IGNORECASE) and index > 0:
                return _normalize_city(parts[index - 1])

    match = _STATE_ZIP_TAIL_RE.search(text)
    if match:
        return _normalize_city(match.group(1))

    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) >= 3 and re.match(r"^[A-Z]{2}\b", parts[2].upper()):
        return _normalize_city(parts[1])
    return None


def _normalize_city(city: str) -> str:
    return _WS_RE.sub(" ", city.strip()).upper()


def normalize_city(value: Any) -> str | None:
    """Normalize a city field or parsed city token."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _normalize_city(text)


def cities_mismatch(
    incoming_address: str,
    candidate_address: str,
    *,
    incoming_city: str | None = None,
    matched_city: str | None = None,
) -> bool:
    """Return True when both cities are known and differ (R05/R14)."""
    left = normalize_city(incoming_city) or extract_city_from_address(incoming_address)
    right = normalize_city(matched_city) or extract_city_from_address(candidate_address)
    if not left or not right:
        return False
    return left != right


def city_mismatch_for_review(
    *,
    incoming_city: str | None,
    matched_city: str | None,
    incoming_address: str | None = None,
) -> bool:
    """Reviewer-facing city mismatch: input city vs Salesforce Site_City__c only."""
    left = normalize_city(incoming_city) or extract_city_from_address(incoming_address or "")
    right = normalize_city(matched_city)
    if not left or not right:
        return False
    return left != right


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


def parse_house_number_token(street: str) -> tuple[int | None, int | None, int | None]:
    """Return (single, range_start, range_end) parsed from the leading house token."""
    line = extract_street_line(street).upper()
    match = re.match(r"^(\d+(?:-\d+)?)\b", line)
    if not match:
        return None, None, None

    token = match.group(1)
    if "-" in token:
        start_text, end_text = token.split("-", 1)
        return None, int(start_text), int(end_text)
    return int(token), None, None


def extract_house_number(street: str) -> str | None:
    """Return the leading house number token when present."""
    line = extract_street_line(street).upper()
    match = re.match(r"^(\d+(?:-\d+)?)\b", line)
    if not match:
        return None
    return match.group(1)


def strip_house_number(street: str) -> str:
    """Return the street line without its leading house number token."""
    line = extract_street_line(street).upper()
    stripped = re.sub(r"^\d+(?:-\d+)?\b", "", line, count=1).strip()
    return canonicalize_street_tokens(stripped)


def extract_street_suffix(canonical_street: str) -> str | None:
    """Return the canonical street-type suffix token when present."""
    tokens = canonical_street.split()
    for token in reversed(tokens):
        expanded = _TOKEN_EXPANSIONS.get(token, token)
        if expanded in _STREET_SUFFIX_TOKENS:
            return expanded
    return None


def strip_street_suffix(canonical_street: str) -> str:
    """Return the street name without its trailing type suffix."""
    tokens = canonical_street.split()
    for index in range(len(tokens) - 1, -1, -1):
        expanded = _TOKEN_EXPANSIONS.get(tokens[index], tokens[index])
        if expanded in _STREET_SUFFIX_TOKENS:
            return " ".join(tokens[:index])
    return canonical_street


def house_numbers_equivalent(left_street: str, right_street: str) -> bool | None:
    """Return whether house numbers refer to the same delivery point, if known."""
    left_single, left_start, left_end = parse_house_number_token(left_street)
    right_single, right_start, right_end = parse_house_number_token(right_street)

    if left_single is None and left_start is None:
        return None
    if right_single is None and right_start is None:
        return None

    if left_single is not None and right_single is not None:
        return left_single == right_single
    if left_single is not None and right_start is not None and right_end is not None:
        return right_start <= left_single <= right_end
    if right_single is not None and left_start is not None and left_end is not None:
        return left_start <= right_single <= left_end
    return False


def house_number_delta(left_address: str, right_address: str) -> int | None:
    """Return absolute house-number delta when both singles are known (R04/R09)."""
    left_single, _, _ = parse_house_number_token(extract_street_line(left_address))
    right_single, _, _ = parse_house_number_token(extract_street_line(right_address))
    if left_single is None or right_single is None:
        return None
    return abs(left_single - right_single)


def street_names_match(left_address: str, right_address: str) -> bool:
    """Return whether normalized street names agree enough to match (R03)."""
    return street_token_jaccard(left_address, right_address) >= STREET_NAME_JACCARD_MIN


def suffix_mismatch(left_address: str, right_address: str) -> bool:
    """Return True when both suffixes are known and differ (R08)."""
    left_suffix = extract_street_suffix(strip_house_number(extract_street_line(left_address)))
    right_suffix = extract_street_suffix(strip_house_number(extract_street_line(right_address)))
    if not left_suffix or not right_suffix:
        return False
    return left_suffix != right_suffix


def _weighted_address_score(
    *,
    house_score: int,
    street_score: int,
    suffix_score: int,
) -> int:
    weighted = (
        ADDRESS_COMPONENT_HOUSE_WEIGHT * house_score
        + ADDRESS_COMPONENT_STREET_WEIGHT * street_score
        + ADDRESS_COMPONENT_SUFFIX_WEIGHT * suffix_score
    )
    return int(round(max(0, min(100, weighted))))


def address_match_score(incoming_address: str, candidate_address: str) -> int:
    """Score two addresses using weighted street components (R06)."""
    left = canonicalize_street_tokens(extract_street_line(incoming_address))
    right = canonicalize_street_tokens(extract_street_line(candidate_address))
    if not left or not right:
        return 0

    number_relation = house_numbers_equivalent(left, right)
    if number_relation is False:
        score = int(round(fuzz.WRatio(left, right)))
        return min(score, _HOUSE_NUMBER_MISMATCH_CAP)

    left_body = strip_house_number(left)
    right_body = strip_house_number(right)
    left_name = strip_street_suffix(left_body)
    right_name = strip_street_suffix(right_body)
    left_suffix = extract_street_suffix(left_body)
    right_suffix = extract_street_suffix(right_body)

    street_score = int(round(fuzz.WRatio(left_name, right_name)))
    suffix_score = 100
    if left_suffix and right_suffix and left_suffix != right_suffix:
        suffix_score = 0

    if number_relation is True:
        if street_score >= _RANGE_SUFFIX_MIN_SCORE and suffix_score == 100:
            return 100
        house_score = 100
        return _weighted_address_score(
            house_score=house_score,
            street_score=street_score,
            suffix_score=suffix_score,
        )

    house_score = 50
    return _weighted_address_score(
        house_score=house_score,
        street_score=street_score,
        suffix_score=suffix_score,
    )


def street_token_jaccard(left_address: str, right_address: str) -> float:
    """Jaccard similarity on street tokens (ignores house numbers)."""
    left_tokens = set(strip_house_number(extract_street_line(left_address)).split())
    right_tokens = set(strip_house_number(extract_street_line(right_address)).split())
    left_tokens.discard("")
    right_tokens.discard("")
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(intersection) / len(union)


def evaluate_match_features(
    incoming_address: str,
    candidate_address: str,
    *,
    incoming_city: str | None = None,
    matched_city: str | None = None,
    distance_m: float | None,
) -> dict[str, Any]:
    """Compute hard-gate flags and reviewer metadata for a candidate pair."""
    delta = house_number_delta(incoming_address, candidate_address)
    street_match = street_names_match(incoming_address, candidate_address)
    city_mismatch = cities_mismatch(
        incoming_address,
        candidate_address,
        incoming_city=incoming_city,
        matched_city=matched_city,
    )
    suffix_flag = suffix_mismatch(incoming_address, candidate_address)

    hard_gate_reason: str | None = None
    if not street_match:
        hard_gate_reason = "hard_gate_street_mismatch"
    elif delta is not None and delta > HOUSE_NUMBER_DELTA_REJECT:
        hard_gate_reason = "hard_gate_house_number_delta"
    elif (
        city_mismatch
        and distance_m is not None
        and distance_m > CITY_MISMATCH_REJECT_MIN_M
    ):
        hard_gate_reason = "hard_gate_city_mismatch"

    return {
        "street_match": street_match,
        "house_number_delta": delta,
        "suffix_mismatch": suffix_flag,
        "city_mismatch": city_mismatch,
        "hard_gate_reason": hard_gate_reason,
        "passed": hard_gate_reason is None,
    }
