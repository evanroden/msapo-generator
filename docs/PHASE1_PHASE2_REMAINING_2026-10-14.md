# ENFRA Phase 1 / Phase 2 — remaining work

This is the single current remaining-work ledger. Historical evidence and failures stay in
`PHASE1_PHASE2_EXECUTION_2026-10-13.md` and the linked PR comments; they are not fresh defect counts.
Neither phase is accepted. Do not merge a stacked cleanup PR into its parent feature branch.

## Current integration checkpoint — October 17, 2026, 03:08 UTC

This checkpoint supersedes the dated branch table below. Both phases remain open.
No owner-source replay, physical-device, native-Word or combined-artwork approval is implied.

| Requirement / retained IDs | Implementation and integration | Tested scope | Actual served evidence | Review / next action / owner | Acceptance |
| --- | --- | --- | --- | --- | --- |
| Water pages; CONT09, SIM-W01–07, ADP-A12–13/A16/A20 | PR249 head358e97e merged normally to main90049cf65b7d19d2e96ec0ecf9a9b0288fdc476a | Exact branch Required38966735323 and Adaptive38966735321 pass. Current local Water review gate76 passes; five reviewed findings resolved with code/tests. Main38996467909/38996467782 were still running at this checkpoint. | Cloud Chromium rendered full90049cf and entry index.enfra-frontend-fbb0a97cf659.js. Independent pinned83-member reconstruction predicts that entry. Isolated Water editor opens; a caption sent with Done is retained and correctly requires renewed page review. This is a limited live path, not a new all-output walkthrough. | Finish the isolated correction/reopen/reload path, then merged-head gates. No generation used to wait for deployment. | Merged; served; partial browser verification. |
| Training; SIM-T01–07, ORIG-T01–05, UX21, ADP-A08/A11/A16–17 | PR250 retargeted to main; repaired4b3b6b2 then normally reconciled90049cf at c1d2ee1616357f31160dc937068f85a71521910f | New baseline:7 failures covering consecutive removal, distinct names, first-row defaults and missing filters;6 separate missing-instrumentation failures. Repaired47 checks pass, repeated47 after main reconciliation. Exact new CI pending. | Not yet merged or delivered. Existing dated date/output evidence remains scoped to its recorded revision. | Both filters now cover workspace_browser_observations.py and qa_monthly_live.py; older delivery/diagnostic helpers remain listed. Inspect new exact CI and current reviews before merge. | Implemented and locally tested. |
| Accepted source batches and history; SRC03–06, CONT04/06/08, ADP-A10–11/A16 | PR251 candidate follows92ec8cd7, retargeted to main90049cf | New exact baseline:7 failures/2 passes. Four first-batch failure cases now stay pending through rerun and correction; saved move and explicit removal retire source-owned pages while human notes/tables remain; history context resets cursor/cache/selection. Full affected gate58 passes. Displayed-version-window tests also pass on the pinned baseline and remain guards. | Not yet merged or delivered. | Retained receipts use page provenance, preserve explicit omission and equal unlinked human content, and never edit originals/history. Existing retained-intake and comparison-pagination findings checked against current code/tests. Publish and run integrated CI. | Implemented and locally tested. |
| Progress photos; SIM-V01–03, CONT07, ADP-A08/A18 | PR252 still based on older PR251; locator/re-entry candidate local | Original38967722620 first failure preserved unchanged:13,272,057 bytes; SHA2566f5268e432efcc58457e09ad44cc510aa8afa9024de5db276b678f79a2193ca5. Both retained DOMs compute “Photos per page Photos per page” using dom-accessibility-api0.7.1/jsdom26.1.0; the original exact single-name locator does not match. Local photo gate21 passes. | Not delivered. No assertion that density state was absent or broken; no final outputs exist for the failed journey. | Group-scoped native slider observation retains End/Home, adds keyboard values1–6 and compact editor re-entry. Reconcile PR251 first, then run both engines through the complete add/remove/Done/reload/output tail. | Browser acceptance pending. |
| Simplicity inventory97 / original113 / ADP-A01–20 | Existing branch cleanup preserved; inventory numbering unchanged | The live90049cf page still visibly contains older duplicate help/copy and secondary controls; branch cleanup is not claimed live. | Representative Water/editor inspection only. | Finish integration, then fresh/populated/imported/unresolved/save-failed/generated/recovered desktop and narrow reviews, words/actions/screenshots and exact residual corrections. | Open implementation/product review. |
| AUTH01–03, standing data, original retention, all-page/privacy/native/physical checks and combined artwork | All existing requirements and evidence boundaries below remain active | Exact private owner archive retrieved again:88,159,285 bytes, six originals plus manifest/README; full manifest-member verification is separate from importer replay. No consumed one-shot genuine diagnostic was repeated. | No new external original-shelf retention claim. | Owner/admin resolution of the specifically denied original transfer remains necessary; unavailable native/physical checks and separate combined-composition approval remain owner checks. Complete independent synthetic/code/output work meanwhile. | Open; precise external dependencies retained. |

Private first-failure ZIP retained as libfile_f02903c20d3c8191856bda8ef46ec69f.
Local JUnit receipts: pr249-review-current.xml; pr250-review-baseline.xml;
pr250-observer-baseline.xml; pr250-review-final.xml; pr250-integrated-review.xml;
pr251-review-baseline.xml; pr251-review-repair.xml; pr251-review-full.xml;
pr252-photo-locator-local.xml. Keep them with the one restart checkpoint.
The browser screenshot was captured but its documented shared-file synchronization did not
produce a readable local file; it is not claimed as a retained screenshot artifact.

## Historical branch and evidence boundary — October 16

Refreshed 2026-10-16 20:49 UTC. This candidate follows published parent1e3516e; no
new merge or live observation occurred. Child252 remains published8c53fb0, with new photo/history
repairs locally verified but not browser-accepted.
Later gate changes require another read. Statuses are
scoped: **Observed** = browser-observed; **Conditional** = source-only conditional; **Defect** =
reproduced defect; **Implemented** = implemented-needs-verification; **Verified(scope)** =
verified-for-a-stated-scope; **Blocked(dependency)** = blocked-on-specific-dependency. An unrun
acceptance row is not a defect. Overlapping test counts are never summed.

## Historical code and release — October 16

Main is `4ca42c59fe647d4cf1f766bfb2d232092e48f7cf`. Last independently verified actually served
SHA is the same, from [live38937063007](https://github.com/evanroden/msapo-generator/actions/runs/38937063007),
not a new navigation here. Its merged-head Tests38936148403 independently had2,711/0 failures/
errors/skips and Adaptive38936148447 passed. Two isolated live sessions completed six accepted
first-attempt generations and12 actual files. This is PR248 synthetic release proof only.

| Code | Exact head / reported base | Reported PR integration | Current gate evidence |
| --- | --- | --- | --- |
| [PR249](https://github.com/evanroden/msapo-generator/pull/249), open/unmerged | [1e3516e](https://github.com/evanroden/msapo-generator/commit/1e3516e5bfa52a4b27202b36418e3f272a4c0ef4) / main4ca | 1d337f83eae57f8779c255d6273f48c241b97911 | Tests38961181930:2,916 cases,1 standalone Water fixture failure,0 errors/skips; container/resource passed. Adaptive38961181932 fails full Water edit-state prerequisite and the separate diagnostic; ordinary Fresh passes both engines with strict errors. Previous0959 integration06ff580 had independently2,851/0/0/0 plus container/resource; Adaptive38953590080 failed only Fresh WebKit native RO. New caption/Done and stricter QA are not covered by that earlier count. |
| [PR250](https://github.com/evanroden/msapo-generator/pull/250), open/unmerged | [d7da87d](https://github.com/evanroden/msapo-generator/commit/d7da87daba5b83c00e0f566f0e1d6becd0d85664) /0959 | [a3a96dd](https://github.com/evanroden/msapo-generator/commit/a3a96dd714777843467c37cdd1195993a5984cc8) | Tests38954899047 SUCCESS, independently2,893/0/0/0 plus container/resource. Adaptive38954899153 FAILED only fresh Water WebKit native RO; native date job117155170545 independently passed its two-engine date/session/output scope and8 actual files. All108 actual PDF page instances and54 pages from two unique DOCX files are reviewed at readable scale; named LibreOffice renderers, synthetic scope only. |
| [PR251](https://github.com/evanroden/msapo-generator/pull/251), open/unmerged | [4c3dac2](https://github.com/evanroden/msapo-generator/commit/4c3dac25cf596e4f6c1b1b2a2f4ad85ab20d9aa2) /0959 | [a5bb015](https://github.com/evanroden/msapo-generator/commit/a5bb0157bad8c4433962a03229c9ec128c05ddc9) | Tests38954899530 SUCCESS, independently2,968/0/0/0 plus container/resource. Adaptive38954899330 FAILED only fresh Water WebKit native RO; all other existing families/full Water passed. |
| [PR252](https://github.com/evanroden/msapo-generator/pull/252), open/unmerged | [8c53fb0](https://github.com/evanroden/msapo-generator/commit/8c53fb0f356a054c76ec97b66ec0d87f6ab35ec3) /2514c | df5888e7089a2a72b60642a85b9b794e0cc34af7 | Required38961654234:3,390 cases,1 standalone Water fixture failure,0 errors/skips; container/resource passed. Adaptive38961654160: full Water prerequisite, Fresh WebKit native RO, photo stale controls, Chromium history headers fail; WebKit history passes its complete tail. Local photo/history114 checks pass, browser repair verification pending. |
| Current finishing candidate after529 | Published parent1e3516e reconciled normally; historycd15df0 and photoQA34fb3b7 applied | New exact integration/CI still required | Water Done collects captions and rejects stale incarnation/reset actions; history excludes only three guarded converter-runtime paths and uses actual comparison heading; new native photo journey checks durable edits, retained assets and actual outputs. This is not release proof. |

PR250/251 are based on PR249; PR252 is based on the workspace branch at4c. PR252529 already
incorporates published4c; this candidate also reconciles the separately published new parent1e3516e.
A reported integration SHA or mergeable value is not a merge. Merge the parent to main normally
only after justified exact gates, reconcile/retarget each child to main and inspect its own delta;
never merge a child into its feature parent. No docs-only deployment or CI dispatch is requested.

## Acceptance inventory — retain IDs; newest status is above

| Area / retained coverage | State | Evidence limit | Next concrete action |
| --- | --- | --- | --- |
| Release/dependency order; CONT01–02, ADP-A19–20 | Verified(scope) | Main4ca synthetic release only; current children remain unmerged. | Resolve current first failures, exact integrated and merged-head CI, then full actually served SHA/design before isolated live acceptance. |
| Full Water compact activation; CONT09, SIM-W01–07, ADP-A12–13/A16/A20 | Observed | 19d/970c: WebKit durable order[2,1], but one View preview action left aria-expandedfalse/pairOpen absent for20s; no browser error. Chromium completed actual files. Later full Water0959/384 passed. Original cause remains unknown. | Use retained1085→cbb5bd9 original-button binding/trusted-click probe on the next coherent build; keep one action, Current/image/output and visibility bounds. |
| Fresh Water/native dropdown; CONT09, SIM-W, ADP-A12/A16/A20 | Implemented | Exact0959 naturally delivered all three reconstructed primary/Tooltip/virtualizer bodies in both engines; both five-stage canonical tails complete. WebKit still has a native RO error. Zt/Cr source models do not identify its sole owner. | Inspect the exact native error onset/owner; preserve strict errors and source models' conditional-height limit. No whitelist, rescue, synthetic event or timeout change. |
| Identity/Help/sites/navigation; audit A01–14, SIM-G/S/C, UX01, ADP-A16–17 | Implemented | PR251 code and synthetic/AppTest scopes; current Required2,968 passes but overall Adaptive fails separate Fresh Water native RO. b2c initial keyboard selection passed but one later deselection failed without delivery evidence. | Verify exact native actions/focus and deep-link workflow/section recovery; retain one full-name site input and all Change/More details functions. |
| Save/recovery/history/admin; audit D/E/F, CONT01–03, SRC03, ADP-A10–11 | Implemented | PR251 status/history/admin exists;529 WebKit completes all nine cover stages then reaches three versions. Those older test prerequisites were corrected. Current8c WebKit completes its history tail; Chromium exposes a real header-accessibility gap now repaired locally with a semantic table. | Run the next coherent exact history/cover path; preserve dated author/version rows, read-only inspection/reload, both-version conflict choice, partial-output/shared-save errors and zero display-driven writes. |
| Training matrix/sessions/date; SIM-T01–07, ORIG-T01–05, ADP-A08/A11/A16–17, UX21 | Verified(scope) | Prior19d/970c date job117138939790 independently completed both baselines/repaired references/session/output tails and8 actual files. Currentd7da/a3a96dd independently repeats both-engine date/session/output success and8 verified files; overall Adaptive still fails fresh Water native RO. | All108 current PDF page instances and54 pages from two unique DOCX files are reviewed: CI PDF producer LibreOffice24.2; DOCX renderer LibreOfficeDev26.8alpha. Resolve the separate integrated native error; retain raw blank/Not recorded/Pending/Completed/Not required, unknown hours, one date, participants, stale-incarnation and standing/monthly separation. Physical/assistive audio remains open. |
| Organization notes/contacts; SIM-O01–08, SRC01–02, CONT07, ADP-A08/A11 | Implemented | Reproduced native overwrite/disappearing cleared notes/Add-contact early rerun;22 new AppTests and116 affected checks on recorded revisions. Published529 includes the repair. | Verify exact integrated native notes/reentry/Done/Add/source/recovery paths and scoped shared-save concurrency; retain true contacts schema/chart alternative/page-separation acceptance. |
| Progress photos; SIM-V01–03, CONT07, ADP-A08/A18 | Implemented | Reviewed5918438 application is published in529 with33 new native/source cases and81 affected passes. Exact529 Required3,295 passes. This candidate adds the real uploader/action/reload/output browser journey; its8c browser first run reproduces stale review controls in both engines. The new refresh and same-packet Activity/durable regression pass locally; a separate earlier setup failure is retained. | Complete the new exact composed source gate and real-browser upload/order/caption/Add/Remove/Done/reload/output journey; retain originals, reviews, density and unrelated text through the durable commit. |
| Sources/pages/CMMS/writing; audit B/C/D, SRC01/SRC04–06, CONT04/06/08/09, SIM-A/W | Implemented | Water model/broad source manager, non-Water atomic outcome and resolved-card/caption/read commits exist in separate scopes; not every conditional or authentic route accepted. | Trace each combined action to reachable Add files/reuse, Report pages, source manager, mappings/totals/help. Keep per-page decisions, reference-only distinction, missing/price/site blockers, unknown coverage/NR and grounded Add/Replace/Dismiss. |
| Scorecards/thermal/standing; SIM-SC01–05, CONT07, ADP-A11/A16 | Implemented | Synthetic source/UI/failure/concurrency checks do not establish authentic mapping, reuse or deployment retention. | Verify units/NR/qualified/missing values, contract/facility/service/system scope, safe first-fill/manual overrides, failed-save/retry/history and zero display writes. |
| Other sections/conditional artwork; audit C/D/F, SIM-M/MC/I/CR/P/R, SRC02/SRC05 | Conditional | Specific MBCx/RFI/proposals/issue-evidence/section-copy slices implemented with scoped tests; complete audit mapping and every conditional caller remain incomplete. | Reproduce the next actual gap before edits; preserve MBCx/onsite-vendor meaning, proposals decisions, RFI headers/continuations/Add, capital unknown dates, Subcontractor scope and safe unread-art recovery. Finish available code work independently. |
| Cover photo/replay/unread art; SRC02/SRC05–06, CONT03/07, SIM-C/A, ADP-A18 | Implemented | Ordinary report-only Change/Use/No photograph, source-bound explicit No-photo and consumed-source logo replay have synthetic/AppTest/native-package scopes. Neither authentic master nor all-channel privacy is accepted. | Verify exact integrated cover/history and source replay, retaining originals/current design pin, human Omit/Clear/removal, source/profile/month/role/incarnation/cycle guards and unread-art blockers. |
| AUTH01/02/03; ORIG-S04–06, CONT03/06–09 | Blocked(dependency) | Existing private originals and narrow local diagnostics are not owner-selected source→target expectations or genuine browser import/output acceptance. | Obtain only missing scenario labels/independent facts and supported access; real byte-identical import/review/merge, omission/reload/fresh-session/reimport and actual output tails. Do not request existing files again. |
| External originals/cross-deploy retention; CONT01, ADP-A10/A20 | Blocked(dependency) | Original transfer and managed localhost operations remain specifically denied. Library/local/CI persistence is not independent external-after-chat retention. | Obtain exact supported owner/admin transfer resolution; normal upload/download and independent full-byte/hash/manifest retrieval, repeated after a normal later different served revision. No bypass or deployment churn. |
| Native Word/PDF/master/privacy; CONT07, SRC06, VIS, UX21, ORIG-C/Q, ADP-A18 | Blocked(dependency) | Named synthetic bytes/rendering scopes are not approved authentic master, Microsoft Word, combined-outage approval or every graphic/hidden/package privacy channel. | Inspect all actual pages with exact source/build/design and named renderer; keep Microsoft Word, actual-scale combined artwork and physical checks separate. Continue independently reproducible native/privacy fixes. |
| Six adaptive journeys; ADP-J01–06/A01–20, UX04/22/23, CONT10 | Verified(scope) | Isolated emulated Monthly/PO/Expense book/tabletop/compact scopes only; active failures and physical/assistive/IME/latency/eviction/durability breadth remain open. | Preserve every coverage ID and one authoritative editor, asymmetric/reverse/keyboard/source return, scoped writes, PO two-file and Expense receipt/split/share-cancel integrity; no business sends. |

## Retained first failures and discriminators — dated scopes

- **Current automatic review, checked without starting another reviewer:** the older empty-Omit
  and no-source retained-content comments are already covered by current code and dedicated
  tests, including the actual Fresh journey. The restored Vendor-service-as-Water last-page
  route defect reproduces and is repaired in this parent candidate: one exact source-byte/
  section route marker survives report serialization, without representing an included image,
  approving a page, changing source classification or adding a source-schema field. Actual
  attachments retain precedence; wrong source ID/bytes/section/malformed markers cannot reroute.
  A new section session can deliberately re-include the excluded page once. Route-only metadata
  is excluded from the missing-support dependency scan; real narrative/page references still
  block missing-source output. Forty-five route/source/review checks pass. A95-case earlier
  affected run had94 pass and one new dependency-test setup failure: the synthetic template used
  demo_water, not the production water_reports block. Both setup failures are retained; correcting
  that schema makes the intended missing-source negative meaningful.
- **Finishing-source review fixes (local,37 checks pass):** source-manager Include now validates
  the displayed inherited caption before review, preserving deliberate absent/blank metadata
  and legitimate0/NR. Its first regression used Change even though priced material correctly
  opened under Review source files; the corrected native entry reproduces the enabled button.
  Reopening an actual Starting cover card now retains automatic_logo_skips and cannot silently
  reselect an exact preferred-logo skip. Existing exact-source/profile/month/role and explicit
  deselection recovery gates remain. First failing receipts remain separate from corrected tests.


- **Current1e/8c Water prerequisites (implemented):** both browser engines retain the
  clear caption with Done in working/durable state and complete its required review. Done closes
  the editor, so the next intentional edit must use ordinary Edit pages before Page to review.
  The standalone Required fixture also omitted the production caller's post-commit refresh;
  it now consumes that refresh only after its own returned source/block commit. No rescue
  gesture, timeout, native-error filter or business/output assertion was added or removed.
  The exact48 affected local checks pass; first CI failures remain preserved.
- **Current8c Progress photos (reproduced/implemented):** both browsers save both page reviews
  but earlier section controls remain stale. A full production-fixture AppTest reproduces this.
  The finishing patch requests one existing refresh after all image decisions, complete draft
  and recovery attempt. Same-packet Activity, both review decisions, matching journal and a
  no-change display rerun are checked; photo/history114 affected local tests pass.
- **Current8c history (observed/implemented):** Chromium paints the three real version rows,
  but the canvas fallback header is not exposed by the accessible-role locator. WebKit completes
  all nine cover and seven history stages including reload and another context. The finishing
  patch uses a real escaped, read-only HTML table for this immutable version index only, keeping
  native editable report grids, all dated authors/versions, inspection and conflict choices.
  Real header/row semantics and literal markup-like author text are locally tested; current
  Chromium/browser and physical assistive verification remain pending.
- **Floating UI resize feedback (conditional defect class, repair candidate):** original
  diagnostic12072454773 is6,154,563 bytes, SHA256
  `67c21b951bd22a82b064853349c2a4a86f623fc32d693faa49a2eb2156070801`.
  Exact native rn/vr and Aria callbacks reproduce a current-cycle width write at trigger depth19
  leaving independent popup/list observers at depths4/5 skipped. Five negative controls avoid
  it. The retained trace does not measure the width setter/microtask checkpoint or prove sole
  cause of the8218ms native error. This candidate defers only rn's RO-driven update into one
  cancelled/coalesced lifetime-owned frame. Initial, scroll, window resize, layout shift,
  animation-frame paths and native errors remain. Its own unobserve/reobserve is preserved;
  no global observer wrapper or eager render is introduced. Actual source model/lifecycle3
  checks pass; exact integrated source/publication and strict native browser gates remain.
  Two initial lifecycle test failures were model prerequisites: duplicate removeEventListener
  must be idempotent, and Node lacks a default IntersectionObserver. Their records remain.
  The archived one-shot derivative refuses the new generation and is not rerun. Ordinary Fresh
  now requires all four naturally delivered repaired body hashes, including Floating UI.


- **Water Done / same-packet caption:** two actual caller cases reproduced loss of nonempty/blank
  captions, and two held Leave-out cases reproduced stale incarnation/reset actions. Published1e3516e
  fixes both;85 affected AppTests pass. Its browser journey adds one clear-caption/Done operation,
  matching durable state and pending-review checks before the unchanged original tail. New exact
  browser CI remains required; this is separate from native RO ownership.
- **529 Fresh / Adaptive38957483651:** Chromium reaches zero/one-site but the same connected idle
  Reporting month input opens then closes about38ms after one native click; no final option appears.
  Native Tooltip scroll-close code is reachable but actual close cause is unassigned. WebKit completes
  all five canonical stages, verifies all three body pins and retains a native RO error. No rescue
  gesture, settling delay, larger timeout or error exception is justified by these observations.
- **529 history, same run:** Chromium fails before upload only because render-jobs/.active-office.json,
  an exact78-byte temporary converter process marker, disappears through the existing office cleanup.
  All report/journal/version/asset state is unchanged. WebKit completes all nine cover stages and reaches
  the three dated versions, then uses obsolete comparison heading Activity summary instead of actual
  Work completed this month. These are proved harness causes, not proved data loss. Current fixes
  retain namespace/link/count/byte guards, all unknown render files and same-named files elsewhere;
  only three exact converter runtime paths are excluded. Standing-file disappearance still fails.
  Both saved/current content and read-only/reload/second-session assertions remain. Nine runtime
  cases and the actual comparison AppTest pass; prior composed78 pass predates the final stat-race case.
- **New photo QA local setup:** composed103 cases had102 pass and one existing run_web setup timeout
  before any photo action. Its cause is unassigned and no unchanged retry was used. Sixteen new cases
  passed; later10 cleanup/PDF-negative cases passed. The current candidate has additional exact
  integration checks pending. The output matcher rejects extra known photo-page images, including
  unexpected color models; it does not claim unrelated aspect classes or manual all-page acceptance.
- **0959 fresh Water / Adaptive38953590080:** WebKit RO at46,021.636ms during September option;
  both engines completed all five durable stages and verified three exact naturally requested
  asset bodies. Every earlier family/full Water passed. Required2,851 is independent CI proof,
  not native-error acceptance. The responsible native observer owner remains unassigned;582a6bc is
  unpublished stricter native-window evidence, not a demonstrated application repair.
- **Current child confirmations:** d7da/a3a96dd Required2,893 and4c/a5bb015 Required2,968 independently pass with zero failures/errors/skips. Their overall Adaptive gates fail only fresh WebKit RO at46,250.766ms and45,750.339ms respectively, both during September selection despite three naturally received body pins matching reconstructed locked assets. Both five-stage canonical tails complete. These confirmations do not identify the native observer owner.
- **384 fresh Water / Adaptive38952943302:** WebKit RO at36,522.774ms; all five stages complete.
  That build delivered the older Tooltip generation and has no0959 Cr repair. Full Water and
  all10 first-site paths passed; this does not explain earlier failures.
- **384 history, same run:** Chromium upload-only exact storage equality failed after unchanged
  draft/assets/history receipts; the failed controller inventory was not retained, so its first
  cause remains unclassified. WebKit's later Use was rejected by an overbroad shared-assets
  assertion even though the new photo's exact immutable object/link/empty bucket lock is permitted
  report recovery. Local693→67932f4 preserves bounded path inventories before assertion and
  allows only those exact explicit-action additions. Upload-only/display/reload still require
  equality; profiles/history/standing/other journals/old assets remain fixed. New browser proof open.
- **19d compact Water / Adaptive38950074630:** one native View preview action failed eligibility;
  no visible indefinite blank/data-loss or observer cause was shown. Keep1085→cbb5bd9 probe and
  the existing20s/Current/image/output predicates; no retry/rescue or eager rendering.
- **c114 Month activation /38944314371:** same connected idle native input focused, popup not
  observed, exact September option timed out. Passive Month evidence is retained; later passes
  or either resize repair do not establish the original activation cause.
- **b2c first-site /38947283726:** initial zero→one keyboard selection passed; later UMMC
  deselection failed in one WebKit path with no last-action wire/trace. Passive8526 evidence
  preserves all30 original actions/predicates, no intergesture wait/evaluate. No checkbox
  application repair is justified by the old capture; this observation is not a pass.

Detailed original EncodingError/native-commit/cache/caption/retained-art/No-photo/replay and invalid
harness first failures remain verbatim in the [94116f8 history archive](PHASE1_PHASE2_EXECUTION_2026-10-13.md#retained-october-16-implementation-and-ci-history--from94116f8).
A later success neither erases an unexplained failure nor converts a proved harness defect into
an application defect.

## Retained workspace behavior and coverage pointers

Every combined control still needs a reachable action/state/scope. Detailed implementation and
first-failure wording is byte-preserved in the941 archive, including:

- Identity/help: searchable full names/logos; one title/contract-sites-month/Change strip; month/year
  together; native full-row checkbox; aliases/group/region/scoped save in More report details;
  one attribution Prepared by and actual focus links; meaningful Jump/deep links; diagnostics/admin.
- Saving/recovery: acknowledged working versus unsent input and immutable shared version; real
  dated author/history rows; one Create Word/PDF; split output/shared-save failures and targeted
  retry; mandatory checks; explicit browser-scope discard and two-version concurrency choices;
  shared-write Continue consequence, master pins and scoped contact administration.
- Sources/writing: eligible reuse/exact formats and limits; deliberate disclosed external reading;
  page include/exclude/review/caption/order and originals; reference-only distinction and no blanket
  approval; metadata/mapping/CMMS unknown coverage/NR; native tables with every narrow column;
  source-bound facts/proposed Add/Replace/Dismiss and separate Copilot flow.
- Sections: chart/picture/contact alternatives and actual standing scope; approved outage only;
  Progress photo review/density/caption/order; utility versus thermal; grounded MBCx/onsite/vendor
  Activity; Subcontractor/MSA scope; issue Remove/Clear/Include again and Evidence; unknown capital
  timing; current-month proposal decision; native RFI continuation; Training raw status/date/hours.
- Conditional art/previews: reproduce before removing recovery; stable cover choice cannot approve
  unread art; preserved drawings/SmartArt/VML/OLE originals/retry; honest standing-write scope;
  actual eligible visible surface before Current; toolbar-free normal multipage scrolling,
  bounded cache/raster/generation leases and specific recoverable errors without blanket waivers.

The existing execution crosswalk retains all [113 original scenarios](PHASE1_PHASE2_EXECUTION_2026-10-13.md#original-113-scenario-crosswalk),
[97 simplification records](PHASE1_PHASE2_EXECUTION_2026-10-13.md#all-97-simplification-records),
[six source safeguards](PHASE1_PHASE2_EXECUTION_2026-10-13.md#six-conditional-safeguards),
[CONT01–CONT10](PHASE1_PHASE2_EXECUTION_2026-10-13.md#continuation-requirements--cont01cont10-current-crosswalk),
[ADP-A01–A20](PHASE1_PHASE2_EXECUTION_2026-10-13.md#adaptive-acceptance-all-20-categories) and
[ADP-J01–J06](PHASE1_PHASE2_EXECUTION_2026-10-13.md#six-first-class-adaptive-journeys).
IDs are coverage references, not defect counts or renumbering. Original owner audit A01–A14,
B01–B12/B08–B09/C05–C08/C14–C16/D04/D06/D/E/F and SRC/CONT/VIS/UX/AUTH remain; no UX20 exists.
Historical SIM numeric-to-exact-copy attribution remains unavailable; do not invent it.

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

## Next integration, restart and release rule

1. Complete and publish the bounded Floating UI repair plus Water prerequisite corrections after
   exact source/publication tests. Preserve first failures; no repeat owner diagnostic or unchanged gate retry.
2. Reconcile the actually published parent into the photo/history repair batch, refresh main
   and all four PR refs, reported/tested integration SHAs and exact Required/Adaptive results.
   Reconcile dependent ancestry and inspect each own delta. No child merges into a feature parent.
3. After justified normal integration, verify exact merged-head CI independently, then full
   actually served SHA/design before permitted isolated live acceptance. A deployment wait timeout
   is not generation failure. Roll back code by revert, never a data reset or owner-conflict choice.
4. Continue all independent implementation and acceptance while a specific source-access,
   renderer, physical-device or artwork approval dependency is blocked. Exact owner checks are
   supported transfer/scenario expectations, specifically combined artwork and unavailable native/
   physical review; no repeated original upload or hash work is assigned to the owner.

Keep code commits separate from acceptance claims and preserve unpublished patches with exact
base/blob identities. Save one useful TXT continuation plus necessary private evidence in the
existing owner acceptance folder; never publish private client material. No paid reviewer,
migration, credentials, spending, security change, business send or irreversible cleanup is
authorized. This documentation commit is held for the next coherent implementation publication;
no docs-only production deployment or CI dispatch is authorized by the compaction.

This branch reconciliation normally merges published358e97e into 4c3dac25cf596e4f6c1b1b2a2f4ad85ab20d9aa2.
Its preceding complete ledger remains retained at that Git commit (SHA256
1f7a1b7530ca7ea8c6f7b40408feb7c92137eab636ef22a7da084c139c772fc3); the compact current ledger preserves every coverage ID.
All branch-specific application and QA paths remain, with exact composed checks and new CI required.

PR251 additionally takes the exact already-published28a13b4 semantic history table and its
regression, so the known Chromium header-accessibility gap is fixed in the owning history
branch before integration. The prior103-case reconciliation pass precedes these two byte-exact
backports; targeted history verification passed21 checks, zero failures/errors/skips,15.35s. The
reconciled workspace/source/Water gate passed103 checks,62.41s. New exact CI remains required.
