---
document_type: implementation_notes
date: 2026-10-08
base_commit: f3afd30cf39dd26f4a167ffb753927c22239f021
workflow: Monthly report
change_type: native_chart_import
status: locally_tested_awaiting_publication
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
