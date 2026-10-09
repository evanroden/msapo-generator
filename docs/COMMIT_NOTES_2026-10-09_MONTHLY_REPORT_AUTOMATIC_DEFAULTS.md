---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: 49f57928159fd92ae1e25cf2b353de436cd5c6e2
status: integration_validation_in_progress
---

# Monthly report defaults and live section editing

The owner's feedback supersedes earlier per-report section choices, standing
information confirmations, equipment-tag entry and prominent branding prompts.
All twelve standard sections remain included even when blank. Guided drafts
normalize legacy omissions and required flags without deleting imported content
or weakening checks on content that is present.

One Starting report upload infers source sites and dates. Current body evidence
survives stale cover dates, older monthly prose/pictures roll forward blank, and
another site's report supplies design without its private site content. Only
ambiguous identity, unsupported artwork or problematic content needs a decision.
Starting/importing saves the reusable design directly, without a remember box.

Editing uses two equal columns. The right side automatically renders only the
selected section's actual Word layout, with sharp scrollable pages. Preview
approval does not unlock exports; final content checks remain independent.
Whole-report preview is limited to Review. Per-section cache keys ignore unrelated
changes, and failed updates never leave stale pages looking current.

Saved directory contacts fill an empty table after editor attribution, using
unique exact names/aliases. Existing report content is retained. Reviewed saved
ENFRA outage diagrams establish shared immutable defaults across contracts.
Workflow and cover appearance changes are tucked into collapsed settings.

Thermal capacity accepts common documents, spreadsheets, PDFs, text and images.
Native tables and bounded structured reading preserve required/available values,
units and service/plant distinctions. A reviewed contract-wide save makes every
matched site's tables available to new reports. Existing/manual report contents
remain pinned. Source originals, revision history, uncertain matches and update
conflicts are preserved; values are never calculated or invented.

Picture editing focuses on new/changed images and retains unchanged approvals.
The source-page Include action, CMMS Apply action and MBCx Use this update action
replace redundant checkbox-plus-button flows. Factual issue/proposal decisions
and evidence remain explicit. No contact workbook or private runtime data is
committed.

Validation covers complete blank-section generation, current-section preview
updates, single-upload inference, shared data across sites, retained manual work,
concurrent revisions, and unchanged-picture review persistence. See the PR checks
for the final full-suite and real-renderer results.
