# Monthly report assembly boundary and reproducibility acceptance

**Issue:** #498 (MR-030). **Status:** Engineering contract and synthetic regression coverage; not the final served/client acceptance under #304. This is a decision record for the current implementation, not an owner-approved decision that all project variants have passed.

## Existing implementation (verified against source paths)

1. **Source intake and interpretation:** `monthly_report_sources.ingest` and the specialized DOCX/PDF/CSV readers inspect originals into bounded source records and table/page evidence. Optional interpretation or AI can suggest text, facts or destination choices. A suggestion is not an approved report statement.
2. **Review and source provenance:** `ReportDraft` stores selected `ResolvedBlock` values, editable rows/tables, asset hashes/captions, references and included `ReportFollowUp` records. Source evidence has immutable identifiers/fingerprints and physical page/item references. A manual correction changes the accepted draft; it is not reconstructed from a fresh model response on export.
3. **Saved state:** Browser recovery and shared report snapshot are separate durability paths. Saving and reopening must retain the canonical draft, its source/asset provenance and deliberate omissions. Do not treat a file's classification, mere upload or stale AI proposal as permission to change confirmed rows.
4. **Deterministic assembly:** `assemble_docx` performs preflight and acknowledgment checks before building Word content from the selected draft and pinned native design (or the generic fallback). `generate_report` then prepares the Word package and derives the PDF using the configured converter. This path does **not** require a new source-reader or model answer for each generation. PDF conversion and package timestamps can differ at the byte level without changing the intended content.

## Added bounded validation

`app/monthly_report_reproducibility.py` is an **audit helper**, not an alternate writer, an upload/reimport path or a new user-facing approval. Normal generation remains one-pass.

- `canonical_input_manifest` records the report identity/period, **actual SHA-256 of the pinned Word template/shell**, active sections in output order with their visible numbers, block schema and accepted values, used source fingerprints, included issue/proposal cards, divider/cover assets and their content-addressed hashes when an asset loader is provided.
- `canonical_docx_manifest` reads the generated Word package and records ordered paragraph text, styles, page/section breaks, native table cell text/merges, body/header/footer picture relationships/geometry and media hashes. It deliberately ignores ZIP timestamps, core-property metadata, volatile OOXML IDs and unused source file contents. It does not assert that two Word ZIP files must have identical raw bytes.
- `verify_repeated_assembly` performs **two** gated Word generations for testing, compares the input snapshots before/after and compares semantic Word outputs. A mismatch fails the review test without replacing any saved version or silently retrying interpretation.
- The focused regression suite runs three independently constructed synthetic variants (single facility, multi-site with optional omissions, and a regional report with an approved table and image). It also checks a changed row, content-blind package timestamps, unselected source proposals, selected source fingerprints, and an optional two-pass real Word/PDF conversion using LibreOffice.

This is a *structural/content* comparison. It cannot establish pixel-perfect brand geometry, correct visible two-digit divider clipping, fully supported OCR, perfect cross-software pagination, or the authoritative final UMMC report's fidelity. Those remain separately gated.

## Proposed acceptance / future changes

- A report stored under a named contract/site/month and pinned design must always give the same visible section order, selected content, page references and graphic placement semantics on repeated generation from that unchanged state. If the input or template changes while rendering, report the stale state instead of publishing it as current.
- Reader proposals should be reviewable, source-bound and replaceable. Unknown/missing/site-ambiguous fields are not filled automatically; a failed reader must not erase human-authored entries.
- Preserve financial/price exclusions, site scope, source identities and existing edit conflict checks. No new hosted model, OCR, paid provider or automatic background interpretation is approved in this issue.
- Actual served acceptance still requires a saved/reopened report, a known source/template revision, two real downloaded DOCX/PDF results, comparisons of the output semantic manifest plus representative rendered pages, and explicit review of any differences. Test all relevant native/source variants independently; do not extrapolate from the three synthetic examples to the roughly 36 discussed project variants.
- Any future automatic use of these manifests in production must have a bounded CPU/memory policy and must **never** log or publish client source text. This PR introduces no telemetry of report content.

## Coordination

#476 provides a separate normalized work-order review contract; #277 and #285 retain source-grounding controls; #304 owns full cross-section output acceptance. #460 handles truthful contents pagination, not this semantic comparison. This contract does not change their source or rendering code.
