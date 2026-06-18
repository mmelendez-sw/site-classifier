"""Placeholder tests for dedupe resolver."""

from dedupe.constants import DEFAULT_RADIUS_METERS
from dedupe.resolver import SiteResolver


def test_build_bounding_box_symmetric():
    bbox = SiteResolver.build_bounding_box(38.0, -77.0, meters=250)
    assert bbox["min_lat"] < 38.0 < bbox["max_lat"]
    assert bbox["min_lng"] < -77.0 < bbox["max_lng"]


def test_fuzzy_match_prefers_close_address():
    score, match = SiteResolver.fuzzy_match(
        "100 F St NE, Washington, DC",
        [{"Id": "001", "Site_Address__c": "100 F Street NE, Washington, DC 20549"}],
    )
    assert score > 60
    assert match is not None


def test_score_candidate_within_radius_boosts_combined_score():
    incoming = "100 Main St, Milwaukee, WI 53212"
    sf_record = {
        "Id": "001",
        "Site_Address__c": "100 Main Street, Milwaukee, WI 53212",
        "Site_Latitude__c": 43.0526,
        "Site_Longitude__c": -87.9112,
    }
    scored = SiteResolver._score_candidate(
        incoming,
        43.052581,
        -87.911206,
        sf_record,
        search_radius_m=150,
    )
    assert scored["within_radius"] is True
    assert scored["address_score"] >= 80
    assert scored["combined_score"] >= scored["address_score"]


def test_prefilter_excludes_far_candidates():
    pool = [
        {
            "Id": "near",
            "Site_Address__c": "100 Main St",
            "Site_Latitude__c": 43.0526,
            "Site_Longitude__c": -87.9112,
        },
        {
            "Id": "far",
            "Site_Address__c": "999 Remote Rd",
            "Site_Latitude__c": 44.0,
            "Site_Longitude__c": -88.5,
        },
    ]
    filtered = SiteResolver._prefilter_candidates(
        pool,
        incoming_lat=43.052581,
        incoming_lng=-87.911206,
        incoming_zip="53212",
        max_distance_m=500,
    )
    assert len(filtered) == 1
    assert filtered[0]["Id"] == "near"


def test_resolve_in_radius_status_uses_proximity_duplicate_rule():
    match = {
        "combined_score": 58,
        "address_score": 78,
        "distance_m": 12.0,
    }
    status, score = SiteResolver._resolve_in_radius_status(match)
    assert status == "duplicate"
    assert score == 58


def test_resolve_in_radius_status_uses_proximity_review_rule():
    match = {
        "combined_score": 55,
        "address_score": 72,
        "distance_m": 40.0,
    }
    status, score = SiteResolver._resolve_in_radius_status(match)
    assert status == "review"
    assert score == 55


def test_is_potential_duplicate_flags_close_net_new():
    match = {
        "within_radius": True,
        "combined_score": 55,
        "distance_m": 62.0,
    }
    assert SiteResolver.is_potential_duplicate(status="net_new", match=match) is True


def test_is_potential_duplicate_rejects_far_net_new():
    match = {
        "within_radius": True,
        "combined_score": 55,
        "distance_m": 150.0,
    }
    assert SiteResolver.is_potential_duplicate(status="net_new", match=match) is False


def test_resolve_returns_status_shape():
    assert DEFAULT_RADIUS_METERS == 250
