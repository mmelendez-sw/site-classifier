"""Upload Site__c records from an sf_upload.csv template file (one row at a time)."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from salesforce.field_map import OBJECT_NAME
from salesforce.sf_client import SalesforceClient, map_upload_record_to_payload
from salesforce.upload_template import (
    UPLOAD_CSV_COLUMNS,
    csv_row_to_upload_record,
    validate_upload_record,
)

load_dotenv()
logger = logging.getLogger(__name__)


def load_upload_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"No rows found in {path}")
    missing = [col for col in UPLOAD_CSV_COLUMNS if col not in rows[0]]
    if missing:
        raise ValueError(f"CSV missing template columns: {', '.join(missing)}")
    return rows


def upload_from_csv(
    input_path: Path,
    *,
    dry_run: bool = False,
    verbose: bool = True,
    start: int = 1,
    limit: int | None = None,
    log_path: Path | None = None,
) -> dict[str, int]:
    rows = load_upload_csv(input_path)
    if start < 1:
        raise ValueError("--start must be >= 1")
    slice_start = start - 1
    slice_end = slice_start + limit if limit is not None else None
    selected = rows[slice_start:slice_end]
    if not selected:
        raise ValueError("No rows selected — check --start / --limit")

    summary = {"total": len(selected), "loaded": 0, "skipped": 0, "errors": 0}
    log_rows: list[dict[str, Any]] = []
    client = None if dry_run else SalesforceClient()

    if verbose:
        logger.info("=" * 72)
        logger.info(
            "SALESFORCE CSV UPLOAD — %d row(s) from %s%s",
            len(selected),
            input_path.name,
            " (DRY-RUN)" if dry_run else "",
        )
        logger.info("  object: %s", OBJECT_NAME)
        logger.info("=" * 72)

    for index, row in enumerate(selected, start=start):
        street = (row.get("Site Street") or "").strip()
        city = (row.get("Site City") or "").strip()
        label = f"{street}, {city}" if city else street
        try:
            record = csv_row_to_upload_record(row)
            errors = validate_upload_record(record)
            if errors:
                raise ValueError("; ".join(errors[:5]))

            if verbose:
                logger.info(
                    "[%d/%d] %s",
                    index - start + 1,
                    len(selected),
                    label,
                )
                logger.info(
                    "         type=%s morphology=%s carrier=%s",
                    row.get("Site Type") or "—",
                    row.get("Morphology") or "—",
                    row.get("Carrier Leasing Source") or "—",
                )

            sf_id = ""
            if dry_run:
                payload = map_upload_record_to_payload(record)
                if verbose:
                    logger.info("  dry-run OK — would create with %d fields", len(payload))
            else:
                assert client is not None
                result = client.create_site(record, verbose=verbose)
                sf_id = str(result.get("id") or "")
                summary["loaded"] += 1
                logger.info("  created Site__c Id=%s", sf_id)

            log_rows.append(
                {
                    "row": index,
                    "site_street": street,
                    "site_city": city,
                    "site_type": row.get("Site Type"),
                    "status": "dry_run" if dry_run else "created",
                    "salesforce_id": sf_id,
                    "error": "",
                }
            )
        except Exception as exc:
            summary["errors"] += 1
            logger.error("  FAILED: %s", exc)
            log_rows.append(
                {
                    "row": index,
                    "site_street": street,
                    "site_city": city,
                    "site_type": row.get("Site Type"),
                    "status": "error",
                    "salesforce_id": "",
                    "error": str(exc),
                }
            )

    target_log = log_path or input_path.with_name(
        f"{input_path.stem}_upload_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    with target_log.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["row", "site_street", "site_city", "site_type", "status", "salesforce_id", "error"],
        )
        writer.writeheader()
        writer.writerows(log_rows)

    if verbose:
        logger.info("=" * 72)
        logger.info(
            "Upload complete — loaded=%d errors=%d log=%s",
            summary["loaded"],
            summary["errors"],
            target_log.resolve(),
        )
        logger.info("=" * 72)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload Site__c records from sf_upload.csv one row at a time"
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to sf_upload.csv (Salesforce upload template columns)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate rows and show payloads without calling Salesforce",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Minimal logging",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="1-based row number to start from (default: 1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of rows to upload",
    )
    parser.add_argument(
        "--log",
        help="Optional path for upload log CSV",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    upload_from_csv(
        Path(args.input),
        dry_run=args.dry_run,
        verbose=not args.quiet,
        start=args.start,
        limit=args.limit,
        log_path=Path(args.log) if args.log else None,
    )


if __name__ == "__main__":
    main()
