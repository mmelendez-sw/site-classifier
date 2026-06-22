"""Tests for Salesforce upload template mapping."""

from datetime import datetime

from salesforce.upload_template import (
    build_upload_record,
    map_classifier_site_type,
    permit_scraping_carrier_leasing_source,
    upload_record_to_csv_row,
    validate_upload_record,
)


def test_permit_scraping_carrier_leasing_source():
    assert permit_scraping_carrier_leasing_source(datetime(2026, 6, 18)) == "MM_PermitScraping_jun2026"
    assert permit_scraping_carrier_leasing_source(datetime(2026, 1, 5)) == "MM_PermitScraping_jan2026"


def test_upload_record_matches_template_columns():
    record = build_upload_record(
        {
            "address": "44 S Broadway, White Plains, NY 10601",
            "lat": 41.03062,
            "lng": -73.7617,
            "zip_code": "10601",
            "permit_metadata": {"permit_id": "123"},
        },
        classified={"site_type": "rooftop", "site_confidence": 0.9},
        dedupe_row={"urbanicity_tier": "suburban", "zip_population": 10000},
        carrier_leasing_source="MM_PermitScraping_jun2026",
    )
    row = upload_record_to_csv_row(record)
    assert row["Site Street"] == "44 S Broadway"
    assert row["Site City"] == "White Plains"
    assert row["Site State"] == "NY"
    assert row["Site Zip Code"] == "10601"
    assert row["Site Country"] == "US"
    assert row["Site Latitude"] == "41.03062"
    assert row["Site Longitude"] == "-73.76170"
    assert row["Carrier Leasing Source"] == "MM_PermitScraping_jun2026"
    assert row["Site Type"] == "Rooftop"
    assert row["Verified Site"] == "TRUE"
    assert row["Verified Site Source"] == "Permitting Data"
    assert row["Morphology"] == "Suburban"
    assert validate_upload_record(record) == []


def test_map_classifier_site_type():
    assert map_classifier_site_type("tower", tower_subtype="monopole") == "Monopole"
    assert map_classifier_site_type("rooftop") == "Rooftop"
    assert map_classifier_site_type("unclear") == ""


def test_csv_row_roundtrip():
    from salesforce.upload_template import csv_row_to_upload_record

    record = build_upload_record(
        {
            "address": "44 S Broadway, White Plains, NY 10601",
            "lat": 41.03062,
            "lng": -73.7617,
            "zip_code": "10601",
        },
        classified={"site_type": "rooftop"},
        dedupe_row={"urbanicity_tier": "suburban", "zip_population": 10000},
        carrier_leasing_source="MM_PermitScraping_jun2026",
    )
    row = upload_record_to_csv_row(record)
    restored = csv_row_to_upload_record(row)
    assert restored["site_street"] == "44 S Broadway"
    assert restored["site_type"] == "Rooftop"
    assert restored["carrier_leasing_source"] == "MM_PermitScraping_jun2026"
    assert validate_upload_record(restored) == []


def test_verified_site_source_defaults_to_permitting_data_without_metadata():
    record = build_upload_record(
        {
            "address": "100 E PLEASANT ST, MILWAUKEE, WI 53212",
            "lat": 43.05,
            "lng": -87.91,
        },
        classified={"site_type": "rooftop"},
    )
    assert record["verified_site_source"] == "Permitting Data"
    row = upload_record_to_csv_row(record)
    assert row["Verified Site Source"] == "Permitting Data"
    assert row["Site Street"] == "100 E Pleasant St"
    assert row["Site City"] == "Milwaukee"
