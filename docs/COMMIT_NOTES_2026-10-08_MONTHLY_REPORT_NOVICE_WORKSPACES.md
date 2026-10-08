---
document_type: implementation_notes
date: 2026-10-08
base_commit: 08d4696c4e06b7a973b74c8adb0282054b9c88aa
status: deployed_public_controls_verified
---

# Monthly report novice workflow review

## Reason and scope

The owner authorized parallel novice walkthroughs. Four independent reviewers
covered first-use/returning memory, imported cover and organization pages,
monthly evidence, and every remaining section/final output review. Their findings
were reproduced with synthetic AppTest inputs and retained private originals
outside git. This increment fixes concrete dead ends rather than claiming the
whole workflow is finished.

## Changes

- Cover and organization replacements have named upload inputs beside the
  section. Uploads survive reruns. Keeping complete chart pages no longer drops
  a newly uploaded outage procedure during import/save.
- Saved pictures have visible cards and direct removal, with bounded pagination.
  The guided workspace groups standing information by actual report section;
  utility results, equipment issues, renewal priorities, proposals and requested
  information have one monthly editing location. This UI grouping does not
  change which content is cleared next month.
- The report checklist shows section guidance, populated-part counts and the
  editing location without hiding a lone include checkbox inside an expander.
  New general designs leave the optional RFI appendix off; existing choices stay.
- Empty monthly attachment sections explain the next action. With no suggested
  work there is no meaningless source-action confirmation.
- Scanned source review queues every undecided page, including initially
  unselected pages. Explicit exclusions are fingerprint-bound and serialized
  backward-compatibly. A single source needs no file dropdown; destination
  choices have section names. Undecided pages remain visible in the queue.
- Native action suggestions use only selected readable technical pages, and
  insertion cites the actual supporting pages. Human-edited unmatched wording
  remains intact for review and is not automatically attributed to other pages.
- New capital/proposal tables do not ask for prices. Guided editing makes a
  detached copy of old tables without identified pricing columns, explains the
  removal, and preserves saved history. Inline prices still require correction.
- Final output review shows one page with explicit approve/remove actions;
  every included page must be checked. Content changes invalidate approval and
  finished downloads. Caption/source alignment survives removal.
- Concurrent-save comparison shows readable saved/current content, editor,
  version and limited image previews. Expected-revision acceptance stays explicit.

## Validation and release state

PR #84 merged at `be81a93fd5fb548b9a66f62a2c103002bcff3ddf`. Feature head
`d785644261113962f1b0ef16c7d4bc29b921d73f`, tree
`a927853e8bde2055552d0b07be7232162730a634`. Actions `37832296397`,
job `113500438654`: **957 passed, zero skipped**, exact head against unchanged
main. Public health recovered following a transient deployment 502. Browser
verified real DOCX analysis and named cover/client/brand plus chart/outage/contact
replacement controls. No client profile or final report was approved/saved;
other guided/final-review flows were verified by local AppTest.
Full local suite: **955 passed, one CI-only skip**, with actual LibreOffice.
The subsequent new documentation front matter was corrected and checked separately.
Private read-only section walkthroughs passed: individual report 13 sections /
84 pictures / 25 picture groups; regional report 13 sections / 34 pictures /
16 groups. Every section entered edit mode, all picture groups loaded, original
file hashes stayed unchanged, and no client content was approved or saved.
These are control checks, not owner acceptance of report output. Exact-head CI passed before expected-head-protected merge.
The previous documentation checkpoint PR #83 merged at
`08d4696c4e06b7a973b74c8adb0282054b9c88aa` after successful Actions
`37830532962`.

## Remaining work and safeguards

Private directory/sample seeding is still pending, including resolution of the
workbook's copied contract-tab membership ambiguity. No client profile or final
report has been approved by these walkthroughs. Manual image review remains
necessary; a cover date never proves the dates of embedded pages. CMMS mapping
and the upload/prepare/add sequence still need further simplification. Public
Render checks only; no private logs/workspace access. Originals, historical
snapshots and content-addressed binaries remain immutable. PO and expense paths
are outside this implementation scope and remain covered by the full suite.

Rollback: revert this feature commit. Added exclusion metadata is optional and
old snapshots remain readable. No destructive runtime migration is required.
