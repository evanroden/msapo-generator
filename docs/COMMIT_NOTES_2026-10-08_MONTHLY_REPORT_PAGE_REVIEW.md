---
document_type: implementation_notes
date: 2026-10-08
base_commit: dd1c02bf6efd9e4ce269fe4caeae81aebdce6616
status: merged_public_check_pending
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

## Publication and retained-sample walkthrough

PR #77 published head `acc27c209d5b7f9ebb43f85f404918b573ac8bb5`, tree
`43b22a04dcfb803cec63b7802b4a9e87c9c6d1cf`. All six blobs and the tree
were hash-verified, fetched and compared before local identity reconciliation.
Actions `37792632959`, job `113363758419`, passed **914 tests, zero skipped**.
Logs confirmed the exact head against unchanged main `dd1c02bf6efd9e4ce269fe4caeae81aebdce6616`.
Expected-head merge produced `013f7bfdbd514f89175b760f4909182d8b95562d`.

A retained private DOCX was read locally as monthly evidence. Its cover preview
was visually inspected. AppTest passed leave-out, revisit and workflow-switch
retention without approving any client output. This is a targeted UI smoke test,
not new full-report acceptance. Originals, extracted images and test runtime are
outside git under `/workspace/scratch/page-review-qa/`.

Follow-up adds the same page-decision instructions to the first-time help panel,
so users can learn the controls before starting a report. Public checks remain
limited to health and UI; no private Render access or persistent QA profile.
