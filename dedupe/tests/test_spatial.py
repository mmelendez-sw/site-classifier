"""Tests for spatial scoring helpers."""

from dedupe.spatial import combined_score, haversine_meters, proximity_score


def test_haversine_same_point_is_zero():
    assert haversine_meters(43.05, -87.91, 43.05, -87.91) == 0.0


def test_proximity_score_at_edges():
    assert proximity_score(0, 150) == 100
    assert proximity_score(150, 150) == 0
    assert proximity_score(75, 150) == 50


def test_combined_score_blends_address_and_proximity():
    score = combined_score(90, 100, address_weight=0.65, proximity_weight=0.35)
    assert score == 94
