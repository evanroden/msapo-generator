---
document_type: implementation_notes
date: 2026-10-08
base_commit: d82903eab8e64d4248c877b1625172c56750b6f2
workflow: Monthly report
status: validation_in_progress
---

# Monthly report lifecycle validation — 2026-10-08

## Scope and findings

The owner requested complete create/update/download and returning-user validation,
including every supplied layout and a report built from scratch. This increment
addresses defects found during that work; private fixtures and QA outputs stay
outside the public repository.

- A fresh template exposed twelve sections and many empty-section warnings with
  no guided section-selection control. The Report step now offers section
  checkboxes, retains omitted content, and explains next-month reuse. New template
  setup lands there before monthly editing. Review blockers offer navigation.
- Save feedback disappeared on rerun. The workspace now compares the edited draft
  with the saved snapshot and shows saved version or unsaved-change status.
- A newer imported report could lose precedence to an older monthly snapshot.
  Seed selection now compares reporting periods and the import's snapshot revision;
  future months are excluded. Same-contract design suggestions rank explicit site
  overlap, scope and recency without changing report membership.
- Guided/imported divider blocks were not resolved by the renderer. They now render
  behind section titles; explicit omission overrides a legacy divider reference.
  Import review can identify a divider photograph and assign org chart, outage
  workflow and contact pictures individually.

## Additional defects found during output/continuation checks

- Floating footer text and decorative numbers could become section titles. Import
  now keeps a clean heading or the recognized section title, with a synthetic
  regression case. Existing narrative text is not silently removed.
- Adding a teammate’s partial report used only persisted content and could lose
  unsaved edits. Guided import now includes the open draft and its image assets,
  and refuses to proceed if the saved revision changed during review. An AppTest
  verifies both editors’ text survives.
- Returning users see their report title and explicit site membership; the long
  site chooser starts collapsed but stays editable.

## Validation

- All thirteen recovered private DOCX files passed bounded inspection. Their
  pictures were reviewed as contact sheets outside git. This exposed native Word
  drawings and rasterized heading fragments that still require deliberate review;
  successful parsing does not establish faithful reconstruction.
- A synthetic three-site regional report was created through the actual Streamlit
  AppTest flow, edited, generated with real LibreOffice, and reopened in a fresh
  session for the next month. DOCX/PDF downloads, period, group name, membership,
  section choices, org chart retention and cleared activity text were verified.
- Earlier focused run: 38 passed, one new saved-status test failed because status
  was computed before same-rerun edits. Status rendering was moved after editing;
  the focused rerun passed **43 tests**. The full suite found missing front matter
  in these notes (corrected) and then exited without a summary during the monthly
  tests; no full-suite pass is claimed. Exact-head CI and private-output matrix
  remain pending.

Nothing in this note claims deployment or acceptance of finished client reports.


### Completed local validation

- Final focused release run: **97 passed** with real LibreOffice, including UI,
  imports, saved design selection, rendering, docs and public hygiene. Ruff F/E9,
  compileall, pip check and diff checks passed.
- Thirteen private DOCX input cases each produced DOCX and PDF through production
  import/model/library/renderer APIs. The QA copies use explicit synthetic site
  identities and are marked synthetic. The matrix verifies original SHA retention,
  deterministic DOCX, snapshot reload, append-only partial updates, stale-write
  rejection and next-month seed selection/clearing. This is developer validation,
  not client acceptance or a claim of pixel-identical import.
- Image choices were deliberate: cover/logos, selected dividers and standing
  pictures. Old vendor pages were left in the original for reference. Pricing and
  instruction lines were excluded from the QA copy; originals were retained.
  Four charts required replacement images rendered locally from the original;
  two source reports have workflows/contact matrices but no separate org chart,
  so explicitly synthetic charts completed those QA cases. Native Word charts
  are still not automatically converted into editable nodes by the application.
- Actual individual, regional and multi-site DOCX AppTest walkthroughs opened all
  thirteen section cards per case, retained an edited activity paragraph after
  closing/reopening its section, and kept pricing/unsupported-content blockers.
- The supplied PDF has 56 pages. Native extraction classified ten as pricing and
  fourteen as needing visual review; duplicate suppression passed. Seven selected
  technical water-treatment pages produced a ten-page DOCX/PDF QA report. A priced
  page remained blocked even when supplied a review fingerprint. PDF evidence
  upload is tested; first-report design bootstrap still accepts DOCX, not PDF.
- Output contact sheets exposed the floating-footer heading bug, then affected
  layouts were rerendered after correction. Private QA artifacts are outside git
  in `/workspace/scratch/fbb232e099bf/monthly-report-validation/`.

### Publication and CI

PR #72 first head `240ed8d21d8cc5d9e5e2c5fb24b6eae95127e07d`, tree
`017bf31911795d3e651912a07508ff7f57737a1c`, was fetched and compared with local
Git before reconciliation. Actions `37717852378`, job `113118391993`, finished
**896 passed, two failed**: missing notes front matter and an old UI test assuming
new template setup still lands directly in Site information. Both are corrected;
the latter now navigates to that step before testing the same chart/contact flow.
Two local full-suite attempts exited without a summary; no full local pass is
claimed. Final updated-head CI, merge and public deployment checks remain pending.
