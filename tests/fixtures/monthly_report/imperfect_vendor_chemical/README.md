# Imperfect synthetic vendor and water-treatment reports

This folder contains **fully fictional** PDF/DOCX evidence for testing the ENFRA Monthly Report importer. It is safe for the public repository: no authentic customer reports, contact lists, vendor scans, or customer artwork are included.

## Files and reproducibility

- `runtime/qa_fixtures/ENFRA_Synthetic_Imperfect_Vendor_Chemical_QA_Pack.zip` — the one immutable, runtime-shipped archive (four DOCX, five PDF, generator and instructions). The checked-in manifest and regeneration script in this documentation folder are kept out of the production image.
- `MANIFEST.json` — original file SHA-256 hashes, page counts, scenario identifiers and expected inclusion/exclusion decisions.
- `generate_fixtures.py` — source to regenerate the sample documents locally. Run it from a **disposable working directory** after copying the script there, or extract the included script and run `python generate_fixtures.py`. It needs python-docx, Pillow, PyMuPDF and LibreOffice CLI. Its output depends on the installed fonts/renderer; checked-in binary fixture hashes in MANIFEST are authoritative.

The checked-in ZIP SHA-256 is `c767124fb922445ced29c07de7755567f3adf6945b2218021584aa8f325c627f`. It is immutable source evidence for synthetic tests; don't edit or repackage it silently.

## Scenarios

| File stem | Fictional scope | Deliberate issues and expected treatment |
| --- | --- | --- |
| `QA_Vendor_Service_MixedPages` | Demo North | Page 1 has valid inspection findings; page 2 is blank, 3 is legal-only, 4 signature-only and 5 contains unapproved prices. Do not treat an unperformed quoted repair as completed. |
| `QA_Water_Treatment_MixedPages` | Demo North | Pages 1–2 contain readings and a chart that must survive; 3 legal, 4 signature and 5 blank must stay out. Above-limit chlorides and pending culture must not become compliant/negative findings. |
| `QA_Vendor_AmbiguousDate` | Demo North | An invalid completion date and planned work must not create a completed work order. |
| `QA_Chemical_DifferentSite` | Demo South | Site-isolation test: no foreign measurements, asset identities or artwork in a Demo North report; separate priced/blank pages remain excluded. |
| `QA_Water_Treatment_ImageOnlyScan.pdf` | Demo North | Technical page 1 has no extractable text and requires visual/OCR or source recovery; page 2 is blank. No silent approval or content omission. |

The numbered pages above refer to **rendered PDFs**. DOCX ingestion may expose document items rather than identical page numbers; use source IDs and actual observed item structure.

## How to test

Unzip the pack to a disposable QA folder. For each independent scenario, upload the **real binary fixture** via the normal monthly evidence importer in a synthetic QA namespace rather than inserting hand-coded results. Select Demo North/September 2026 unless the scenario specifies otherwise. Verify page classifications, source lineage, site scope, idempotence, deliberate exclusion persistence across refresh, and final Word/PDF output.

Vendor contractor work belongs in **Monthly Activity Summary**, not ENFRA-only onsite calls. Chemical findings and relevant images belong in **Water Treatment**. No client output may include blank, price-bearing, legal-only or signature-only pages. Unknown or image-only content must remain explicitly reviewable and never be silently discarded. A test may verify that a previously reported defect is still present; do not relabel a failing expectation to produce a pass.

This pack supplements the existing 18-of-18 deterministic synthetic fixture. It **does not** demonstrate acceptance of authentic UMMC/Unity/USH reports or Word/Adobe visual parity. Do not commit authentic reports into this folder or expose them through public test URLs.

This repository change only stores fixtures; it does not enable a fixture-picker UI, external AI reading, authentication or Render storage changes.
