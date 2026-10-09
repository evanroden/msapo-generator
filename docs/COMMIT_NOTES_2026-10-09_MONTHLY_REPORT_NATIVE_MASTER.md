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
