---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: f0e7fa32a20d95a9ae7338060397d9de34fab42c
status: visual_validation_in_progress
---

# Native ENFRA master report design

The prior renderer rebuilt imported reports inside a generic shell. It did not
preserve the source page design despite using that output for live previews.
The owner's correction requires the native ENFRA layout for every report,
including a new report started without an upload.

The native renderer uses the source Word package's page geometry, styles,
positioned artwork, native text boxes, section properties and header/footer
relationships. Source facts are cleared before current report values populate
native content locations. Empty sections remain present. Master reuse removes
source-client logos and site imagery unless the selected report supplies them.

The passive package reader retains closed local dependencies and rejects unsafe
or unsupported visible objects explicitly. No private report, contact values or
runtime master assets enter the repository. Reference documents remain immutable
runtime objects with integrity-checked hashes.

The master registry saves revisions with editor attribution and concurrent-write
guards. New reports pin the current master automatically. Existing saved reports
retain their pinned version; applying the current master is an explicit action.
The infrequent master-update upload is inside collapsed advanced design settings,
separate from the single Starting report upload for monthly content.

Full DOCX output, PDF conversion and active-section preview share the native
renderer. Native previews use actual source section ranges and inherited page
chrome, rather than assuming a fixed pair of Word sections per report section.

Validation includes source-package fidelity, absence of previous source data,
master reuse across contracts, design-version pinning, current-content rendering,
native section preview, and visual comparisons against supplied originals.

## Checkpoint evidence

Draft PR #90 initial head `3071e15bc26c90e13532c4bed18fa865a1241c29`
(tree `13b65d8e60e143e4c0d093d44a8df0a7d1cbe5df`) passed Actions
`37921482195`, job `113790193342`: **1392 passed, zero skips**. This is a
code regression result, not completed-report visual acceptance.

Subsequent UMMC replay found and corrected divider/content routing, photo-grid
tables incorrectly treated as work-order data, missing image captions, and
end-of-life table placement. Source photos now occupy individual native frames.
Only explicitly matched current payloads qualify for retaining their original
styled nodes. Large body pictures cannot become master decorations merely from
their dimensions. The fresh-report UI automatically selects and saves the master
version without requiring an upload or another template choice.

Current targeted checks: 61 import/section/native-renderer tests passed; a separate
46-test master/section/package run passed. These overlapping counts are not added.
The complete private UMMC replay records three Cost-column removals from the
existing content policy; they must be reported separately from layout defects.

Visual acceptance remains blocked. The bundled converter identifies itself as
LibreOfficeDev 26.8 alpha. Physically removing unrelated package parts changes
whether native decorations render, even when retained drawing XML and image bytes
are identical. Controlled package comparisons and both fresh-master and
starting-report replay outputs remain outside Git. Do not merge this checkpoint
or describe its output as identical until every-page comparison passes.
