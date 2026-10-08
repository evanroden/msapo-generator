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

## Validation in progress

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
  the final rerun/full suite and private-output matrix remain pending.

Nothing in this note claims deployment or acceptance of finished client reports.
