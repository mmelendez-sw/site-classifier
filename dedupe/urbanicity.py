"""Zip-code population lookup and urbanicity search-radius tiers."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from dedupe.constants import (
    SUBURBAN_POPULATION_MIN,
    SUBURBAN_RADIUS_M,
    URBAN_POPULATION_MIN,
    URBAN_RADIUS_M,
    URBANICITY_DEFAULT_TIER,
    RURAL_RADIUS_M,
)
from dedupe.context import extract_zip_code

DEFAULT_POPULATION_CSV = Path("data/zip_populations.csv")


@dataclass(frozen=True)
class UrbanicityProfile:
    """Urbanicity classification and search radius for one incoming record."""

    zip_code: str | None
    population: int | None
    tier: str
    search_radius_m: float
    population_source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "zip_code": self.zip_code,
            "zip_population": self.population,
            "urbanicity_tier": self.tier,
            "search_radius_m": self.search_radius_m,
            "population_source": self.population_source,
        }


def _population_csv_path() -> Path:
    configured = os.environ.get("ZIP_POPULATION_CSV", "").strip()
    return Path(configured) if configured else DEFAULT_POPULATION_CSV


@lru_cache(maxsize=1)
def _load_population_table() -> dict[str, int]:
    path = _population_csv_path()
    if not path.exists():
        return {}

    populations: dict[str, int] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        zip_field = _find_field(reader.fieldnames or [], ("zip", "zip_code", "zcta", "ZCTA5CE20"))
        pop_field = _find_field(
            reader.fieldnames or [],
            ("population", "pop", "POPULATION", "P1_001N", "P001001"),
        )
        if not zip_field or not pop_field:
            return populations

        for row in reader:
            zip_code = _normalize_zip(row.get(zip_field))
            population = _parse_population(row.get(pop_field))
            if zip_code and population is not None:
                populations[zip_code] = population
    return populations


def classify_population(population: int) -> str:
    """Map a ZCTA population count to urban, suburban, or rural."""
    if population >= URBAN_POPULATION_MIN:
        return "urban"
    if population >= SUBURBAN_POPULATION_MIN:
        return "suburban"
    return "rural"


def radius_for_tier(tier: str) -> float:
    """Return the dedupe search radius for an urbanicity tier."""
    if tier == "urban":
        return float(URBAN_RADIUS_M)
    if tier == "suburban":
        return float(SUBURBAN_RADIUS_M)
    return float(RURAL_RADIUS_M)


def lookup_zip_population(zip_code: str | None) -> tuple[int | None, str]:
    """Return population and source label for a zip code."""
    normalized = _normalize_zip(zip_code)
    if not normalized:
        return None, "missing_zip"

    population = _load_population_table().get(normalized)
    if population is not None:
        return population, "zip_populations_csv"
    return None, "unknown_zip"


def urbanicity_for_record(record: dict[str, Any]) -> UrbanicityProfile:
    """Derive urbanicity tier and per-asset search radius from the record zip."""
    zip_code = extract_zip_code(record)
    population, source = lookup_zip_population(zip_code)

    if population is None:
        tier = URBANICITY_DEFAULT_TIER
        return UrbanicityProfile(
            zip_code=zip_code,
            population=None,
            tier=tier,
            search_radius_m=radius_for_tier(tier),
            population_source=source,
        )

    tier = classify_population(population)
    return UrbanicityProfile(
        zip_code=zip_code,
        population=population,
        tier=tier,
        search_radius_m=radius_for_tier(tier),
        population_source=source,
    )


def _find_field(fieldnames: list[str], candidates: tuple[str, ...]) -> str | None:
    lower_map = {name.lower(): name for name in fieldnames}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return None


def _normalize_zip(value: Any) -> str | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) >= 5:
        return digits[:5]
    return None


def _parse_population(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
