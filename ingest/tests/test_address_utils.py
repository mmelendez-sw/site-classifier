"""Tests for address zip parsing."""

from ingest.address_utils import parse_zip_from_address


def test_parse_zip_from_state_suffix():
    assert parse_zip_from_address("100 E PLEASANT ST, MILWAUKEE, WI 53212") == "53212"


def test_parse_zip_ignores_leading_street_number():
    assert parse_zip_from_address("10001 W BLUE MOUND RD, MILWAUKEE, WI 53226") == "53226"


def test_parse_zip_from_census_formatted_address():
    assert (
        parse_zip_from_address("10001 W BLUE MOUND RD, MILWAUKEE, WI, 53226")
        == "53226"
    )
