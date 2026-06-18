"""Tests for street-line address matching."""

from dedupe.address_match import (
    address_match_score,
    canonicalize_street_tokens,
    extract_house_number,
    extract_street_line,
)


def test_extract_street_line_strips_city_state_zip():
    street = extract_street_line("1525 N 24TH ST, MILWAUKEE, WI 53205")
    assert street == "1525 N 24TH ST"


def test_extract_street_line_handles_salesforce_html():
    street = extract_street_line("1800 W BECHER ST<br>MILWAUKEE, WI 53215")
    assert street == "1800 W BECHER ST"


def test_canonicalize_street_tokens_expands_abbreviations():
    assert canonicalize_street_tokens("1525 N 24th St") == "1525 NORTH 24TH STREET"


def test_extract_house_number():
    assert extract_house_number("1525 North 24th Street") == "1525"
    assert extract_house_number("North Avenue") is None


def test_address_match_score_similar_streets():
    score = address_match_score(
        "1525 N 24TH ST, MILWAUKEE, WI 53205",
        "1525 North 24th Street<br>Milwaukee, WI 53205",
    )
    assert score >= 90


def test_address_match_score_penalizes_different_house_numbers():
    score = address_match_score(
        "1525 N 24TH ST, MILWAUKEE, WI 53205",
        "1520 North 24th Street, Milwaukee, WI 53205",
    )
    assert score <= 45
