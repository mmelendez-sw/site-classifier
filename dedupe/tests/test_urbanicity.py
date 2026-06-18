"""Tests for urbanicity tier lookup."""

from dedupe.urbanicity import (
    UrbanicityProfile,
    classify_population,
    radius_for_tier,
    urbanicity_for_record,
)


def test_classify_population_tiers():
    assert classify_population(30_000) == "urban"
    assert classify_population(10_000) == "suburban"
    assert classify_population(1_000) == "rural"


def test_radius_for_tier():
    assert radius_for_tier("urban") == 100
    assert radius_for_tier("suburban") == 150
    assert radius_for_tier("rural") == 250


def test_urbanicity_for_milwaukee_zip(tmp_path, monkeypatch):
    csv_path = tmp_path / "zip_populations.csv"
    csv_path.write_text("zip,population\n53212,20395\n", encoding="utf-8")
    monkeypatch.setenv("ZIP_POPULATION_CSV", str(csv_path))

    from dedupe import urbanicity as urbanicity_module
    urbanicity_module._load_population_table.cache_clear()

    profile = urbanicity_for_record(
        {"address": "100 E PLEASANT ST, MILWAUKEE, WI 53212", "lat": 43.0, "lng": -87.9}
    )
    assert isinstance(profile, UrbanicityProfile)
    assert profile.zip_code == "53212"
    assert profile.population == 20395
    assert profile.tier == "suburban"
    assert profile.search_radius_m == 150


def test_unknown_zip_defaults_to_suburban(monkeypatch):
    monkeypatch.setenv("ZIP_POPULATION_CSV", "missing-file.csv")
    from dedupe import urbanicity as urbanicity_module
    urbanicity_module._load_population_table.cache_clear()

    profile = urbanicity_for_record({"address": "1 Main St, Nowhere, WI 99999", "lat": 0, "lng": 0})
    assert profile.tier == "suburban"
    assert profile.search_radius_m == 150
    assert profile.population is None
