# Adaptive workspace implementation checkpoint — October 13, 2026

## Scope and baseline

Baseline: `abb28d7a019d0913e4df843bb7fc40f5db085a6b`. Locked and locally
imported Streamlit: **1.61.1**. This is a shared foundation, not acceptance of
all Phase 2 journeys. No authentic input is used by these fixtures or artifacts.

The prior app imposed a 1,000 CSS-pixel main width, used equal unkeyed monthly
columns, and used fixed 730/760-pixel preview heights. Only Cover attempted
sticky positioning. Expense receipt sources preceded their fields. PO and
expense business rules and financial calculations are outside this patch.

## Shared API and ownership

`app/workspace_layout.py` exposes:

```python
with workspace('monthly', report_identity, navigation_key='monthly_report_navigation'):
    with workspace_section('monthly_activity', 'Activity'):
        editor, reference = workspace_columns('monthly_activity')
        with editor:
            # The existing canonical editor, rendered exactly once.
            ...
        with reference:
            # Existing generated section preview/source, rendered exactly once.
            ...
```

`workspace` owns the ordered editor root. `workspace_section` owns its heading,
validation and paired editor/reference boundary. Keys are application-owned
identifiers, not a report name. Identity is hashed before entering component
data. Geometry sends no callbacks to Python; resizing cannot call a reader,
assemble a document, write a draft or approve an item.

`app/workspace_geometry.js` validates positive finite rectangles and intersects
layout, visual viewport, app and scrollport in CSS pixels. Visual viewport
scale is not applied twice. It distinguishes the measured divider gap from a
chosen 12-pixel clearance. One/unavailable/malformed/unsupported segments use
an explicit dimension fallback. A valid pair too small for two working panes
uses compact layout. A posture label never invents a hinge angle or device.

`app/workspace_layout.js` contains the one locked Streamlit wrapper adapter.
It decorates only keyed containers and the actual columns between them. It
does not clone, move or re-create framework inputs. Wide and book layouts keep
each preview within its own section. Tabletop intentionally makes the existing
workspace the lower working scroll root; only the active section's reference
occupies the upper measured segment. The outer app scrollport relinquishes
scroll ownership only while this presentation is active. The adapter restores
it on cleanup/exit. Unsupported transformed ancestry fails to compact flow.

ResizeObserver, posture/orientation/media/visual viewport events and DOM
mounts coalesce through requestAnimationFrame. Display changes are local.
Temporary controls, observers and listeners clean up. Active-section selection
has a 24-pixel boundary hysteresis and maintains reverse scrolling.

`app/monthly_report_preview_view.py` uses available height inside the shadow
root, Previous/Next, Fit width/Fit page/125%/150%, and explicit enlargement.
Only view position is retained in a bounded 64-entry in-memory map keyed by
report/section widget identity; report text is never placed in browser storage.
Changed page counts clamp to the nearest surviving page. Existing two-page
requests, DPI tiers, visibility gating and generation checks remain. This
foundation does not alter assembly, queue, cache or standing-data semantics.

## Validation and evidence limits

Executed locally:

- `node --test tests/workspace_geometry_test.cjs`: 17 passed.
- Focused Python workspace/preview tests: 27 passed, 1 renderer-dependent skip
  in the initial run. This is AppTest and logic evidence, not DOM geometry.
- Streamlit 1.61.1 fixture starts successfully with the existing locked runtime.

`python scripts/qa_adaptive_workspaces.py` starts a disposable localhost
Streamlit fixture and records real DOM rectangles and synthetic screenshots
for Chromium and Playwright WebKit. The CI workflow
`.github/workflows/adaptive-workspaces.yml` runs this harness independently of
production. It has no Render URL, credentials, real files, OCR requests,
Smartsheet actions, email/share actions or business storage.

Local Playwright browser installation returned a truncated archive, so no local
browser pass is claimed. CI outcomes are recorded below, including subsequent
failures when stronger actual-image checks were added. Playwright WebKit is not
shipping Safari. Injected geometry is not physical folding hardware.

Coverage targeted by the harness: long-section pin/release/reverse, internal
viewer fit, asymmetric book gap, upper/lower tabletop geometry, active-section
change, unblurred value/selection/focus, and compact preview/return. Pure
geometry covers unavailable/malformed/extra segments, safe edges, off-center
and zero gaps, viewport offsets, coarse posture labels and reduced available
space. These are bounded ADP-A01–A08 evidence, not six completed workflow
journeys or authentic/native-output acceptance.

## Remaining integration and acceptance

- Monthly and Expense boundary wiring is implemented. PO wiring is separately
  committed in `0335ced`; integrated-head CI must verify the combined result.
  Existing keys, mirrors, source identities and explicit handoff actions remain.
- Actual Expense and PO harnesses now exercise original multipage sources and
  generated-result staging; their browser outcomes are still pending. Confirm
  workflow switch/return behavior with source and draft identity preserved.
- Run the actual application DOM, real generated multipage previews and resource
  gates after integration. Review page/zoom, image-heavy failure/retry, late jobs,
  gray-freeze instrumentation, large text, keyboard/IME and accessibility.
- Record ADP-J01–J06 separately. Physical posture/Safari checks and authentic
  imports/outputs require their own evidence and remain unaccepted here.

## Rollback

Revert the boundary integration and the shared display/view files together.
There are no data migrations, infrastructure changes or standing-data writes.
Report state and originals remain under the existing production code paths.

## Primary API references verified during implementation

- https://docs.streamlit.io/1.61.0/develop/api-reference/custom-components/st.components.v2.component
- https://docs.streamlit.io/1.61.0/develop/api-reference/layout/st.container
- https://www.w3.org/TR/device-posture/
- https://drafts.csswg.org/css-viewport/#dom-viewport-segments
- https://www.w3.org/TR/cssom-view/#the-visualviewport-interface

These references establish API semantics, not device/browser availability.

## Expense integration checkpoint

The expense isolation gate ran before UI mutation: two real AppTest sessions,
original synthetic image bytes and independent edits/splits/removals, temporary
EPC_DATA_DIR, denied socket/subprocess/external-reader/native-share boundaries.
Real SQLite and Python write paths were constrained to the temporary root.
Both tests passed; no Monthly QA namespace was used.

The expense renderer now uses one shared workspace and per-receipt boundaries,
with the existing single editor on the left and the original bounded source
viewer on the right. Existing receipt hashes, splits, calculations and controls
are unchanged. Mileage pairs the existing editor with current trip/reimbursement
information. The existing current-package signature gate pairs manual handoff
controls with the actual generated PDF; missing PDFs retain Excel fallback.
`reference_preview.py` uses the existing owner-scoped global PreviewStore,
loads only visible sources and rasterizes at most two requested pages. PDFs
remain byte-for-byte original; images use existing bounded normalization.

Executed integration-focused checks: 14 passed across isolation, draft mirror,
disclosure, source-viewer and workspace tests. Source viewing tests separately
prove an offscreen source has zero PDF/raster entries, a four-page source loads
only two requested pages and a second owner cannot read its ticket. Browser
expense journeys and hardware/share cancellation remain unverified.

## Browser checkpoints and repairs

- Run `38336061830` failed the real wide sticky assertion: the reference flex
  wrapper stretched to the full row height, defeating its containing interval.
  Commit `31df00c` makes this app-owned reference wrapper non-stretching with
  intrinsic height; the original geometry assertion remains.
- Run `38336703871`, integrated commit `963f144`, passed the foundation harness
  in Chromium and Playwright WebKit. Screenshot review then found that a
  placeholder surface could satisfy that version of the harness. This pass
  supports its geometry assertions, not actual multipage image readiness.
- Run `38337327841`, integrated commit `d807419`, used actual two-page PDF
  tickets/images and failed the retained JavaScript-error assertion after the
  Chromium geometry assertions. Old component callbacks referenced one-page
  sizes after the mounted preview became two pages. Commit `5ef2373` explicitly
  disposes superseded render listeners, makes cleanup/timers invocation-local,
  and rejects queued stale callbacks. A Node regression reproduces mounted
  placeholder-to-two-page rendering, old queued observers and delayed cleanup;
  the focused Python suite passed 31 tests. This is a lifecycle repair awaiting
  the stronger real-browser CI rerun, not a browser pass.

`7da64a5` confines explicit enlargement to the measured book/tabletop segment
(or usable compact viewport), and Escape restores the previous page, zoom and
reading offset. Actual Expense browser assertions cover these bounds and return
behavior; they are pending CI. `8017832` admits image normalization through the
existing preview resource-priority slot and rejects prior owner generations.

The actual Expense harness uses private temporary EPC_DATA_DIR, invented PDFs
and blocked external reader/share/generation boundaries. It asserts original
page-two display, splits/manual overrides, book/tabletop transitions, mileage-only
review, and unchanged full-app-run count during preview navigation. No physical
hardware or authentic report evidence is inferred from those fixtures.

Known remaining limits include framework popover portals outside app-owned
containers, optional explicit focus override, physical keyboard/IME and Safari
behavior, and all authentic input/output acceptance. Separate actual Monthly
and PO harnesses are integrated by their owners; their run outcomes belong in
the consolidated exact-head evidence ledger.


## Fragment ownership and measured tabletop visibility repair

Actual QA browser instrumentation found that whole-context restoration inside a
Monthly preview fragment also restored Streamlit's older rendering context.
`capture_namespace()` now binds only the application-owned QA scope and reset
lease. It leaves Streamlit's current fragment and delta-generator state intact.
Viewport, poll and retry callbacks bind that same namespace before touching
caches, and validate the reset lease before any state mutation. Worker threads
continue to carry their captured context. Tests inspect real Streamlit widget
metadata and prove stale callbacks cannot recreate an erased QA namespace.

The browser checks require page navigation/section scrolling to leave full-app
counts unchanged while fragment counts increase. Synthetic diagnostics use
hidden DOM data so they cannot enlarge the section being measured. Exact runs,
including failures, are in the consolidated execution ledger.

Tabletop reference visibility uses positive measured viewport bounds for the
active fixed upper pane because WebKit can report it clipped to the lower
scroll ancestor. Inactive references are display-hidden, preserving all editor
instances. Geometry excludes the measured persistent header; tests hit-test the
upper title and require actual decoded imagery for the newly selected receipt.
This is browser implementation work, not physical-device or Safari acceptance.


### Preview startup and protocol diagnostic checkpoint — 14:40 UTC

The viewer binds stable `st-key-epc_workspace_` / `st-key-epc_pair_` ancestors before the layout adapter's first animation frame. Presentation classes may not yet exist when the Streamlit v2 component mounts; missing that ancestor prevented active-section notifications from reaching an initially offscreen preview. Lifecycle regression covers that ordering; Chromium/WebKit proof remains required.

Current `6f0c902` browser evidence confirms the real Monthly Chromium preview remains fragment-local (full runs 7→7, fragment progress) and both PO engines complete. WebKit Monthly instead encountered a Streamlit wire-cache connection error; bounded localhost-only protocol diagnostics are added without changing cache/runtime behavior. This is distinct from the next-pane preview startup repair. Revert the scoped code changes for rollback; preserve all report/storage data.


### Applied-view acknowledgments and Expense output — 14:52 UTC

Browser dispatch is distinct from the server's applied viewport. Each shared preview now receives the latter with its current generation; a rerender that did not apply the requested view causes a distinct bounded request-ID delivery. A matching applied view causes no repeat. This only reconciles bounded visibility/page/DPI requests, never business text or saves. Existing owner/generation/reset validation and global raster/conversion budgets remain intact. Tests explicitly model an interrupted callback that stored a widget value without applying it.

On `29b650f`, actual Monthly/PO and shared DOM passed both engines; Expense Chromium still lacked its newly active second receipt, so the acknowledgment change needs browser proof. The previous WebKit cache error remains unresolved, though it did not recur. The isolated Expense fixture now executes the production Calc builder and its actual packet/download/source-return journey; no external reader, share, email or submission operation is permitted. Native Safari and physical folding remain separate.
