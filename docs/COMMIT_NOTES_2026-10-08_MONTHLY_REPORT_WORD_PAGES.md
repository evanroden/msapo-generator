---
document_type: implementation_notes
date: 2026-10-08
base_commit: f3afd30cf39dd26f4a167ffb753927c22239f021
workflow: Monthly report
change_type: native_chart_import
status: merged_and_publicly_verified
---

# Preserve reviewed chart and contact pages

## LLM quick context

The owner requested real-report validation and a flow a new asset manager can
understand. The previous lifecycle release exposed a recurring gap: native Word
charts were recognized but needed manually exported replacement pictures. This
increment adds an on-demand page preview within the Organizational Chart section.

Choose **Prepare chart and contact pages**, enable complete pages, and check the
pages to retain. Each page has a purpose (chart, either outage workflow, or contact
matrix) and an explicit comparison with the original. No page starts selected.
The selected pages replace disconnected pieces only in this draft. They become
reusable pictures, not editable chart nodes; the existing Site information editor
remains the way to build a chart with editable positions and reporting lines.

## Implementation and boundaries

- A focused helper constructs a passive DOCX containing only selected Word body
  sections and their used local dependencies. The original package is not opened
  in LibreOffice. SmartArt drawing references are resolved against the containing
  document when required. Legacy VML text/group drawings now trigger review.
- Fields, external links, header/footer references and unrelated parts are removed.
  Embedded objects and linked/missing/unsupported drawing assets fail closed.
  Raster dependencies are decoded and normalized; executable image formats and
  macros are never passed through. XML parsing rejects DTDs and bounds depth/nodes.
- Preparation bounds eight Word sections, twelve output pages, 8 MB selected XML,
  24 MB reconstructed assets/output images and eighty package parts. LibreOffice
  runs in its own temporary profile with a 60-second deadline and child resource
  limits. One preparation runs at a time; it stays outside network-only workers.
- Page previews retain original geometry where conversion supports it. Blank,
  priced, legal-only, signature-only and placeholder-bearing pages identified by
  available text are blocked. These checks cannot prove scanned content is safe:
  every included page requires visual review, and changed bytes/purpose invalidate
  the relevant acceptance. An unreadable or distorted page needs a replacement.
- Confirmed images use the existing content-addressed library, snapshot revision
  guards and setup transaction. The audit record pins page, Word section, purpose,
  extracted text, digest and entered review. The original stays available. Later
  months retain these standing assets without retaining old monthly attachments.

## Validation at this checkpoint

- **82 focused tests passed** with real LibreOffice. Nine new synthetic tests cover
  section isolation, local SmartArt relationship resolution, blocked external links
  and embedded objects, stripped fields/macros, XML bounds, rendering/cleanup,
  image provenance, review gates, and the actual Streamlit prepare/select/save/
  reopen/next-month flow. Purpose changes invalidate page review.
- A supplied regional SmartArt chart was reconstructed, visually inspected and
  included in a four-page DOCX/PDF produced by the normal report generator. All
  four rendered output pages were inspected. Private inputs/output remain outside
  git under `/workspace/scratch/fbb232e099bf/chart-import-qa/`.
- A supplied legacy VML layout was also rendered. Some chart labels remained
  distorted. That case is **not** a successful preservation result and must use a
  reviewed replacement or the editable chart builder. Operator comparison is
  required; the UI does not assert that every original layout was preserved.
- Full local suite: **909 passed, one CI-only skip** with real LibreOffice.
  Documentation/public hygiene checks passed separately (**32 passed**). Ruff
  F/E9, compileall, pip check and diff checks passed. Exact-head CI, merge and
  public deployment checks remain pending at this checkpoint.

## Published feature and CI

All ten blobs and the assembled tree were verified against local Git before
publication. Published head `4db9faf36e4c75f005752d373efc565c4f71644b`, tree
`9387889905592e8c918a632a5ce521a31b6cb80a`, was fetched and diffed before
reconciling local commit identity. PR #74 passed Actions `37779538777`, job
`113318848451`: **911 passed, zero skipped**, including the added documentation
check. Logs confirmed that exact head against unchanged main
`f3afd30cf39dd26f4a167ffb753927c22239f021`. Expected-head merge produced
`798e751714064c3d4de91d28c461a784f8c7c3d6`. Public verification follows below.

## Public verification and usability follow-up

Public health recovered to 200/ok after the deployment restart. The supported
browser selected a contract/site, uploaded a small synthetic Word drawing, and
analyzed it into section cards. Production successfully prepared its complete
page, showed the preview, accepted page selection, and required comparison with
the original before approval. No persistent profile or client content was saved.
Local AppTest covers saved state; this smoke test does not claim a persisted
production lifecycle.

That walkthrough exposed a stale instruction to use an “Edit” option no longer
shown in this flow. The follow-up names the actual section-specific update choice
and points native-chart users to complete-page preparation first. It puts page
controls beside a smaller preview (stacked on narrow screens) with a fullscreen
hint for small text. Bound/timeout messages now offer replacement pictures instead
of asking users to select fewer Word sections through a nonexistent control.
This changes guidance and presentation, not review gates or document output.
The follow-up passed **87 focused tests** with real LibreOffice, including
AppTest, documentation and public hygiene; Ruff F/E9 and diff checks passed.
Final label corrections also passed **28 focused tests**. These use the displayed
section labels in pricing and long-text/table instructions, and avoid advertising
an unavailable replacement uploader for cover/unplaced native drawings.

PR #75 final head `d5980b615a32b441383d7aea90c4ce7fc47d3336`, tree
`d810c22ce39a825a60d71f9b9faffe7e5f1aa386`, passed Actions `37781360900`,
job `113324982948`: **911 passed, zero skipped**. Published blobs/tree were
hash-verified and fetched/diffed locally. Logs confirmed the exact final head
against main `798e751714064c3d4de91d28c461a784f8c7c3d6`; main was rechecked
before expected-head merge at `ae303a8338c477b72eef382fdc596a64f1dd6cfd`.

Final public check: health returned 200/ok. A fresh supported-browser session
uploaded the synthetic fixture again, saw the corrected section-specific warning,
prepared its page, and displayed page selection/purpose/review beside the image.
The preview and controls were visually inspected together. The confirmation and
shared-save boxes were left unchecked; no persistent profile was created. Public
screenshot proof is outside git at
`/workspace/scratch/monthly-report-chart-review-2026-10-08.jpg`. No private Render
workspace, logs or data access was used. Actual phone/iPad rendering was not
verified; responsive stacking relies on the existing Streamlit layout.

## What was not verified

This is not universal Word-layout compatibility or client acceptance. It does
not convert native charts to editable people, import an entire PDF as a saved
design, or establish accuracy for every supplied layout. The earlier thirteen-
DOCX lifecycle matrix remains documented in the lifecycle notes; it is not
recast as thirteen automatic native-chart preservation successes.

## Deliberately unchanged

Explicit site membership, price-free client outputs, entered-editor attribution,
review/restoration/conflict guards, DOCX retention after PDF failure, and existing
PO/expense behavior remain in force. There are no client fixtures or artwork in
git, no email output, no passcode, and no private Render access.
