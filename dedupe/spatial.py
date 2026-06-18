"""Distance helpers for spatial dedupe."""

from __future__ import annotations

import math
from typing import Any

_METERS_PER_DEG_LAT = 111_320


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in meters between two WGS84 points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def sf_coordinates(record: dict[str, Any], *, lat_field: str, lng_field: str) -> tuple[float, float] | None:
    """Return Salesforce lat/lng when both coordinates are present."""
    lat = record.get(lat_field)
    lng = record.get(lng_field)
    if lat is None or lng is None:
        return None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def proximity_score(distance_m: float, radius_m: float) -> int:
    """Map distance inside a search radius to a 0-100 proximity score."""
    if radius_m <= 0:
        return 0
    if distance_m <= 0:
        return 100
    if distance_m >= radius_m:
        return 0
    return int(round(100 * (1 - distance_m / radius_m)))


def combined_score(address_score: int, proximity: int, *, address_weight: float, proximity_weight: float) -> int:
    """Blend fuzzy address score with in-radius proximity score."""
    total = address_weight + proximity_weight
    if total <= 0:
        return address_score
    blended = (address_weight * address_score + proximity_weight * proximity) / total
    return int(round(max(0, min(100, blended))))
