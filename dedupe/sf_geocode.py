"""Geocode Salesforce site records that are missing native coordinates."""

from __future__ import annotations

import logging
import os
from typing import Any

from dedupe.constants import (
    SF_ADDRESS_FIELD,
    SF_CITY_FIELD,
    SF_LAT_FIELD,
    SF_LNG_FIELD,
    SF_STATE_FIELD,
    SF_ZIP_FIELD,
)
from dedupe.spatial import sf_coordinates
from ingest.geocoder import geocode

logger = logging.getLogger(__name__)

DEDUPE_GEOCODED_LAT = "_dedupe_geocoded_lat"
DEDUPE_GEOCODED_LNG = "_dedupe_geocoded_lng"
DEDUPE_COORD_SOURCE = "_dedupe_coordinate_source"


def sf_geocode_enabled() -> bool:
    return os.environ.get("SF_GEOCODE_MISSING", "1").strip().lower() in ("1", "true", "yes")


def normalize_sf_address(value: Any) -> str:
    text = str(value or "")
    return text.replace("<br>", " ").replace("<BR>", " ").strip()


def build_sf_geocode_address(record: dict[str, Any]) -> str | None:
    """Build a one-line address suitable for Census/Nominatim geocoding."""
    street = normalize_sf_address(record.get(SF_ADDRESS_FIELD) or record.get("Name"))
    if not street:
        return None

    city = str(record.get(SF_CITY_FIELD) or "").strip() or None
    state = str(record.get(SF_STATE_FIELD) or "").strip() or None
    zip_code = str(record.get(SF_ZIP_FIELD) or "").strip() or None
    upper = street.upper()

    suffix_parts: list[str] = []
    if city and city.upper() not in upper:
        suffix_parts.append(city)
    if state and state.upper() not in upper:
        suffix_parts.append(state)

    if zip_code and zip_code not in street:
        if suffix_parts:
            return f"{street}, {', '.join(suffix_parts)} {zip_code}"
        return f"{street}, {zip_code}"
    if suffix_parts:
        return f"{street}, {', '.join(suffix_parts)}"
    return street


def resolve_sf_coordinates(record: dict[str, Any]) -> tuple[float, float, str] | None:
    """Return lat/lng and source label from Salesforce or prefetch geocode fallback."""
    native = sf_coordinates(record, lat_field=SF_LAT_FIELD, lng_field=SF_LNG_FIELD)
    if native is not None:
        return native[0], native[1], "salesforce"

    geocoded_lat = record.get(DEDUPE_GEOCODED_LAT)
    geocoded_lng = record.get(DEDUPE_GEOCODED_LNG)
    if geocoded_lat is not None and geocoded_lng is not None:
        try:
            return float(geocoded_lat), float(geocoded_lng), "geocoded"
        except (TypeError, ValueError):
            return None
    return None


def enrich_missing_sf_coordinates(
    records: list[dict[str, Any]],
    *,
    verbose: bool = False,
) -> dict[str, int]:
    """Geocode only Salesforce rows missing Site_Latitude__c/Site_Longitude__c."""
    if not sf_geocode_enabled():
        if verbose:
            logger.info("  SF geocode fallback: disabled (SF_GEOCODE_MISSING=0)")
        return {"native": 0, "geocoded": 0, "failed": 0, "skipped": len(records)}

    summary = {"native": 0, "geocoded": 0, "failed": 0, "skipped": 0}
    to_geocode: list[tuple[dict[str, Any], str]] = []

    for record in records:
        if sf_coordinates(record, lat_field=SF_LAT_FIELD, lng_field=SF_LNG_FIELD) is not None:
            record[DEDUPE_COORD_SOURCE] = "salesforce"
            summary["native"] += 1
            continue

        address = build_sf_geocode_address(record)
        if not address:
            record[DEDUPE_COORD_SOURCE] = "missing"
            summary["failed"] += 1
            continue

        to_geocode.append((record, address))

    if verbose and to_geocode:
        logger.info(
            "  SF geocode fallback: %d native coords, geocoding %d missing",
            summary["native"],
            len(to_geocode),
        )

    for index, (record, address) in enumerate(to_geocode, start=1):
        site_id = record.get("Id", "—")
        try:
            result = geocode(address)
            record[DEDUPE_GEOCODED_LAT] = result["lat"]
            record[DEDUPE_GEOCODED_LNG] = result["lng"]
            record[DEDUPE_COORD_SOURCE] = "geocoded"
            summary["geocoded"] += 1
            if verbose:
                logger.info(
                    "    [%d/%d] geocoded SF %s lat=%.6f lng=%.6f",
                    index,
                    len(to_geocode),
                    site_id,
                    result["lat"],
                    result["lng"],
                )
                logger.info("           %s", address[:100])
        except Exception as exc:
            record[DEDUPE_COORD_SOURCE] = "missing"
            summary["failed"] += 1
            if verbose:
                logger.warning(
                    "    [%d/%d] SF geocode failed %s: %s",
                    index,
                    len(to_geocode),
                    site_id,
                    exc,
                )

    if verbose:
        logger.info(
            "  SF coordinate summary: native=%d geocoded=%d failed=%d",
            summary["native"],
            summary["geocoded"],
            summary["failed"],
        )

    return summary
