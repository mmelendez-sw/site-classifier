"""Spatial + fuzzy deduplication against Salesforce site records."""

from __future__ import annotations

import math
import os
from typing import Any

from simple_salesforce import Salesforce

from dedupe.address_match import address_match_score, normalize_sf_address
from dedupe.constants import (
    ADDRESS_SCORE_WEIGHT,
    DEFAULT_RADIUS_METERS,
    DUPLICATE_THRESHOLD,
    FUZZY_PREFILTER_MAX_M,
    GEOCODER_COLLISION_MAX_ADDRESS,
    GEOCODER_COLLISION_MAX_M,
    POTENTIAL_DUPLICATE_MAX_DISTANCE_M,
    POTENTIAL_DUPLICATE_MIN_COMBINED,
    PROX_DUPLICATE_MAX_M,
    PROX_DUPLICATE_MIN_ADDRESS,
    PROX_REVIEW_EXTENDED_MAX_M,
    PROX_REVIEW_EXTENDED_MIN_ADDRESS,
    PROX_REVIEW_MAX_M,
    PROX_REVIEW_MIN_ADDRESS,
    PROXIMITY_SCORE_WEIGHT,
    REVIEW_THRESHOLD,
    SF_ADDRESS_FIELD,
    SF_LAT_FIELD,
    SF_LNG_FIELD,
    SF_ZIP_FIELD,
    STRONG_ADDRESS_DUPLICATE_MAX_M,
    STRONG_ADDRESS_DUPLICATE_MIN,
)
from dedupe.context import build_dataset_context
from dedupe.soql import build_dedupe_query
from dedupe.sf_geocode import enrich_missing_sf_coordinates, resolve_sf_coordinates
from dedupe.spatial import combined_score, haversine_meters, proximity_score
from dedupe.urbanicity import UrbanicityProfile, urbanicity_for_record


class SiteResolver:
    """Resolve incoming records against existing Salesforce sites."""

    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        username = os.environ["SF_USERNAME"]
        password = os.environ["SF_PASSWORD"]
        security_token = os.environ["SF_SECURITY_TOKEN"]
        domain = os.environ.get("SF_DOMAIN", "login")
        login_host = "test.salesforce.com" if domain == "test" else (
            "login.salesforce.com" if domain == "login" else f"{domain}.salesforce.com"
        )

        import logging
        logger = logging.getLogger(__name__)
        if verbose:
            logger.info("=" * 72)
            logger.info("SALESFORCE CONNECT")
            logger.info("  login host : https://%s", login_host)
            logger.info("  username   : %s", username)
            logger.info("  domain env : %s", domain)
            logger.info("  (.uat username → Salesforce routes to your UAT sandbox org)")
            logger.info("=" * 72)

        self.sf = Salesforce(
            username=username,
            password=password,
            security_token=security_token,
            domain=domain,
        )
        self._candidate_cache: list[dict[str, Any]] | None = None
        self._dataset_context: dict[str, Any] | None = None

        if verbose:
            logger.info(
                "Salesforce authenticated — API instance: https://%s",
                self.sf.sf_instance,
            )
            logger.info("All Site__c queries run against this org instance.")

    @staticmethod
    def build_bounding_box(
        lat: float, lng: float, meters: float = DEFAULT_RADIUS_METERS
    ) -> dict[str, float]:
        """Compute a ±meters lat/lng bounding box around a point."""
        delta_lat = meters / 111_320
        delta_lng = meters / (111_320 * math.cos(math.radians(lat)))
        return {
            "min_lat": lat - delta_lat,
            "max_lat": lat + delta_lat,
            "min_lng": lng - delta_lng,
            "max_lng": lng + delta_lng,
        }

    def prefetch(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Load Salesforce candidates for the full dataset zip codes + expanded bbox."""
        import logging
        logger = logging.getLogger(__name__)

        self._dataset_context = build_dataset_context(records)
        zip_codes = self._dataset_context["zip_codes"]
        bbox = self._dataset_context["bbox"]

        if self.verbose:
            logger.info("=" * 72)
            logger.info("SALESFORCE PREFETCH (bulk candidate query)")
            logger.info("  normalized records : %d", len(records))
            logger.info("  unique zip codes   : %d", len(zip_codes))
            if zip_codes:
                preview = ", ".join(zip_codes[:15])
                if len(zip_codes) > 15:
                    preview += f", ... (+{len(zip_codes) - 15} more)"
                logger.info("  zips               : %s", preview)
            if bbox:
                logger.info(
                    "  dataset bbox (+250m buffer): lat [%.5f, %.5f] lng [%.5f, %.5f]",
                    bbox["min_lat"],
                    bbox["max_lat"],
                    bbox["min_lng"],
                    bbox["max_lng"],
                )

        soql = build_dedupe_query(zip_codes or [], bbox)
        if self.verbose:
            logger.info("  SOQL: %s", soql)
            logger.info("  executing query...")

        self._candidate_cache = self.query_salesforce(zip_codes=zip_codes, bbox=bbox)
        enrich_missing_sf_coordinates(self._candidate_cache, verbose=self.verbose)

        if self.verbose:
            with_coords = sum(
                1 for row in self._candidate_cache if resolve_sf_coordinates(row) is not None
            )
            logger.info(
                "  returned %d Site__c rows (%d with coordinates for spatial matching)",
                len(self._candidate_cache),
                with_coords,
            )
            logger.info("=" * 72)

        return self._candidate_cache

    def query_salesforce(
        self,
        *,
        zip_codes: list[str] | None = None,
        bbox: dict[str, float] | None = None,
        soql: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return Salesforce site records for zip codes and/or a bounding box."""
        if soql is None:
            if zip_codes or bbox:
                soql = build_dedupe_query(zip_codes or [], bbox)
            else:
                raise ValueError("query_salesforce requires zip codes and/or a bounding box")

        try:
            result = self.sf.query(soql)
            return list(result.get("records") or [])
        except Exception as exc:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Salesforce SOQL query failed: %s", exc)
            logger.error("SOQL was: %s", soql)
            raise

    @staticmethod
    def fuzzy_match(
        incoming_address: str, sf_records: list[dict[str, Any]]
    ) -> tuple[int, dict[str, Any] | None]:
        """Score incoming address against candidates; return best score and record."""
        best_score = 0
        best_record: dict[str, Any] | None = None
        for record in sf_records:
            candidate = record.get(SF_ADDRESS_FIELD) or record.get("Name") or ""
            score = address_match_score(incoming_address, candidate)
            if score > best_score:
                best_score = score
                best_record = record
        return best_score, best_record

    @staticmethod
    def _normalize_zip(value: Any) -> str | None:
        if value is None:
            return None
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        if len(digits) >= 5:
            return digits[:5]
        return None

    @staticmethod
    def _prefilter_candidates(
        pool: list[dict[str, Any]],
        *,
        incoming_lat: float,
        incoming_lng: float,
        incoming_zip: str | None,
        max_distance_m: float,
    ) -> list[dict[str, Any]]:
        """Keep only nearby Salesforce rows (or same-zip rows missing coordinates)."""
        filtered: list[dict[str, Any]] = []
        for record in pool:
            resolved = resolve_sf_coordinates(record)
            if resolved is not None:
                lat, lng, _ = resolved
                if haversine_meters(incoming_lat, incoming_lng, lat, lng) <= max_distance_m:
                    filtered.append(record)
                continue

            matched_zip = SiteResolver._normalize_zip(record.get(SF_ZIP_FIELD))
            if incoming_zip and matched_zip and incoming_zip == matched_zip:
                filtered.append(record)

        return filtered

    @staticmethod
    def _score_candidate(
        incoming_address: str,
        incoming_lat: float,
        incoming_lng: float,
        sf_record: dict[str, Any],
        *,
        search_radius_m: float,
    ) -> dict[str, Any]:
        candidate_address = normalize_sf_address(
            sf_record.get(SF_ADDRESS_FIELD) or sf_record.get("Name") or ""
        )
        address_score = address_match_score(incoming_address, candidate_address)
        resolved = resolve_sf_coordinates(sf_record)

        if resolved is None:
            return {
                "record": sf_record,
                "address_score": address_score,
                "distance_m": None,
                "within_radius": False,
                "proximity_score": 0,
                "combined_score": address_score,
                "coordinate_source": "missing",
            }

        lat, lng, coordinate_source = resolved
        distance_m = haversine_meters(incoming_lat, incoming_lng, lat, lng)
        within_radius = distance_m <= search_radius_m
        prox = proximity_score(distance_m, search_radius_m) if within_radius else 0
        if address_score >= STRONG_ADDRESS_DUPLICATE_MIN:
            combined = address_score
        elif within_radius:
            combined = combined_score(
                address_score,
                prox,
                address_weight=ADDRESS_SCORE_WEIGHT,
                proximity_weight=PROXIMITY_SCORE_WEIGHT,
            )
        else:
            combined = address_score
        return {
            "record": sf_record,
            "address_score": address_score,
            "distance_m": distance_m,
            "within_radius": within_radius,
            "proximity_score": prox,
            "combined_score": combined,
            "coordinate_source": coordinate_source,
        }

    @staticmethod
    def _pick_best(candidates: list[dict[str, Any]], *, key: str) -> dict[str, Any] | None:
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[key])

    @staticmethod
    def _eligible_for_resolution(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Candidates that can influence duplicate/review/net-new status."""
        eligible: list[dict[str, Any]] = []
        for item in scored:
            distance_m = item.get("distance_m")
            address_score = item["address_score"]
            if distance_m is None:
                continue
            if item["within_radius"]:
                eligible.append(item)
                continue
            if (
                address_score >= STRONG_ADDRESS_DUPLICATE_MIN
                and distance_m <= STRONG_ADDRESS_DUPLICATE_MAX_M
            ):
                eligible.append(item)
                continue
            if (
                distance_m < GEOCODER_COLLISION_MAX_M
                and address_score < GEOCODER_COLLISION_MAX_ADDRESS
            ):
                eligible.append(item)
        return eligible

    @staticmethod
    def _pick_best_match(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item["address_score"],
                item["combined_score"],
                -(item.get("distance_m") or float("inf")),
            ),
        )

    @staticmethod
    def _status_from_combined_score(score: int) -> str:
        if score >= DUPLICATE_THRESHOLD:
            return "duplicate"
        if score >= REVIEW_THRESHOLD:
            return "review"
        return "net_new"

    @staticmethod
    def _resolve_match_status(match: dict[str, Any]) -> tuple[str, int, str | None]:
        """Apply geocoder-collision, strong-address, proximity, and score thresholds."""
        combined = match["combined_score"]
        address_score = match["address_score"]
        distance_m = match.get("distance_m")

        if (
            distance_m is not None
            and distance_m < GEOCODER_COLLISION_MAX_M
            and address_score < GEOCODER_COLLISION_MAX_ADDRESS
        ):
            return "review", combined, "geocoder_collision"

        if address_score >= STRONG_ADDRESS_DUPLICATE_MIN and (
            distance_m is None or distance_m <= STRONG_ADDRESS_DUPLICATE_MAX_M
        ):
            return "duplicate", max(combined, address_score), "high_address_match"

        if not match.get("within_radius"):
            return "net_new", combined, None

        if distance_m is not None:
            if distance_m <= PROX_DUPLICATE_MAX_M and address_score >= PROX_DUPLICATE_MIN_ADDRESS:
                return "duplicate", combined, f"<= {int(PROX_DUPLICATE_MAX_M)}m addr>={PROX_DUPLICATE_MIN_ADDRESS}"
            if distance_m <= PROX_REVIEW_MAX_M and address_score >= PROX_REVIEW_MIN_ADDRESS:
                return "review", combined, f"<= {int(PROX_REVIEW_MAX_M)}m addr>={PROX_REVIEW_MIN_ADDRESS}"
            if (
                distance_m <= PROX_REVIEW_EXTENDED_MAX_M
                and address_score >= PROX_REVIEW_EXTENDED_MIN_ADDRESS
            ):
                return (
                    "review",
                    combined,
                    f"<= {int(PROX_REVIEW_EXTENDED_MAX_M)}m addr>={PROX_REVIEW_EXTENDED_MIN_ADDRESS}",
                )

        status = SiteResolver._status_from_combined_score(combined)
        return status, combined, None

    @staticmethod
    def is_potential_duplicate(
        *,
        status: str,
        match: dict[str, Any] | None,
    ) -> bool:
        if status != "net_new" or match is None:
            return False
        if not match.get("within_radius"):
            return False
        distance_m = match.get("distance_m")
        if distance_m is None or distance_m > POTENTIAL_DUPLICATE_MAX_DISTANCE_M:
            return False
        return match["combined_score"] >= POTENTIAL_DUPLICATE_MIN_COMBINED

    @staticmethod
    def _build_resolution_detail(
        *,
        urbanicity: UrbanicityProfile,
        spatial_candidate_count: int,
        prefilter_count: int,
        match: dict[str, Any] | None,
        status: str,
        proximity_rule: str | None,
    ) -> str:
        radius = int(urbanicity.search_radius_m)
        pop = urbanicity.population
        pop_text = f"{pop:,}" if pop is not None else "unknown"
        if match is None:
            return (
                f"{urbanicity.tier} zip population={pop_text} radius={radius}m "
                f"prefilter={prefilter_count} spatial_candidates=0/{spatial_candidate_count}; "
                f"no in-radius Salesforce match"
            )

        distance_text = (
            f"{match['distance_m']:.0f}m"
            if match.get("distance_m") is not None
            else "no_coordinates"
        )
        coord_source = match.get("coordinate_source") or "missing"
        detail = (
            f"{urbanicity.tier} zip population={pop_text} radius={radius}m "
            f"prefilter={prefilter_count} spatial_candidates={spatial_candidate_count}; "
            f"address_score={match['address_score']} proximity_score={match['proximity_score']} "
            f"combined_score={match['combined_score']} distance={distance_text} "
            f"coord_source={coord_source}"
        )
        if proximity_rule:
            detail += f"; proximity_rule={proximity_rule}"
        detail += f"; status={status}"
        return detail

    @staticmethod
    def _proximity_rule_label(proximity_rule: str | None) -> str | None:
        return proximity_rule

    def resolve(
        self,
        record: dict[str, Any],
        candidates: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run urbanicity-radius spatial gate + fuzzy dedupe and return status."""
        address = record["address"]
        incoming_lat = float(record["lat"])
        incoming_lng = float(record["lng"])
        incoming_zip = self._normalize_zip(record.get("zip_code"))
        urbanicity = urbanicity_for_record(record)

        pool = candidates if candidates is not None else self._candidate_cache
        if pool is None:
            raise RuntimeError(
                "Call prefetch() with the full dataset before resolve(). "
                "Dedupe uses one expanded bounding box from the dataset min/max "
                "lat/lng, not a per-site radius."
            )

        prefilter_max_m = max(urbanicity.search_radius_m, float(FUZZY_PREFILTER_MAX_M))
        filtered_pool = self._prefilter_candidates(
            pool,
            incoming_lat=incoming_lat,
            incoming_lng=incoming_lng,
            incoming_zip=incoming_zip,
            max_distance_m=prefilter_max_m,
        )

        scored = [
            self._score_candidate(
                address,
                incoming_lat,
                incoming_lng,
                sf_record,
                search_radius_m=urbanicity.search_radius_m,
            )
            for sf_record in filtered_pool
        ]
        in_radius = [item for item in scored if item["within_radius"]]
        spatial_candidate_count = len(in_radius)
        eligible = self._eligible_for_resolution(scored)
        match = self._pick_best_match(eligible)

        if match is not None:
            status, score, proximity_rule = self._resolve_match_status(match)
        else:
            score = 0
            status = "net_new"
            proximity_rule = None

        potential_duplicate = self.is_potential_duplicate(status=status, match=match)
        matched_record = match["record"] if match else None
        resolution_detail = self._build_resolution_detail(
            urbanicity=urbanicity,
            spatial_candidate_count=spatial_candidate_count,
            prefilter_count=len(filtered_pool),
            match=match,
            status=status,
            proximity_rule=proximity_rule,
        )

        if self.verbose:
            import logging
            logger = logging.getLogger(__name__)
            matched = matched_record or {}
            matched_addr = matched.get(SF_ADDRESS_FIELD) or matched.get("Name") or "—"
            logger.info(
                "    urbanicity : %s (zip=%s pop=%s radius=%sm)",
                urbanicity.tier,
                urbanicity.zip_code or "—",
                f"{urbanicity.population:,}" if urbanicity.population else "unknown",
                int(urbanicity.search_radius_m),
            )
            logger.info(
                "    candidates : %d prefetched, %d within %dm prefilter, %d within radius",
                len(pool),
                len(filtered_pool),
                int(prefilter_max_m),
                spatial_candidate_count,
            )
            if match:
                dist = (
                    f"{match['distance_m']:.0f}m"
                    if match.get("distance_m") is not None
                    else "no_coordinates"
                )
                logger.info(
                    "    best match : %s | %s (coords=%s)",
                    matched.get("Id", "—"),
                    matched_addr[:80],
                    match.get("coordinate_source", "missing"),
                )
                logger.info(
                    "    scores     : address=%s proximity=%s combined=%s distance=%s",
                    match["address_score"],
                    match["proximity_score"],
                    match["combined_score"],
                    dist,
                )
            if potential_duplicate:
                logger.info("    flag       : potential_duplicate (manual calibration)")
            logger.info("    result     : %s — %s", status.upper(), resolution_detail)

        return {
            "status": status,
            "score": score,
            "address_score": match["address_score"] if match else 0,
            "combined_score": match["combined_score"] if match else 0,
            "proximity_score": match["proximity_score"] if match else 0,
            "matched_distance_m": match["distance_m"] if match else None,
            "matched_coordinate_source": match.get("coordinate_source") if match else None,
            "matched_record": matched_record,
            "candidate_count": len(pool),
            "spatial_candidate_count": spatial_candidate_count,
            "prefilter_candidate_count": len(filtered_pool),
            "urbanicity": urbanicity.as_dict(),
            "resolution_detail": resolution_detail,
            "potential_duplicate": potential_duplicate,
            "dataset_context": self._dataset_context,
        }
