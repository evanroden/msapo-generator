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

Observed: **102 passed**. The set covers exact input/reference identity, actual
signature-current output selection, explicit source comparison, unchanged bytes,
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
uses the actual application UI, an invented multipage original quote and a
controlled generated PDF. External reading, submissions and shares are blocked.
The browser additionally rejects HTTP requests outside the loopback origin.

The script captures geometry and screenshots for Chromium and Playwright WebKit,
asserts actual source/output image delivery, long-review stickiness, asymmetric
book clearance, tabletop source/package transitions, unblurred text/selection/
focus, explicit source comparison, compact reflow and local preview return.
Artifacts contain synthetic data only. Segment geometry is injected; these
checks do not establish native sensor support, shipping Safari or physical
folding ergonomics.

Local execution stopped before Chromium launched because the installed
Playwright package's browser executable was absent. The existing download log
already recorded failed browser downloads; no repeated installation was
attempted. Therefore there is no local PO browser pass or geometry claim.
The harness is committed for the existing CI browser job. Record its exact-head
executed outcome separately before accepting ADP-J02/J05 or PO geometry.

Remaining separate obligations include actual multipage user quotes and shipping
Safari/device checks, accessibility beyond programmatic labels/focus, and the
complete Phase 2 acceptance matrix. This implementation is not the user's final
owner acceptance.

## Rollback

Revert this code change to restore the previous PO presentation. No persisted
schema, source file, historical record, financial rule or infrastructure was
migrated. The temporary browser fixture is never enabled by the production app.
