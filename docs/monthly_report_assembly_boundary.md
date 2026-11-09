# Monthly report assembly boundary and reproducibility acceptance

**Issue:** #498 (MR-030). **Status:** Engineering contract and synthetic regression coverage; final served/client acceptance remains under #304. Recovered from inactive #540 against main `1c8001ca6f4034bb03d847dd8709acd833cf33da`. This record does not approve an AI-only or hybrid architecture or certify every project variant.

## Existing implementation (verified against source paths)

1. **Source intake and interpretation:** `monthly_report_sources.ingest` and the specialized DOCX/PDF/CSV readers inspect originals into bounded source records and table/page evidence. Optional interpretation or AI can suggest text, facts or destination choices. A suggestion is not an approved report statement.
2. **Review and source provenance:** `ReportDraft` stores selected `ResolvedBlock` values, editable rows/tables, asset hashes/captions, references and included `ReportFollowUp` records. Source evidence has immutable identifiers/fingerprints and physical page/item references. A manual correction changes the accepted draft; it is not reconstructed from a fresh model response on export.
3. **Saved state:** Browser recovery and shared report snapshot are separate durability paths. Saving and reopening must retain the canonical draft, its source/asset provenance and deliberate omissions. Do not treat a file's classification, mere upload or stale AI proposal as permission to change confirmed rows.
4. **Deterministic assembly:** `assemble_docx` performs preflight and acknowledgment checks before building Word content from the selected draft and pinned native design (or the generic fallback). `generate_report` then prepares the Word package and derives the PDF using the configured converter. This path does **not** require a new source-reader or model answer for each generation. PDF conversion and package timestamps can differ at the byte level without changing the intended content.

## Added bounded validation

`app/monthly_report_reproducibility.py` is an **audit helper** used by tests and explicit diagnostics. It has no normal product-flow caller. Normal generation remains one-pass; existing source-integrity checks, preflight and approvals remain enabled.

- `canonical_input_manifest` records the report identity/period, **actual SHA-256 of the pinned Word template/shell**, active sections in output order with their visible numbers, block schema and accepted values, used source fingerprints, included issue/proposal cards, divider/cover assets and their content-addressed hashes when an asset loader is provided.
- `canonical_docx_manifest` reads an officially generated Word package and records ordered paragraph text and style names, explicit page/section breaks, native table cell text/merges, body/header/footer picture hashes, paragraph drawing extents and packaged media hashes. It deliberately ignores ZIP timestamps, core-property metadata and arbitrary relationship IDs. Existing byte-determinism tests remain in place.
- `verify_repeated_assembly` performs **two** Word generations for testing through the existing assembler and preflight, supplying the current draft fingerprint. It compares the selected input snapshot before/after and the structural Word outputs. A mismatch fails the diagnostic without replacing a saved version or retrying interpretation. Calling it is not a human approval or permission to export unreviewed content.
- Three independently constructed generic-shell variants cover a single facility, multiple sites with optional omissions, and a regional report with an accepted table and divider image. Controls check changed accepted rows, ZIP timestamp changes, unselected source proposals and selected source fingerprints.
- A separate synthetic native-master case saves and reopens a draft through the existing library APIs, advances the isolated default master, and verifies that the reopened report retains its original design bytes, accepted content and snapshot history. It uses a synthetic Word master and no customer records.
- Reader guards cover the actual `monthly_report_sources.ingest`/`suggest_facts`, `ocr.extract_text`/`_ocr_request` and `monthly_report_ai.request_json` entry points. Deterministic inspection of the pinned native design remains allowed.
- The optional two-pass Word/PDF case uses the repository's `requires_libreoffice` capability gate and compares PDF page text and dimensions. An environment without the Writer/Calc import filters skips that case; a skip is not output acceptance. Hosted converter requirements remain unchanged.

## Comparison and evidence limits

The input manifest is a selected-content/provenance diagnostic, not a complete encoding of every renderer input. It does not include persisted native-art/source-view approval receipts. The output manifest omits hyperlink destinations, bookmark and section-to-header/footer associations, detailed section/table geometry and styles, drawing dimensions within table cells, and some cell paragraph boundaries. Equal manifests alone cannot establish visual equivalence or identical approval state. Existing byte, geometry, source-scope, approval and native-layout tests remain authoritative for their respective controls.

The helper accepts **officially generated packages**, not arbitrary uploads. Its compressed-size and per-part checks are not a comprehensive untrusted-DOCX admission policy or aggregate expanded-media budget. Do not wire it into source intake or automatic production generation without a separate bounded resource design.

These synthetic checks cannot establish pixel-perfect brand geometry, correct visible two-digit divider clipping, fully supported OCR, cross-software pagination, or the final UMMC report's fidelity. Save/reopen is through library APIs, not a native browser. A generated DOCX package is not a rendered Word/PDF visual review, and the three generic variants plus one synthetic master do not cover every project variant.

## Proposed acceptance / future changes

- A report stored under a named contract/site/month and pinned design must always give the same visible section order, selected content, page references and graphic placement semantics on repeated generation from that unchanged state. If the input or template changes while rendering, report the stale state instead of publishing it as current.
- Reader proposals should be reviewable, source-bound and replaceable. Unknown/missing/site-ambiguous fields are not filled automatically; a failed reader must not erase human-authored entries.
- Preserve financial/price exclusions, site scope, source identities and existing edit conflict checks. No new hosted model, OCR, paid provider or automatic background interpretation is approved in this issue.
- Actual served acceptance still requires a saved/reopened report, a known source/template revision, two real downloaded DOCX/PDF results, comparisons of the output semantic manifest plus representative rendered pages, and explicit review of any differences. Test all relevant native/source variants independently; do not extrapolate from the three synthetic examples to the roughly 36 discussed project variants.
- Any future automatic use of these manifests in production must have a bounded CPU/memory policy and must **never** log or publish client source text. This PR introduces no telemetry of report content.

## Coordination

#476 provides a separate normalized work-order review contract; #277 and #285 retain source-grounding controls; #304 owns full cross-section output acceptance. #460 handles truthful contents pagination, not this semantic comparison. This contract does not change their source or rendering code.
