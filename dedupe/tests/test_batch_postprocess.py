"""Tests for batch dedupe postprocessing."""

from dedupe.batch_postprocess import (
    apply_batch_postprocess,
    escalate_address_exact_distance_outliers,
    mark_input_duplicates,
    mark_input_duplicates_near,
    promote_potential_duplicates,
    reconcile_shared_matched_ids,
)
from dedupe.match_snapshot import serialize_scored_candidate


def _row(**kwargs):
    base = {
        "address": "100 Main St",
        "lat": 43.0,
        "lng": -87.9,
        "status": "net_new",
        "status_resolver": "net_new",
        "status_recommended": "net_new",
        "combined_score": 50,
        "address_score": 50,
        "matched_id": None,
        "potential_duplicate": False,
        "urbanicity_prefilter_radius_m": 100,
        "resolution_detail": "status=net_new",
        "_gated_candidates": [],
    }
    base.update(kwargs)
    return base


def _candidate(matched_id: str, combined: int, address: int = 90) -> dict:
    item = {
        "record": {"Id": matched_id, "Site_Address__c": f"{matched_id} Main St"},
        "address_score": address,
        "proximity_score": 80,
        "combined_score": combined,
        "distance_m": 20.0,
        "coordinate_source": "salesforce",
        "scoring_mode": "address_exact_override",
        "match_features": {"passed": True},
    }
    return serialize_scored_candidate(item, routing_reason="high_address_match")


def test_mark_input_duplicates():
    rows = [
        _row(address="100 Main St, Milwaukee, WI 53212"),
        _row(address="100 MAIN ST, MILWAUKEE, WI 53212"),
    ]
    changed = mark_input_duplicates(rows)
    assert changed == 1
    assert rows[0]["status_recommended"] == "net_new"
    assert rows[1]["status_recommended"] == "duplicate"
    assert rows[1]["routing_reason"] == "duplicate_of_input"


def test_mark_input_duplicates_near():
    rows = [
        _row(
            address="100 Main St, Milwaukee, WI 53212",
            lat=43.0,
            lng=-87.9,
        ),
        _row(
            address="102 Main Street, Milwaukee, WI 53212",
            lat=43.00001,
            lng=-87.90001,
        ),
    ]
    changed = mark_input_duplicates_near(rows)
    assert changed == 1
    assert rows[1]["routing_reason"] == "duplicate_of_input_near"


def test_reconcile_shared_matched_ids_reroutes_loser():
    rows = [
        _row(
            status="duplicate",
            status_recommended="duplicate",
            matched_id="001",
            combined_score=100,
            address_score=100,
            _gated_candidates=[_candidate("001", 100), _candidate("002", 70)],
        ),
        _row(
            status="net_new",
            status_recommended="net_new",
            matched_id="001",
            combined_score=52,
            address_score=45,
            _gated_candidates=[_candidate("001", 52), _candidate("002", 70)],
        ),
    ]
    changed = reconcile_shared_matched_ids(rows)
    assert changed == 1
    assert rows[1]["matched_id"] == "002"
    assert rows[1]["routing_reason"] == "matched_id_rerouted"


def test_reconcile_shared_matched_ids_clears_loser_without_alternate():
    rows = [
        _row(
            status="duplicate",
            status_recommended="duplicate",
            matched_id="001",
            combined_score=100,
            address_score=100,
            _gated_candidates=[_candidate("001", 100)],
        ),
        _row(
            status="duplicate",
            status_recommended="duplicate",
            matched_id="001",
            combined_score=52,
            address_score=45,
            _gated_candidates=[_candidate("001", 52)],
        ),
    ]
    changed = reconcile_shared_matched_ids(rows)
    assert changed == 1
    assert rows[1]["status_recommended"] == "net_new"
    assert rows[1]["matched_id"] is None


def test_escalate_address_exact_distance_outliers():
    rows = [
        _row(
            status="duplicate",
            status_recommended="duplicate",
            routing_reason="high_address_exact",
            matched_distance_m=235,
            urbanicity_prefilter_radius_m=100,
        )
    ]
    changed = escalate_address_exact_distance_outliers(rows)
    assert changed == 1
    assert rows[0]["status_recommended"] == "review"
    assert rows[0]["override_reason"] == "address_exact_distance_outlier"


def test_promote_potential_duplicates():
    rows = [_row(status="net_new", status_recommended="net_new", potential_duplicate=True)]
    changed = promote_potential_duplicates(rows)
    assert changed == 1
    assert rows[0]["status_recommended"] == "review"
    assert rows[0]["routing_reason"] == "potential_duplicate_promoted"


def test_apply_batch_postprocess_runs_all_passes():
    rows = [
        _row(address="1 Main", lat=1.0, lng=2.0),
        _row(address="1 MAIN", lat=1.0, lng=2.0),
        _row(status="net_new", status_recommended="net_new", potential_duplicate=True, matched_id="abc"),
    ]
    summary = apply_batch_postprocess(rows)
    assert summary["input_duplicates"] == 1
    assert summary["potential_duplicate_promoted"] == 1
