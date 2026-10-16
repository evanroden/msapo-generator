# ENFRA Phase 1 / Phase 2 — remaining work

This is the single current remaining-work ledger. Historical evidence and failures stay in
`PHASE1_PHASE2_EXECUTION_2026-10-13.md` and the linked PR comments; they are not fresh defect counts.
Neither phase is accepted. Do not merge a stacked cleanup PR into its parent feature branch.

## Current branch and evidence boundary

Main and the last independently verified served revision remain
`0dca61194d1769d7871ba46d222289dadef0e8d1` (PR247). Its terminal evidence is
https://github.com/evanroden/msapo-generator/pull/247#issuecomment-6196963277 .
No new main merge, Render workspace selection or served revision is claimed here.

PR248 remains open on `fix/starting-review-deselection-20261015`; current parent
`d9ab483bea475a8e86357d286a8f097b13d3008b` repairs conservative table re-selection,
reference-only Retry gating, exact Prepared-by typing and pending textarea Tab/ShiftTab commits.
The real DOCX re-selection defect reproduced three failures before82 affected cases passed.
The pinned first-fragment scheduler model reproduced a deferred Prepared commit in a fragment;
its bounded hold passed8 gate cases. Fresh WebKit Shared evidence in38924106205
then showed trusted input/Tab/change/blur on one connected node and the corrected69-character
hash delivered only through a preview fragment; the durable draft remained empty. Tab/ShiftTab
keydown now promotes the existing pending hold before focus/scroll can queue that fragment.
Two negative regressions failed before repair; all11 gate cases,15 observer cases and33 existing
lifecycle/geometry cases pass. Exact internal scheduling order remains unrecorded; preserve that
limitation rather than claiming every historical image/input error explained.
Required38926528701 on currentd9ab483 succeeded; Adaptive38926528415 is still running.
Earlier580213c Required38923741582 succeeded and Adaptive38923741814 was superseded. The
9baa90de browser run38925992973 was superseded by the specific Tab repair, not rerun unchanged.

PR249 remains open and stacked on PR248. This candidate incorporates currentd9ab483 and keeps
all prior Water caption/action/source/omission protections. Run38924106205 on b7b4304 now proves
both engines reached narrow-current-preview with actual visible Current3-page content after
reload. The previous missing-root/offscreen harness prerequisites are corrected; no eager raster,
forced viewport event, longer wait or application-rendering change was required. That run failed
later: QA generation rejected source-page artwork because its toolbar omitted asset_loader.
The ordinary guided generator already supplies that resolver. Current QA repair captures the
isolated namespace/generation, validates even memory hits against its lease, and resolves current
memory assets or scoped library bytes in uncopied workers without any live fallback. Actual PDF
page ingestion-to-DOCX media, missing-asset rejection and stale-reset/worker negative cases pass
(38 affected tests). Local PDF conversion used an explicit stub; CI actual final output remains
required. No production generation is used as QA.

Independent review reproduced retained Water content marked source=Omit being falsely called
included while Include page kept it omitted. Current repair reports zero included, distinguishes
reviewing retained pages from inclusion, and offers a separate explicitly scoped whole-section
recovery only after all retained image/source reviews. It retains native text/tables and original
bytes, refuses stale/reset/caption-changing actions, and retires stale automatic-add receipts.
One page review cannot restore its companions.61 affected cases and final13 omitted cases pass.

The exact b7b4304 Required38924106259 succeeded. Its Adaptive38924106205 failed only Shared
WebKit re-entry and the QA Water asset resolver tail; all other recorded step families passed.
Its8 Prepared journeys used the corrected bounded event observer:98 events each, same native
node throughout, with actual final change/blur. Those passes predate the newer input guards.
Original artifact12056143035 and the separate Training artifact12056357103 are retained privately
with their own byte-verified hashes; do not conflate a selected derivative with an original ZIP.

PR250 is the separate Training follow-up stacked on249, published at6a201157. It separates
requirements/sessions, requires an actual date and fixes the exact locked scalar-date boundary
using cache-safe content-named assets, without changing dependency versions.88 affected cases
passed. Its first actual browser job117055295271 reproduced the old announcement and verified
repaired typed/calendar/keyboard single-date behavior in both engines, then failed before native
Clear while the Participants popup was still open. A natural ordering correction uses the same
gestures and retains the real accessible Clear assertion; DOM/AX evidence will distinguish any
remaining cause. No physical/assistive audio, durable session tail or output pass is claimed yet.

PR251 is the separate low-reading/history/source follow-up stacked on249, published at3b642e1.
It includes real dated/author shared history and read-only comparison, one Help, Report actions,
About diagnostics and a single explicit source inclusion action. Current further local batches
consolidate identity/details/admin and section editors. Review caught two concrete follow-ups:
accepted uploads must persist for the retained detailed editor's later Generate rerun (reproduced
and repaired with actual caller/generation coverage); picture paging must bind canonical
comparison identity and each ordered image collection (two reproduced failures,29 tests pass).
These changes are not considered merged, served or complete solely because committed.

### Failures that must remain visible

* PR248 head6046650 Required38774586215 passed 2,641 tests, but Adaptive38774586190 failed:
  WebKit did not produce the expected durable Activity receipt after transitions, and the shared
  fixture journey recorded an image EncodingError. Passing later runs do not explain these.
  The rejected first automatic-deletion proposal was never merged/deployed.
* The PR249 20af Water run included both source pages durably but left pre-merge controls visible.
  Head148e4a9 adds one refresh only after canonical inclusion/acknowledgment; failed merges do not
  acknowledge pages. Preserve the final guided `_refresh_period_editors_after_commit(prefix)`.
* Head148e4a9 Required38835526698 passed; Adaptive38835526737 failed. Hash-verified artifact
  12019408150 is 66,312,471 bytes, SHA256
  `fae64b41d1a7c32a5a31bc1c059401f831954073356e5555ca36f10db2ce0c2b`.
  Chromium stopped awaiting the second page decision; only page 1 was durably reviewed.
  WebKit included both pages, then waited for Water output while the screenshot viewport was
  on Equipment Issues. That offscreen wait does not reproduce an indefinitely blank visible pane.
* Head2912e1e4 Adaptive38838186070 failed. Its unchanged artifact12020477877 is
  58,457,194 bytes, SHA256
  `15ac10f5f341eedf1882692c7ab16b0000ef00dc926f0ae3c2b905e3c801c20f`.
  Monthly WebKit stopped at a disabled vendor-page checkbox after source-manager opening;
  it did not reach the later layout-transition receipt check. Shared WebKit's intentional
  keyboard clear remained uncommitted: exact wire carried the empty Activity in a preview-fragment
  request without the needed full editor run. Water in both engines durably included two pages,
  then waited for an offscreen current preview; caption/order/removal/export tails were not reached.
  Preserve each failure independently; do not call a trace-start fix a business-input repair.
* An exploratory local assertion about reused page-button keys failed, but a delayed-action probe
  did not reproduce unintended approval. No production key change was made from that conjecture.

The October16 runtime has a complete normal Git checkout and branch worktrees, not the older
partial reconstruction. Dependencies use the unchanged requirements-dev.lock under Python3.12.14.
A local native NumPy import SIGBUS was traced to a truncated installed OpenBLAS file; restoring
byte-identical content from the same locked wheel restored import. This environment repair is
not an application change, dependency upgrade or passing browser evidence.

## Ordered implementation and acceptance still required

| Area | Evidence state | Next operation |
| --- | --- | --- |
| PR248/249 integration | Implemented; current browser gate not cleared | Diagnose retained failures, finish current exact-head Required/Adaptive, review both diffs, merge parent to main only when justified, retarget cleanup to main, verify integrated and actually served revisions. |
| One Water/source-page workspace | Actual compact Current preview verified; output tail repair awaits exact CI | Complete desktop then narrow upload, one review/caption/order/omit/reinclude path, repeated unchanged upload, durable reload, explicit blank/price rejection, real preview and DOCX/PDF. Preserve source identity, dependency gates and omitted-page guards. |
| Identity/help/navigation | Browser-observed cleanup remains | One stable contract/sites/month strip and useful Change path; combined quiet Help; one Prepared by with actual focus links; More report details for aliases/group/region; meaningful workflow-preserving deep links only. |
| Saving/history/recovery | Browser-observed and conditional | One truthful status; actual history rows or correctly named checkpoint action; report actions for confirmed scoped discard. Preserve conflict choices, both versions, unsent versus acknowledged edits, original/history/standing scope. |
| Training | Implemented in separatePR250; partial actual browser proof, session/output tail open | Separate standing staff requirements from monthly sessions. Retain statuses, unknown hours, explicit deletion, same-name/course identity, rollover/history and stable input incarnation. Reproduce and correct the single-date second-date announcement without changing to a range or hiding the warning. |
| Section/editor cleanup | Browser-observed, partly conditional | Remove duplicate headings/prose, not functions. Keep one canonical Activity editor, optional grounded writing help, evidence/price gates, CMMS coverage, scoped organization/contact editors, correct ENFRA onsite versus vendor distinction, issue recovery, proposals and RFI meaning. |
| Administration/design controls | Navigation cleanup remains | Move storage, bulk directory and master administration out of ordinary reporting without changing permissions. Keep pins/history and explicit shared-write scope. Raw hashes belong in diagnostics. |
| Imported cover/artwork/conflicts | Source-only conditional states not fully reached | Reproduce duplicate galleries/action gates before deleting them. Preserve original graphics, bounded recovery/retry, explicit uncertainty, scope/date correction and optimistic concurrency. No silent art drop or hidden shared save. |
| AUTH01/02/03 | Blocked on exact approved source/target expectations and supported access | Same-site prior month; different site same contract; owner-identified genuinely half-finished current month. Inventory is not scenario selection; filenames do not establish partial status. |
| Genuine native conversion | Diagnostic incomplete, not production timeout | Investigate the retained same-site preflight with bounded worker, stage timings, first-failure trace and reliable process cleanup before retry. Do not raise limits or discard drawings. |
| Native outputs/privacy | Open authentic acceptance | Inspect every actual PDF page and every DOCX page with named renderer; retain Microsoft Word check separately. Check package/graphics/hidden channels, real masters/assets and actual source values. |
| Standing data | Scope/reuse acceptance incomplete | Verify contract versus facility/service/system/unit scope, safe first-fill, contacts, capacity/NR, Training, concurrent writes, failed-save recovery, history and deployment retention. Display/resize must write nothing. |
| Adaptive/accessibility | Coverage partial, physical checks open | Finish all six journeys and retained ADP-A01–A20 IDs; actual pointer/touch, keyboard/AX, IME/caret, zoom, preview latency/eviction and durability distinctions. |

For removed/combined controls, record where each necessary action lives. Capture task steps and
representative before/after screens, not just label counts. Conditional branches not reached remain
unverified, not proven defects. Source reuse is distinct from embedding a complete source page;
never include an entire file merely because one page was reviewed. Ready files collapse at export;
wrong-site, missing evidence, prices and unpreserved artwork remain targeted blockers.

## Source access, durability and genuine journeys

Approved originals are available in the owner's private acceptance Library; they are not missing.
The unchanged six-source archive is 88,159,285 bytes. Private manifests and original filenames/full
hashes stay out of public Git/CI. The synthetic evidence archive is separate. Library persistence,
local copies, source-code ZIPs, temporary media URLs and seven-day CI artifacts do not establish
independent non-OpenAI access or Render retention.

The supported shared-fixture/archive page previously returned Access Denied /
ERR_BLOCKED_BY_ADMINISTRATOR. The denied transfer must not be retried or bypassed using another
route/tool/session/proxy/encoding or a security/infrastructure change. Obtain the smallest supported
owner/admin resolution for that exact operation. The local managed browser also blocked localhost;
continue permitted code/AppTest work and the existing independent CI harness, not a policy bypass.
No unconfirmed Render workspace selection.

After legitimate resolution: upload unchanged originals through the supported flow; independently
retrieve full bytes/manifest and verify SHA256/size; repeat after a normal authorized deployment
with a different actually served revision. Do not create deployment churn for a retention claim.
Admission limits differ: archive96MiB, AUTH32MiB, ordinary Starting128MiB. Preserve expanded-package,
image/memory/queue/malformed-input bounds. Structural ZIP checks do not prove import or rendering.

For each authentic journey record exact original identity, target sites/month, pinned design,
independent retained/excluded expectations, warnings, preview and final bytes. Repeat import,
report-only clear/removal, save/reload and a fresh session. Preserve deliberate blanks, NR,
corrections, unresolved items and eligible pictures; exclude foreign facility facts. Changed-byte
and advanced per-item replay remain separate from PR247's unchanged-byte ordinary Starting fix.
The successful local different-site 20-block/12-asset diagnostic is not owner AUTH approval.

The incomplete same-site native-drawing preflight had a150s requested AppTest bound and254.651s
outer cleanup observation. No profile was published, no Continue/save clicked, original unchanged;
root cause remains unassigned. Keep its private script/receipt/log and distinguish launcher,
monitoring-driver and environment failures from production behavior.

## Native output, scope and device gates

Use actual approved masters/assets, not generic templates or guessed web images. Preserve editable
native tables, merged cells, units, source order, image aspect, captions, RFI continuation and links.
Contact headers must be true Facility/Role/Name/Phone/Email rows; test zero/one/many/long entries,
repeated headers and intact rows. The chart/matrix belongs alone; contacts start on the next page
without blank-page artifacts. Test portrait/landscape transitions on actual Word-compatible output.
LibreOffice rendering is not Microsoft Word acceptance.

Verify the corporate-office cover photo below the stripe (not the client logo), ENFRA assets,
photo-only grayscale, divider artifacts, section10, contents/AppendixG/page references, footers,
watermark intent, seams/crops and actual-scale legibility. Individual outage wording was approved;
the later stacked one-image/one-page composition still needs its own approval before canonical
installation. No redraw, changed time windows or duplicate individual-plus-combined insertion.

Privacy checks cover visible prose/tables and captions, graphic/OCR/EMF/VML/WordArt, headers/footers,
watermarks, comments, objects, metadata and retained package parts as applicable. Text scanning
alone cannot clear graphic/hidden channels. Preserve legitimate operational values and PO/Expense
prices; do not silently drop unreadable art to pass. One honest inclusion summary, no invented work.

Maintain one ordered Monthly editor, section-owned sticky preview pairs and the SAME tabletop
editor/scroll root. Keep toolbar-free continuous multipage scrolling. Measure responsiveness and
event-to-useful-preview time; visible content must become current, explicitly outdated, honestly
empty or specifically recoverable. Bounded visibility/raster work, generation leases, stale-result
rejection and export priority remain; no eager all-section rendering or hardware upgrade shortcut.

ADP-J01/J04 are Monthly book/tabletop; J02/J05 PO; J03/J06 Expense. Retain all ADP-A01–A20 coverage
IDs, SRC/CONT/VIS/UX/AUTH references and historical failures; no UX20 exists. Exercise asymmetric
segments/offsets, short sections, reverse scroll, keyboard-open fallback, missing APIs, rapid
transitions and source return. A screenshot is not mobile typing/upload/generation or physical
Safari/fold-device proof; iPhone Duo is only a prospective form-factor label.

Preserve PO exact source, original/change-order identity, leading zeros, totals and reviewed MSAPO
plus original two-file package; Expense receipt/split/trip identity, allocations/rates/rounding,
workbook/PDF mapping, signatures and intended recipient roles. No QA business sends. Layout/focus/
scroll cause zero AI calls, report assemblies, business submissions or standing writes. Keep the
unchanged512MiB/0.5CPU CI gate distinct from the previously observed Render1CPU/2GiB host.

## Restart and release rule

Refresh main, both PR heads and exact workflow results first. Read retained failed artifacts before
retrying an action. Keep code commits separate from acceptance claims and preserve unpublished
patches with exact base/blob identities. Save one useful TXT continuation plus necessary evidence in
the existing owner acceptance folder; never publish private client material. Rollback code by
revert, not data reset. No paid reviewer, migration, credentials, spending, security change,
business send or irreversible cleanup is authorized. Finish independent safe work when a particular
access, renderer, hardware or artwork-approval gate remains blocked.
