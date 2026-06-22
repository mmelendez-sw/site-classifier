# Salesforce upload preview (dry-run)

Generated: 2026-06-22T15:00:58

## Summary

- Classified rows reviewed: **47**
- Upload candidates (`net_new`): **47**
- Skipped (not net_new): **0**
- Validation failures: **0**

## Site type mapping

- Rooftop: 44
- Self Support / Lattice Tower: 3

## Output files

| File | Purpose |
|------|---------|
| `sf_upload.csv` | Manual Data Loader template (same columns as production) |
| `sf_upload_picklists.txt` | Valid picklist values for review |
| `sf_upload_validation.csv` | Per-row dedupe status + validation |
| `sf_upload_payload.json` | Spoofed `Site__c.create()` payloads (no API call) |

## Live upload path

1. Dedupe marks rows `net_new` in `dedupe_results.csv`
2. Classifier fills `site_type`, confidence, equipment
3. `build_upload_record()` maps to template columns
4. Non-dry-run orchestrator calls `SalesforceClient.create_site()` per net-new row

This preview performs steps 3–4 mapping only — **nothing is written to Salesforce**.
