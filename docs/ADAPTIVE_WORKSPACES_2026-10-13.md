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

Local Playwright browser installation returned a truncated archive, so the
browser harness has **not** passed locally at this checkpoint. Its CI outcome
must be recorded before declaring the geometry verified. Playwright WebKit
is not shipping Safari. Injected geometry is not physical folding hardware.

Coverage targeted by the harness: long-section pin/release/reverse, internal
viewer fit, asymmetric book gap, upper/lower tabletop geometry, active-section
change, unblurred value/selection/focus, and compact preview/return. Pure
geometry covers unavailable/malformed/extra segments, safe edges, off-center
and zero gaps, viewport offsets, coarse posture labels and reduced available
space. These are bounded ADP-A01–A08 evidence, not six completed workflow
journeys or authentic/native-output acceptance.

## Remaining integration and acceptance

- Wire these boundaries into actual monthly, PO and expense renderers. Preserve
  all existing keys, mirrors, source identities, explicit submission handoffs,
  current output invalidation and per-workflow test isolation.
- Confirm source/result staging in PO, receipt-scoped references and mileage-only
  expense pairing; confirm actual workflow switch/return behavior.
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

The first real DOM CI run exposed a sticky-wrapper height failure. This is an
open implementation defect under diagnosis; the sticky assertion is retained.
A passed geometry resolver/AppTest is not acceptance of this browser behavior.
