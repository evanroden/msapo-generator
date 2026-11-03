# Monthly upload routes and limits

This is an implementation inventory for issue #472, based on main
`fe051571da209e29f16e2b37cb9fe1eec60c924b` and its route-guidance follow-up.
It does not increase any limit or certify realistic-size files under #471.
A chooser's maximum is only the largest supported file-type admission ceiling;
parsing, artwork interpretation, page inclusion and report totals are separate.
All byte labels use binary units: 1 MiB = 1,048,576 bytes.

| Route | Original-file admission | Separate processing constraints |
| --- | --- | --- |
| Starting Report and advanced DOCX import | DOCX: 128 MiB | Expanded package: 256 MiB; individual member: 64 MiB; XML part: 32 MiB; total XML: 64 MiB; selected prepared images: 60 MiB. |
| Starting Report artwork interpretation | Independent 24 MiB source envelope | A file admitted by the DOCX importer can exceed this envelope. Existing template/cover-design recovery remains available; this is not proof of damaged artwork. |
| Monthly evidence, section-local evidence and structured source intake | DOCX: 128 MiB; other supported formats: 30 MiB | PDF: 500 pages; extracted text: 400,000 characters per source. XLSX: 2,000 package parts, 80 MiB expanded, 32 MiB per part, 30 worksheets, 20,000 rows per sheet and 200,000 cells total; existing column and image-pixel limits also apply. |
| Capacity source intake | DOCX: 128 MiB; other supported formats: 30 MiB | XLSX admission is the smaller of its directory-reader cap and shared-original cap. Capacity review: 100 extracted pages/items, 100 tables, 5,000 rows and 50,000 cells. XLSX uses the existing sparse directory reader: 80 MiB expanded and 16 MiB per part, with its additional token/cell limits unchanged. |
| Shared template shelf | DOCX: 512 MiB for unchanged storage | Storage is not report-import capability. Saving does not install a master or change an existing report. Existing shelf package validation still applies. |

Evidence report totals are separately limited to 50 sources and 180 MiB of
originals (including email attachments), 800,000 extracted characters, and 150
embedded image/PDF pages. Prepared report-image and optional OCR/vision budgets
remain separate from original-file size; the displayed vision count follows the
existing source configuration. A file-size pass is not page approval or a promise
that the full document fits the remaining report.

## Source of truth

- `monthly_report_import.py`: DOCX admission and package/XML/image budgets.
- `monthly_report_compatibility_view.py`: Word-artwork source envelope.
- `monthly_report_sources.py`: shared source admission, batch totals and evidence XLSX parsing.
- `monthly_report_capacity.py` / `monthly_report_directory.py`: capacity admission and sparse-workbook review.
- `monthly_report_shared_templates.py`: template storage.
- `monthly_report_upload_limits.py` / `monthly_report_upload_guidance.py`: exact labels and route-specific chooser/help values derived from these constants.

The upload keys, saved source identities, source selection, page review, standing
capacity revisions and original-byte storage are unchanged. Errors distinguish
empty/unsupported inputs, file-type size, PDF page count, source/report text,
report count/bytes, and evidence workbook package limits. Failed batch siblings
must not remove already accepted originals; a fitting retry uses the existing
batch workflow.

## Verification boundaries

Synthetic tests lower selected configuration limits to exercise below, exact and
above boundaries without allocating maximum-size fixtures. They also inspect real
synthetic DOCX/XLSX/PDF inputs, native Streamlit uploader metadata, rerun identity,
retained siblings and retry behavior. These tests do not establish peak resource
usage for real large reports, browser pointer/touch behavior, complete native Word
artwork fidelity or served output acceptance. Those remain with #471, #462 and the
existing acceptance issues. Lower-level DOCX, directory and image-parser error
wording not changed in this follow-up remains outside its claimed coverage.
