"""Tests for Salesforce upload preview script."""

from datetime import datetime
from pathlib import Path

from scripts.preview_sf_upload import build_preview_bundle, preview_from_files


def test_build_preview_bundle_assumes_net_new(tmp_path: Path):
    classify = tmp_path / "detail.csv"
    classify.write_text(
        "id,address,lat,lon,site_type,site_confidence,cell_equipment\n"
        'wi_001,"100 E PLEASANT ST, MILWAUKEE, WI 53212",43.05,-87.91,rooftop,0.8,True\n',
        encoding="utf-8",
    )
    bundle, paths = preview_from_files(classify, assume_net_new=True)
    assert bundle["summary"]["upload_candidates"] == 1
    assert paths["sf_upload"].exists()
    assert paths["payload"].exists()
    payload = paths["payload"].read_text(encoding="utf-8")
    assert "Site_Type__c" in payload
    assert "Rooftop" in payload


def test_build_preview_bundle_skips_non_net_new():
    bundle = build_preview_bundle(
        [
            {
                "id": "wi_001",
                "address": "100 E PLEASANT ST, MILWAUKEE, WI 53212",
                "lat": 43.05,
                "lon": -87.91,
                "site_type": "rooftop",
                "site_confidence": 0.8,
                "cell_equipment": True,
            }
        ],
        dedupe_rows=[
            {
                "id": "wi_001",
                "address": "100 E PLEASANT ST, MILWAUKEE, WI 53212",
                "status": "duplicate",
            }
        ],
        upload_when=datetime(2026, 6, 18),
    )
    assert bundle["summary"]["upload_candidates"] == 0
    assert bundle["summary"]["skipped_non_net_new"] == 1
