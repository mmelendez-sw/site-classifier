"""Tests for free geocoding helpers."""

from unittest.mock import patch

from ingest.geocoder import geocode, geocode_address, reverse_geocode


def test_geocode_address_uses_census_first():
    census_result = {
        "lat": 43.05,
        "lng": -87.95,
        "lon": -87.95,
        "address": "100 E PLEASANT ST, MILWAUKEE, WI, 53212",
        "geocode_matched_address": "100 E PLEASANT ST, MILWAUKEE, WI, 53212",
        "zip_code": "53212",
        "geocode_source": "census",
        "geocode_quality": "census_match",
    }
    with patch("ingest.geocoder.geocode_census", return_value=census_result):
        result = geocode_address("100 E PLEASANT ST, MILWAUKEE, WI 53212")
    assert result["lat"] == 43.05
    assert result["lng"] == -87.95
    assert result["zip_code"] == "53212"


def test_geocode_wraps_address_for_normalizer():
    census_result = {
        "lat": 43.05,
        "lng": -87.95,
        "lon": -87.95,
        "geocode_matched_address": "100 E PLEASANT ST, MILWAUKEE, WI, 53212",
        "zip_code": "53212",
        "geocode_source": "census",
    }
    with patch("ingest.geocoder.geocode_census", return_value=census_result):
        result = geocode("100 E PLEASANT ST, MILWAUKEE, WI 53212")
    assert result["address"].startswith("100 E PLEASANT ST")
    assert result["zip_code"] == "53212"


def test_reverse_geocode_parses_postcode():
    payload = {
        "display_name": "100 E Pleasant St, Milwaukee, WI 53212, USA",
        "address": {"postcode": "53212"},
    }
    with patch("ingest.geocoder.requests.get") as mock_get:
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json.return_value = payload
        result = reverse_geocode(43.05, -87.95)
    assert result["address"].startswith("100 E Pleasant St")
    assert result["zip_code"] == "53212"
