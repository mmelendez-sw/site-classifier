"""Tests for Salesforce geocode enrichment."""

from unittest.mock import patch

from dedupe.sf_geocode import (
    build_sf_geocode_address,
    enrich_missing_sf_coordinates,
    resolve_sf_coordinates,
)


def test_build_sf_geocode_address_composes_city_state_zip():
    address = build_sf_geocode_address({
        "Site_Address__c": "1800 W BECHER ST",
        "Site_City__c": "MILWAUKEE",
        "Site_State__c": "WI",
        "Site_Zip_Code__c": "53215",
    })
    assert address == "1800 W BECHER ST, MILWAUKEE, WI 53215"


def test_enrich_geocodes_only_missing_native_coordinates():
    records = [
        {
            "Id": "001",
            "Site_Address__c": "1800 W BECHER ST",
            "Site_City__c": "MILWAUKEE",
            "Site_State__c": "WI",
            "Site_Zip_Code__c": "53215",
        },
        {
            "Id": "002",
            "Site_Address__c": "100 Main St",
            "Site_Latitude__c": 43.05,
            "Site_Longitude__c": -87.91,
        },
    ]
    with patch("dedupe.sf_geocode.geocode", return_value={"lat": 43.01, "lng": -87.94}):
        summary = enrich_missing_sf_coordinates(records)

    assert summary["native"] == 1
    assert summary["geocoded"] == 1
    assert resolve_sf_coordinates(records[0]) == (43.01, -87.94, "geocoded")
    assert resolve_sf_coordinates(records[1]) == (43.05, -87.91, "salesforce")


def test_resolve_sf_coordinates_prefers_salesforce_values():
    record = {
        "Site_Latitude__c": 43.05,
        "Site_Longitude__c": -87.91,
        "_dedupe_geocoded_lat": 1.0,
        "_dedupe_geocoded_lng": 2.0,
    }
    assert resolve_sf_coordinates(record) == (43.05, -87.91, "salesforce")
