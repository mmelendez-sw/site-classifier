"""Tests for address component parsing."""

from ingest.address_parts import format_address_for_upload, parse_address_components


def test_parse_address_components_standard_us_address():
    parts = parse_address_components("44 S Broadway, White Plains, NY 10601")
    assert parts["site_street"] == "44 S Broadway"
    assert parts["site_city"] == "White Plains"
    assert parts["site_state"] == "NY"
    assert parts["zip_code"] == "10601"
    assert parts["site_country"] == "US"


def test_parse_address_components_dc():
    parts = parse_address_components(
        "1011 N CAPITOL ST NE, WASHINGTON, DC, 20002",
        zip_code="20002",
    )
    assert parts["site_street"] == "1011 N Capitol St NE"
    assert parts["site_state"] == "DC"
    assert parts["zip_code"] == "20002"


def test_format_address_for_upload_all_caps():
    assert format_address_for_upload("100 E PLEASANT ST") == "100 E Pleasant St"
    assert format_address_for_upload("MILWAUKEE") == "Milwaukee"
    assert format_address_for_upload("1110 N OLD WORLD THIRD ST") == "1110 N Old World Third St"
