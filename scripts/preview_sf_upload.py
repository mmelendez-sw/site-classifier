"""Preview Salesforce upload from classifier + optional dedupe outputs (no SF writes)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dedupe.urbanicity import urbanicity_for_record
from salesforce.field_map import FIELD_MAP, OBJECT_NAME
from salesforce.sf_client import map_upload_record_to_payload
from salesforce.upload_template import (
    build_upload_record,
    upload_record_to_csv_row,
    validate_upload_record,
    write_upload_csv,
)


def _load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _norm_addr(value: Any) -> str:
    return str(value or "").strip().upper()


def _index_dedupe_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_id = {str(row.get("id", "")).strip(): row for row in rows if row.get("id")}
    by_addr = {_norm_addr(row.get("address")): row for row in rows if row.get("address")}
    return by_id, by_addr


def _classified_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "site_type": row.get("site_type"),
        "tower_subtype": row.get("tower_subtype"),
        "site_confidence": row.get("site_confidence"),
        "cell_equipment": row.get("cell_equipment"),
        "source_url": row.get("source_url"),
    }


def _canonical_from_classify(row: dict[str, Any]) -> dict[str, Any]:
    lng = row.get("lng")
    if lng is None:
        lng = row.get("lon")
    return {
        "id": row.get("id"),
        "address": row.get("address") or row.get("input_address"),
        "lat": row.get("lat"),
        "lng": lng,
    }


def _dedupe_row_for_record(
    record: dict[str, Any],
    *,
    dedupe_by_id: dict[str, dict[str, Any]],
    dedupe_by_addr: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    site_id = str(record.get("id") or "").strip()
    if site_id and site_id in dedupe_by_id:
        return dedupe_by_id[site_id]
    addr = _norm_addr(record.get("address"))
    if addr and addr in dedupe_by_addr:
        return dedupe_by_addr[addr]
    urbanicity = urbanicity_for_record(record).as_dict()
    return {
        "status": "net_new",
        "zip_code": urbanicity.get("zip_code"),
        "urbanicity_tier": urbanicity.get("urbanicity_tier"),
        "zip_population": urbanicity.get("zip_population"),
    }


def build_preview_bundle(
    classify_rows: list[dict[str, Any]],
    *,
    dedupe_rows: list[dict[str, Any]] | None = None,
    assume_net_new: bool = False,
    upload_when: datetime | None = None,
) -> dict[str, Any]:
    dedupe_by_id: dict[str, dict[str, Any]] = {}
    dedupe_by_addr: dict[str, dict[str, Any]] = {}
    if dedupe_rows:
        dedupe_by_id, dedupe_by_addr = _index_dedupe_rows(dedupe_rows)

    preview_rows: list[dict[str, Any]] = []
    upload_records: list[dict[str, Any]] = []

    for classify in classify_rows:
        canonical = _canonical_from_classify(classify)
        dedupe_row = _dedupe_row_for_record(
            canonical,
            dedupe_by_id=dedupe_by_id,
            dedupe_by_addr=dedupe_by_addr,
        )
        status = (dedupe_row.get("status") or "").lower()
        if not status and assume_net_new:
            status = "net_new"
        if status != "net_new":
            preview_rows.append(
                {
                    "id": canonical.get("id"),
                    "address": canonical.get("address"),
                    "dedupe_status": status or "unknown",
                    "included_in_upload": False,
                    "reason": f"dedupe status={status or 'unknown'}",
                }
            )
            continue

        upload_record = build_upload_record(
            canonical,
            classified=_classified_row(classify),
            dedupe_row=dedupe_row,
            upload_when=upload_when,
        )
        csv_row = upload_record_to_csv_row(upload_record)
        validation_errors = validate_upload_record(upload_record)
        sf_payload = map_upload_record_to_payload(upload_record)

        preview_rows.append(
            {
                "id": canonical.get("id"),
                "address": canonical.get("address"),
                "dedupe_status": status,
                "included_in_upload": True,
                "site_type_classifier": classify.get("site_type"),
                "site_type_upload": csv_row.get("Site Type"),
                "site_confidence": classify.get("site_confidence"),
                "cell_equipment": classify.get("cell_equipment"),
                "morphology": csv_row.get("Morphology"),
                "carrier_leasing_source": csv_row.get("Carrier Leasing Source"),
                "validation_ok": not validation_errors,
                "validation_errors": "; ".join(validation_errors),
            }
        )
        upload_records.append(
            {
                "id": canonical.get("id"),
                "address": canonical.get("address"),
                "dedupe_status": status,
                "upload_record": upload_record,
                "csv_row": csv_row,
                "sf_object": OBJECT_NAME,
                "sf_payload": sf_payload,
                "field_map": FIELD_MAP,
                "validation_errors": validation_errors,
            }
        )

    return {
        "preview_rows": preview_rows,
        "upload_records": upload_records,
        "summary": _summarize(preview_rows, upload_records),
    }


def _summarize(
    preview_rows: list[dict[str, Any]],
    upload_records: list[dict[str, Any]],
) -> dict[str, Any]:
    skipped = [row for row in preview_rows if not row.get("included_in_upload")]
    invalid = [row for row in preview_rows if row.get("included_in_upload") and not row.get("validation_ok")]
    site_types: dict[str, int] = {}
    for row in preview_rows:
        if row.get("included_in_upload"):
            key = row.get("site_type_upload") or "(blank)"
            site_types[key] = site_types.get(key, 0) + 1
    return {
        "classified_rows": len(preview_rows),
        "upload_candidates": len(upload_records),
        "skipped_non_net_new": len(skipped),
        "validation_failures": len(invalid),
        "site_type_counts": site_types,
    }


def write_preview_outputs(bundle: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    upload_dicts = [item["upload_record"] for item in bundle["upload_records"]]
    paths["sf_upload"] = write_upload_csv(upload_dicts, output_dir / "sf_upload.csv")

    validation_path = output_dir / "sf_upload_validation.csv"
    with validation_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "id",
            "address",
            "dedupe_status",
            "included_in_upload",
            "site_type_classifier",
            "site_type_upload",
            "site_confidence",
            "cell_equipment",
            "morphology",
            "carrier_leasing_source",
            "validation_ok",
            "validation_errors",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(bundle["preview_rows"])
    paths["validation"] = validation_path

    payload_path = output_dir / "sf_upload_payload.json"
    payload_path.write_text(
        json.dumps(bundle["upload_records"], indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    paths["payload"] = payload_path

    manifest_path = output_dir / "UPLOAD_PREVIEW.md"
    summary = bundle["summary"]
    lines = [
        "# Salesforce upload preview (dry-run)",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Classified rows reviewed: **{summary['classified_rows']}**",
        f"- Upload candidates (`net_new`): **{summary['upload_candidates']}**",
        f"- Skipped (not net_new): **{summary['skipped_non_net_new']}**",
        f"- Validation failures: **{summary['validation_failures']}**",
        "",
        "## Site type mapping",
        "",
    ]
    for site_type, count in sorted(summary["site_type_counts"].items()):
        lines.append(f"- {site_type}: {count}")
    lines.extend(
        [
            "",
            "## Output files",
            "",
            "| File | Purpose |",
            "|------|---------|",
            "| `sf_upload.csv` | Manual Data Loader template (same columns as production) |",
            "| `sf_upload_picklists.txt` | Valid picklist values for review |",
            "| `sf_upload_validation.csv` | Per-row dedupe status + validation |",
            "| `sf_upload_payload.json` | Spoofed `Site__c.create()` payloads (no API call) |",
            "",
            "## Live upload path",
            "",
            "1. Dedupe marks rows `net_new` in `dedupe_results.csv`",
            "2. Classifier fills `site_type`, confidence, equipment",
            "3. `build_upload_record()` maps to template columns",
            "4. Non-dry-run orchestrator calls `SalesforceClient.create_site()` per net-new row",
            "",
            "This preview performs steps 3–4 mapping only — **nothing is written to Salesforce**.",
        ]
    )
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    paths["manifest"] = manifest_path
    return paths


def preview_from_files(
    classify_detail: Path,
    *,
    dedupe_csv: Path | None = None,
    output_dir: Path | None = None,
    assume_net_new: bool = False,
) -> tuple[dict[str, Any], dict[str, Path]]:
    classify_rows = _load_csv(classify_detail)
    dedupe_rows = _load_csv(dedupe_csv) if dedupe_csv else None
    target_dir = output_dir or classify_detail.parent / "sf_upload_preview"
    bundle = build_preview_bundle(
        classify_rows,
        dedupe_rows=dedupe_rows,
        assume_net_new=assume_net_new or dedupe_rows is None,
    )
    paths = write_preview_outputs(bundle, target_dir)
    return bundle, paths


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preview Salesforce upload CSV + API payloads from classifier output"
    )
    parser.add_argument(
        "--classify-detail",
        required=True,
        help="Classifier results_detail CSV (e.g. runs/.../WI_results_detail.csv)",
    )
    parser.add_argument(
        "--dedupe",
        help="Optional dedupe_results.csv — only net_new rows are included",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory (default: sf_upload_preview beside classify detail)",
    )
    parser.add_argument(
        "--assume-net-new",
        action="store_true",
        help="Treat all classified rows as net_new when dedupe CSV is omitted",
    )
    args = parser.parse_args()

    bundle, paths = preview_from_files(
        Path(args.classify_detail),
        dedupe_csv=Path(args.dedupe) if args.dedupe else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        assume_net_new=args.assume_net_new,
    )
    summary = bundle["summary"]
    print(f"Wrote preview to {paths['sf_upload'].parent.resolve()}")
    print(
        f"Upload candidates: {summary['upload_candidates']} | "
        f"skipped: {summary['skipped_non_net_new']} | "
        f"validation failures: {summary['validation_failures']}"
    )
    print(f"  sf_upload.csv           -> {paths['sf_upload'].name}")
    print(f"  sf_upload_validation.csv")
    print(f"  sf_upload_payload.json")
    print(f"  UPLOAD_PREVIEW.md")


if __name__ == "__main__":
    main()
