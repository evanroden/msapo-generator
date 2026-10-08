---
document_type: implementation_notes
date: 2026-10-08
base_commit: dd1c02bf6efd9e4ce269fe4caeae81aebdce6616
status: implemented_local_validation
---

# Guided monthly source page review

The monthly upload screen put a long fact-editing form ahead of page previews.
Asset managers can now leave those optional corrections collapsed, inspect a
bounded-width preview, and include or leave out the page with an explicit action.
Extracted text is also collapsed so the page itself is the focus.

Include requires the existing content-specific visual acceptance and content
policy gate. Exclusion preserves the source file. Both actions advance to the
next selected image/PDF page that needs review; a separate next button lets the
operator defer the current page. A progress count and completion instruction
explain when to prepare reviewed pages. The existing page selector can revisit
excluded pages; no forced sequence or automatic approval was introduced.

Widget changes are staged for the next rerun, before widgets are instantiated.
Source selections are updated immediately, so preparation signatures invalidate
and workflow switching retains the decision. Caption changes invalidate review.
Pricing/legal/blank/signature detection remains conservative and text-dependent;
visual inspection is required and this increment adds no OCR capability.

Validation: 18 focused upload/source tests passed. New AppTests cover include,
exclude, advance, revisiting excluded pages, caption invalidation, workflow
switching and a priced page that cannot be approved or included. Existing
preparation invalidation and CMMS mapping tests also passed. Ruff F/E9 and diff
checks passed. Full local suite: **912 passed, one CI-only skip** with real LibreOffice.
Documentation/hygiene checks: **33 passed**. Exact-head CI, publication and
deployment pending.

Private reports and generated artifacts remain outside git. This increment's
new regression fixtures are synthetic; it does not repeat or expand the prior
thirteen-report lifecycle acceptance matrix.
