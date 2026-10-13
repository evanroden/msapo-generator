# PO adaptive workspace implementation and evidence

This slice applies the shared first-party workspace and reference preview to the
actual Purchase order UI. It does not change PO calculations, routing, source
selection, generation signatures, attachments or the manual Smartsheet handoff.

## Implementation

`app/web_ui.py` now renders the existing PO body through
`_render_purchase_workflow`. The existing statements and widget keys retain their
ordering. `main` owns the workspace and an `ExitStack`, which releases container
contexts on normal exit, failed intake, and Streamlit rerun. This avoids copying
or conditionally recreating editors and requires no new workflow stages.

There are two real section boundaries:

- `purchase_review` pairs the single Upload/Paste intake and the existing compact
  request review/correction controls with the exact active original quote. Pasted
  source reference uses the same selected text snapshot as PO context. It does
  not produce an imagined final MSAPO form.
- `purchase_package` pairs the existing generation/handoff controls with the
  actual `scope_pdf_bytes` only when `scope_pdf_signature` still matches the
  current document signature. **Compare original quote** deliberately switches
  this local reference surface; returning uses the same output viewer scope.

The shared layout owns wide/book stickiness, section boundaries, compact preview
access and measured tabletop placement. Tabletop changes presentation of these
same controls and chooses the reference associated with the active pair. It does
not generate, approve, submit or share. The optional package comparison has a
non-widget view mirror for workflow-return persistence. A separate random view
identity survives corrections and workflow switches, and changes on explicit
new-upload, upload-removal or synthetic-sample actions. It is never a business
fingerprint or an authentication token.

`app/reference_preview.py` is reused unchanged. It retains original PDF bytes,
uses bounded disposable copies for images, displays pasted text accessibly and
uses the existing owner-scoped preview store and two-page/DPI bounds. Page/zoom
retention follows its source/result-specific view scope. Output invalidation
continues to happen before the generated MSAPO is eligible for display.

## Isolation gate before UI changes

`tests/test_po_adaptive_workspace.py` first exercised the pre-change PO on an
explicit temporary `EPC_DATA_DIR`. Every memory-root lookup was checked against
that exact directory; an outside sentinel was unchanged. Reader/OCR, receipt
jobs, HTTP requests, Smartsheet submission and sharing were fail-fast mocked.
A controlled synthetic PDF generator exercised the actual package assembly and
manual handoff. Original quote bytes were retained, verified memory writes stayed
inside the test root, and an ordinary rerun caused no additional generation or
storage writes. This gate passed before application layout edits.

The first development invocation incorrectly passed AppTest's SafeSessionState
wrapper to the PO mapping function; it failed in the test harness. It was
corrected to use its `filtered_state` mapping. No application or storage
protection was removed.

## Executed focused verification

```sh
ANTHROPIC_API_KEY=test-key-not-used python -m pytest -q \
  tests/test_po_adaptive_workspace.py \
  tests/test_web_ui_helpers.py \
  tests/test_po_context.py \
  tests/test_po_rules.py \
  tests/test_workflow_state.py \
  tests/test_reference_preview.py
```

Observed: **102 passed**. These unit/AppTest checks use a controlled PDF stub
and prove routing to signature-current bytes; they are not acceptance of an
actual generated MSAPO artifact. The set covers exact input/reference identity,
explicit source comparison, unchanged bytes,
zero generation/storage writes from view changes, manual source/scope/amount
preservation, workflow return, output invalidation and the existing financial,
routing, source-selection and package protections. An earlier targeted UI set
passed 12 tests; these overlapping counts are not additive.

The source guard against early returns after analysis now inspects
`_render_purchase_workflow`, where the original logic lives. It still verifies
that every correctable field precedes output invalidation; it was not removed.

## Browser acceptance status

`scripts/qa_po_adaptive.py` starts `tests/fixtures/workspaces/po_app.py` on
loopback only, with its own explicitly named temporary storage root. The fixture
uses the actual application UI and an invented multipage original quote.
The original committed fixture (`0335ced`) used a controlled generated PDF; any
run on that version is only bounded UI/state evidence, not an actual generated
MSAPO acceptance pass.

The revised fixture wraps **the original production
`app.document_generator.build_msapo_pdf`**, using the repository's unchanged
MSAPO template and LibreOffice converter. Its wrapper counts calls, verifies
master text and the reviewed synthetic scope, and records the actual PDF and
SHA-256 receipt. The original synthetic quote remains separate. Template hash
and renderer/version are included in evidence. The renderer's existing
`OUTPUT_DIR` bindings are redirected only inside this loopback fixture to its
explicit disposable root, including intermediate-file cleanup. No production
storage behavior changes. Missing LibreOffice fails the browser gate; it does
not substitute a form or skip generation.

External reading, submissions and shares are blocked. The browser additionally
rejects HTTP requests outside the loopback origin. Published CI evidence may
contain only these repository-backed synthetic documents.

The script captures geometry and screenshots for Chromium and Playwright WebKit,
asserts actual source/output image delivery, long-review stickiness, asymmetric
book clearance, tabletop source/package transitions, unblurred text/selection/
focus, explicit source comparison, compact reflow and local preview return.
The generated form is deliberately multipage. The check advances its real
preview to page 2 at 125%, temporarily opens the original quote at Fit page,
and verifies exact output page/zoom/view identity and reading position within
3 CSS pixels upon return. Previous/Next operations wait for actual raster and
component viewport acknowledgments, then check the instrumented full-app run
counter is unchanged. Comparison and navigation must not generate again.
Artifacts contain synthetic data only. Segment geometry is injected; these
checks do not establish native sensor support, shipping Safari or physical
folding ergonomics.

Local execution stopped before Chromium launched because the installed
Playwright package's browser executable was absent. The existing download log
already recorded failed browser downloads; no repeated installation was
attempted. Therefore there is no local PO browser pass or geometry claim.
The revised actual-builder harness also requires LibreOffice, which is absent
locally. Python compilation and the focused regression suite can run locally;
actual generated artifact, page/zoom, and fragment-only evidence require the
existing CI browser job with LibreOffice. Record its exact-head executed outcome
separately before accepting ADP-J02/J05 or PO geometry.

Remaining separate obligations include actual multipage user quotes and shipping
Safari/device checks, accessibility beyond programmatic labels/focus, and the
complete Phase 2 acceptance matrix. This implementation is not the user's final
owner acceptance.

## Rollback

Revert this code change to restore the previous PO presentation. No persisted
schema, source file, historical record, financial rule or infrastructure was
migrated. The temporary browser fixture is never enabled by the production app.
