This file preserves dated execution history and coverage crosswalks. The only current status and
next-action ledger is [PHASE1_PHASE2_REMAINING_2026-10-14.md](PHASE1_PHASE2_REMAINING_2026-10-14.md).
Historical words such as current/pending describe their original snapshots and do not override it.

# ENFRA Phase 1 and Phase 2 execution and evidence ledger

**Current October 14 remaining-work checkpoint:** [PHASE1_PHASE2_REMAINING_2026-10-14.md](PHASE1_PHASE2_REMAINING_2026-10-14.md). It supersedes the dated pending-status lines for PRs #220/#222/#223/#224/#228 (all merged), distinguishes current implementation, test and owner-acceptance gaps, and identifies active noncompeting branches. The historical 113/97/source/adaptive evidence below is retained for traceability, **not** a current defect list.

## October 14 external-agent reference shelf — upload pending

The owner supplied six original documents for future testing. Their private originals, source SHA-256 manifest and one portable ZIP are retained in a persistent **ChatGPT Library** folder, which is *not* a generic external-agent download service. No document bytes, document names, source digests, extracted images or pricing data are to be committed to public Git, CI or logs. Deleting this chat must not be confused with proof of independent third-party hosting.

`app/monthly_report_shared_source_bundles.py` adds a **bounded immutable reference ZIP shelf to the existing hidden, no-login shared QA area**. It uses the same explicitly rooted Render-mounted test storage and no-follow/marked-directory/atomic-transaction primitives as existing shared fixture storage, but never treats a reference ZIP as an AUTH01/02/03 report or working import. It validates six manifest-declared DOCX/PDF originals by length and full SHA-256 without extraction, rejects undeclared members, traversal, symlinks and oversized archives; retains previous originals on failed admission; and exposes read-only metadata plus an explicit hash-verified download. Each browser downloads only on deliberate Prepare/Download, not on every editor fragment. There is no deletion action, reset coupling, standing-data write, external reader, private service, hosting-plan change, or second report importer.

**State boundary:** Source-bundle code/tests on `feat/shared-external-source-bundle-20261014` are not proof the Render disk contains the user files. An external-agent availability claim requires the one-time real ZIP upload into the served hidden testing UI, browser download SHA-256 comparison, and a second-browser **and redeploy/restart** read. The portable ZIP is 88,159,285 bytes, inside the 96 MiB admission cap; the existing authentic DOCX scenario importer remains separately capped at 25 MiB and cannot directly take the largest source. No AUTH scenario labels, target sites, owner expectations or half-finished status have been inferred. The hidden test area has **no login**: anyone who discovers its link can view/download the source ZIP; this is not confidentiality.


## Persistent cross-chat test evidence — October 14 (Library, not public Git)

The owner requested test artifacts be retrievable by later agents instead of relying on short-lived Actions downloads or ephemeral container files. The eight archived artifacts and manifests were uploaded and their existence re-read through Files Library at:

`/ENFRA/MSAPO/Acceptance-Evidence/2026-10-14/`

Start with `ENFRA_MSAPO_2026-10-14_evidence_README.md` and `ENFRA_MSAPO_2026-10-14_evidence_manifest.json`. The manifest gives SHA-256, sizes, source GitHub workflow run and tested source SHA for each archive. Saved synthetic evidence includes original failed main adaptive WebKit screenshots/DOM (`a8b49ba5`), passing PR #224 Chromium/WebKit evidence (`a41f2732`), synthetic PR #223 DOCX/PDF plus offline page render, and the predecessor failed two-session live run (`c90fd926`). These are **distinct evidence levels**, not a single passed release run.

The Library is accessible to future agents operating in the **same owner Library account**, not anonymously to unrelated coworkers. Customer originals remain separately in the owner Library with a private source-integrity inventory; no original file was placed in public Git or the anonymous shared fixture vault. This Library archive does not select AUTH01–03 scenarios or prove genuine client exports. Future runs should use their own dated Library subfolder, preserve all SHA/commit/run lineage and keep this index current.


## October 14 native Word table null treatment — UX21/P15

In the native editable table mapping `_table`, a missing Python `None` value was coerced with `str(value)` and therefore printed the literal **None**. The generic DOCX fallback assigned untyped values directly to `python-docx` cells and could fail on `None`/numbers. Its supplemental imported-table nonempty check also called `strip()` on each value and could fail on missing cells. This is a bounded code-path defect, not proof of the particular owner-observed table until the actual RGH/UMMC originals and exports are inspected.

The targeted fix preserves source/schema/native rows and columns; writes **blank** for absent values, **0** for zero (never suppresses an actual measurement), and preserves explicit `NR` as entered. Supplemental table inclusion accepts a substantive zero without claiming missing data are zero. Exact values and tests are generated from synthetic data only; preflight, provenance, no-price checks, original assets, standing records and report history remain unchanged. Regressions cover a native table and generic Word tables including imported two-column rows. The running branch's CI and native page proof must be recorded separately before merging; no actual RGH/UMMC visual or owner Word/Adobe acceptance is implied.


## October 14 continuation: WebKit preview/editor event ordering, P02/ADP-A08/A12

On exact main `a8b49ba5`, required Tests [38565624910](https://github.com/evanroden/msapo-generator/actions/runs/38565624910) and the separately serialized exact-served two-session Monthly Live [38566671602](https://github.com/evanroden/msapo-generator/actions/runs/38566671602) passed. However adaptive [38565624873](https://github.com/evanroden/msapo-generator/actions/runs/38565624873) **failed** in WebKit, with actual Expense `Cached ForwardMsg MISS`, Monthly tabletop selected-page decode and shared-fixture `EncodingError: Loading was canceled`. The Expense wire trace shows a full rerun and an expense-preview fragment both dispatched before either response (events 15 and 16), followed by a fragment cached-hash reference after full replacement. This is evidence for a real competing-message window, **not** proof the same root cause explains the other two failures. Chromium and the prior PR-head adaptive pass remain distinct evidence. The source-branch change on `fix/preview-checkbox-click-race-20261014` captures only native checkbox/radio label activation in addition to native change, suspending fragment sends until the workspace's distinct completed full-render receipt. Node regression checks click-before-change, label-focus exclusions, deferred callback, idle receipt and cleanup. Branch CI/Chromium/WebKit outcomes remain to be recorded; do not mark the browser issues closed from this code change alone.

Render workspace `My Workspace` was explicitly confirmed for this continuation. Read-only Render deployment/events show `a8b49ba5` deployed successfully at 12:41 UTC, with no server-failure event in the inspected window; request metrics record 502s near the `c90fd9` and `a8b49b` deployment windows. This identifies HTTP symptoms but does not prove a site-selection cause or restore interrupted unacknowledged edits. The Render production instance is 1 CPU / 2 GiB; the configured 512 MiB / 0.5 CPU test resource gates remain required and were **not** raised to conceal latency.


## October 14 preview cache race repair — P02/UX04/UX22, PR #222

[PR #222](https://github.com/evanroden/msapo-generator/pull/222) starts at merged main `c90fd926` (PR #220), preserving continuous toolbar-free previews and existing preview workers. It addresses a **code-proved cache race**, not a proved cause of the tester's 15–25-second delays: the PDF could be evicted between `STORE.available` and `STORE.pages`, after which the component previously said `Current · N pages` or `Preview · N pages` while supplying no raster. Monthly now removes that failed ticket and requeues the same current section through the existing visibility/bounded worker or exposes an exact Retry. Shared PO/Expense reference viewing invalidates the missing disposable source ticket and exposes a specific Retry rather than a success receipt. Decode errors become recoverable and are never called current. Same-report stale previews are still marked as older; no other report's bytes or prior edit is promoted.

Focused regressions in `tests/test_monthly_report_section_preview.py` and `tests/test_reference_preview.py` simulate the eviction precisely after availability, an unreadable raster and recovery to the correct page indices. **Status: branch changes committed, exact-head CI and actual browser/served checks not yet concluded when this note was written.** P02 time-to-first-useful-page, image-heavy contention, editor responsiveness, long tasks and gray/frozen incidents remain open. No Render service resource, storage policy, source, prepared report, design pin or history was changed. Rollback is a code revert, not a standing-data reset.


## October 14 continuation: P03 and pointer-from-zero coverage (PR #220)

**Status is in progress; owner/device, live served and authentic Word/PDF acceptance are NOT established.** The Oct 14 10:37 UTC baseline is [main `e5dd65b3`](https://github.com/evanroden/msapo-generator/commit/e5dd65b3ae23e610c15f6b66e26e5352d3cbd05d) after docs-only PR #218. Its [required 38549625249](https://github.com/evanroden/msapo-generator/actions/runs/38549625249) and exact-served two-session [monthly live 38550544129](https://github.com/evanroden/msapo-generator/actions/runs/38550544129) were previously verified; that evidence belongs to that served/runtime code, not this new branch. No current authenticated Render workspace was selectable through the connector.

[PR #220](https://github.com/evanroden/msapo-generator/pull/220) implements the new authoritative **UX23/P03** requirement in the shared Monthly/PO/Expense viewer: continuous normal scrolling at actual pane width, bounded lazy page requests with placeholders, browser-native zoom/pinch, selectable scrollport and failure-only Retry; no page/fit/percentage/enlarge app toolbar, no focusable hidden controls. The existing worker/generation/cache and business export paths were not changed. Node lifecycle tests assert removal and actual scroll/reading anchors; real synthetic Chromium/WebKit paths now scroll multipage sections, quote/PO forms, receipts and packet outputs without menu controls.

**P01/UX01 coverage is intentionally narrower than closure:** synthetic browser checks select from **zero checked sites** using one native label click and independently verify keyboard and draft scope. They have not reproduced or resolved a genuinely fresh report's very first mouse/touch on each checkbox square, text label and large row target in clean sessions. Do not promote these partial checks to full first-selection acceptance or infer every checkbox is broken.

**Evidence ledger boundary:** [initial required run 38557263515](https://github.com/evanroden/msapo-generator/actions/runs/38557263515) passed on partial code head `692b5766` (including production/container/resource), **not** on the later browser-test amendments. [Earlier adaptive run 38558506125](https://github.com/evanroden/msapo-generator/actions/runs/38558506125) on `38c92276` failed a WebKit Expense check that incorrectly required the *entire naturally scrolling panel* to fit inside the viewport; its downloaded synthetic artifact identified the measured panel. That is not evidence of an inaccessible page. The latest subsequent code fixes the measurement to check real scroll reachability and clipping. The exact-head required, adaptive and deployed gates must be re-checked after the **final** PR commit; do not relabel either earlier result. Previously passed generic/PO/Monthly Chromium/WebKit samples, shared fixtures and 18/18 synthetic source assertions remain scoped to their run.

**Remaining owner-supplied evidence:** P02 connected visible image-heavy preview latency/502 diagnosis and truthful stale/failure; P01 truly fresh pointer/touch; P04 conflicts/outages; P05 direct date and attribution links; P06–P10 native numbering/contents/cover/logo/chart/table/print treatment using retained hashed RGH 17-page and UMMC 19-page exports, approved master and Word/Adobe; P11 specific **combined** workflow layout approval (individual wording approved, combined layout not yet verified); P12–P15 site-keyed standing/source/training/everyday use; AUTH01–03 **owner-selected genuine DOCX originals** with independent expectations; all ADP-A01–A20 and ADP-J01–J06 remaining device/IME/lag/artifact breadth. Superseded zoom and Previous/Next requirements remain superseded; UX20 does not exist. No public repository owner fixtures, approval bypass, hosting change or bulk history rewrite is permitted.


**IN PROGRESS — neither phase is release-accepted.** This is the current resumable execution record for the October 13, 2026 handoff. Both phases are authorized. Older instructions to defer Phase 2 are superseded; older valid evidence remains bounded to its original commit, input and assertion.

## Latest synthetic release gate — October 14, verified after 05:05 UTC

**Product main `ad55fb6b9e043f10812224f00c9c17b78845ff8e` has now passed ALL THREE separately executed, exact-SHA synthetic gates:**
- [Required 38513548917](https://github.com/evanroden/msapo-generator/actions/runs/38513548917) **SUCCESS**, 2,491 passing pytest cases (two existing openpyxl warnings), healthy production container, generated synthetic Word/PDF and 512 MiB / 0.5 CPU resource checks.
- [Adaptive Chromium/WebKit 38513548892](https://github.com/evanroden/msapo-generator/actions/runs/38513548892) **SUCCESS**, actual synthetic PO, Expenses, Monthly and shared-fixture Starting workflows.
- [Serialized deployed-live 38513993073](https://github.com/evanroden/msapo-generator/actions/runs/38513993073) **SUCCESS**, exactly this main served on Render, two isolated first-attempt Chromium sessions with synthetic source replay/Word/PDF/privacy, durable Activity actions and isolation. A successful CI job on a code SHA is not native MS Word/Adobe or Safari hardware acceptance.

**Previous real failure remains recorded:** [main `d261a835` live 38513519449](https://github.com/evanroden/msapo-generator/actions/runs/38513519449) failed the first session's durable Activity re-entry receipt after deliberate clear, with artifact 11870624024. A possible intervening code deployment is **not established as the cause**; no retry or weaker assertion was used to conceal it. The later exact `ad55fb6` first-attempt success is a separate passed gate, not a relabelled earlier failure.

**Release acceptance is STILL IN PROGRESS** pending the explicitly selected already-uploaded **synthetic** shared DOCX original's byte-for-byte SHA across two observed distinct Render served code revisions, actual owner **AUTH01–03** with independent source/site/month/expected-section evidence, human inspection of native Microsoft Word/Adobe page geometry and genuine owner documents, and shipping physical Safari/tablet/foldable acceptance. The PR #214 read-only fixture verifier is merged but has **not** been executed against a selected production original. The no-login test route is anonymous/discoverable; neither phase can be declared owner accepted from synthetic tests alone. No authentication, Render disk/plan, billing, credentials, owner originals, fixture deletion or standing report changes are authorized by this ledger.

**This new first section supersedes older "in progress", "not yet merged", and "current main" assertions below only as chronological status snapshots; old failures and the original 113 ORIG / 97 SIM / 251-case crosswalk remain unchanged.**

## Exact combined-main synthetic verification update — October 14, after 04:56 UTC

**Main `ad55fb6b9e043f10812224f00c9c17b78845ff8e` Required [38513548917](https://github.com/evanroden/msapo-generator/actions/runs/38513548917) passed** **2,491 pytest tests / two existing openpyxl fixture warnings**, production healthy container and 512MiB/0.5-CPU resource probes. **Its separate adaptive Chromium/WebKit [38513548892](https://github.com/evanroden/msapo-generator/actions/runs/38513548892) passed** the geometry, PO, Expenses, Monthly and shared fixture/actual Starting workflow checks. **Public exact-served synthetic two-session live [38513993073](https://github.com/evanroden/msapo-generator/actions/runs/38513993073) was still in progress at this snapshot**; do not transfer the earlier success to this exact SHA or call both phases release accepted.

**A separate real red earlier live gate must remain visible:** [d261a main live 38513519449](https://github.com/evanroden/msapo-generator/actions/runs/38513519449) **FAILED in its first session** after independently verifying the served `d261a` commit, known-value prefill **18/18**, accepted Generate, actual synthetic Word/PDF/privacy, Activity edit/refresh and explicit clear/refresh. Reentry after that deliberate clear did **not** produce the exact new durable Activity SHA within 90s. Its artifact **11870624024** shows a blank Activity editor and no accepted reentry receipt. Attributing this to the ZIP timestamp test change would be unsupported; a contemporaneous auto-deploy might have interrupted the session, but **that cause is unproven**. No retries, relaxed receipt assertions or reinterpretation as PASS were applied. The new exact-main live run is a separate first-attempt gate. Keep old red and new pass/fail at their own SHAs.

## Latest combined code main checkpoint — October 14, after 04:47 UTC

**Current main `ad55fb6b9e043f10812224f00c9c17b78845ff8e`** merges **PR #216** on top of **PR #217** and all earlier code/ledger/fixture changes. The prior PR #216 exact amended head `212d7a7c6c119558e0693aaffbee014c4d1f7fda` passed [Required 38512806106](https://github.com/evanroden/msapo-generator/actions/runs/38512806106) (all 3 jobs) and [adaptive 38512806195](https://github.com/evanroden/msapo-generator/actions/runs/38512806195) (Chromium/WebKit actual synthetic workspaces). It prevents one source-wide vendor/date from being falsely attributed to multiple different source events and stops a standalone `Completed date: 09/12/2026` label from being narrated as actual completed maintenance. Original data, evidence refs and manual edits remain intact. The earlier failed [PR #216 Required 38512165198](https://github.com/evanroden/msapo-generator/actions/runs/38512165198) and test-only ZIP timestamp failure [PR #215 38511712439](https://github.com/evanroden/msapo-generator/actions/runs/38511712439) remain historical truthful failures; each was corrected in reviewed narrow changes.

**Independent main gates:** prior code main `d261a835938ab46240d668451ca5682a061c33dd` passed [Required 38513053225](https://github.com/evanroden/msapo-generator/actions/runs/38513053225) after merged PR #217; its automatically queued live run [38513519449](https://github.com/evanroden/msapo-generator/actions/runs/38513519449) was **in progress** as main moved and may skip under the exact-main gating rule. New `ad55fb6` [Required 38513548917](https://github.com/evanroden/msapo-generator/actions/runs/38513548917) and [adaptive 38513548892](https://github.com/evanroden/msapo-generator/actions/runs/38513548892) were **in progress/queued** when this entry was written. Its serialized public served-build two-session QA must independently finish on exact `ad55fb6` after CI; neither a passing PR branch, skipped run, old main live or merged commit alone establishes that.

**Owner-facing remaining acceptance still open:** real AUTH01–03 owner originals with known source/target and independent expected content; one specifically chosen synthetic original SHA surviving a real Render code redeploy; human review of actual client Microsoft Word/Adobe pages, contacts, graphics and pagination; physical shipping Safari/tablet/foldable posture. A local-only synthetic AUTH01 witness is available, but was **not** uploaded to the anonymous shared fixture page and cannot establish persistence without a genuine selected production fixture ID. The opt-in read-only verifier is merged but unexecuted. Do not mutate or purge standing/fixture originals, Render config, credentials, billing or access policy. Phase 1/2 release acceptance is not declared.

## Native ZIP invariance test fix and source attribution guard — October 14, after 04:45 UTC

**Current integrated main is `d261a835938ab46240d668451ca5682a061c33dd` (merged [PR #217](https://github.com/evanroden/msapo-generator/pull/217)).** Its exact head `8e8a4a3b248ebff11edfc184220719a182dfc0c2` [Required 38512381448](https://github.com/evanroden/msapo-generator/actions/runs/38512381448) completed **2,483 pytest passed / 2 existing openpyxl warnings**, production healthy container and 512MiB / 0.5-CPU resource probes. It fixes a `python-docx` no-op test that falsely compared compressed ZIP archive header timestamps across successive saves. The replacement compares all actual native DOCX package filenames/compression types/uncompressed bytes and proves a real `word/document.xml` mutation still fails. This is a **test-only** correction; no production generator change or assertion bypass. Prior documentation head [38511712439](https://github.com/evanroden/msapo-generator/actions/runs/38511712439) **really failed** the original ZIP timestamp comparison despite its 2,481 other passes. This run is retained and the prior docs-only [PR #215](https://github.com/evanroden/msapo-generator/pull/215) is superseded by a new, exact-main docs branch rather than merged red.

**Exact merged-main d261a validation is independent:** [Required 38513053225](https://github.com/evanroden/msapo-generator/actions/runs/38513053225) was still **running** at this checkpoint. As a tests-only patch, PR #217 does not trigger path-filtered adaptive DOM on this SHA; the latest all-workspace Chromium/WebKit pass was [38504975128](https://github.com/evanroden/msapo-generator/actions/runs/38504975128) on product main `0dced24`. Earlier current product main `018d29b` passed [Required 38511539695](https://github.com/evanroden/msapo-generator/actions/runs/38511539695) and [serialized exact-served live 38512073440](https://github.com/evanroden/msapo-generator/actions/runs/38512073440). Those are **not** the same SHA as d261a.

**Open, unmerged functional guard [PR #216](https://github.com/evanroden/msapo-generator/pull/216):** source-native unstructured DOCX/PDF/email with multiple vendor/date labels must not assign its first global vendor/date to every later event; preserve original action text and only omit ambiguous global date/vendor prefixes while leaving TXT/CSV per-event identity intact. First head `cb21dcb` [adaptive 38512165290](https://github.com/evanroden/msapo-generator/actions/runs/38512165290) passed, but [Required 38512165198](https://github.com/evanroden/msapo-generator/actions/runs/38512165198) failed **one genuine date-only metadata output problem**: `Completed date: 09/12/2026` had been misidentified as completed work. The patch now explicitly rejects date-only labels while preserving actual `Completed ...` work; a positive regression was added. Current amended head `212d7a7c6c119558e0693aaffbee014c4d1f7fda` [Required 38512806106](https://github.com/evanroden/msapo-generator/actions/runs/38512806106) and [adaptive 38512806195](https://github.com/evanroden/msapo-generator/actions/runs/38512806195) require independent exact-head SUCCESS before a merge; the latter has passed while Required was still running when checked. Do not treat any previously failed run as green.

**Synthetic witness for deferred Render storage proof:** an independent, invented one-page AUTH01 September source DOCX has been prepared *locally only*, SHA-256 `f6753b5ead22e7b7dcafab9f45c7a16f0a607a61838422339125c205f084211d`, 39,072 bytes, invented contract/site/month; no client or owner data and **not uploaded to production or GitHub**. The opt-in, hash-only workflow from merged [PR #214](https://github.com/evanroden/msapo-generator/pull/214) cannot run without the actual shared fixture ID provided by the real production upload and two observed distinct Render served SHAs. No user-selected authentic report, free-space/redeploy confirmation, physical Safari/foldable acceptance, or per-page native Microsoft Word/Adobe approval exists.

**Release status remains IN PROGRESS.** Do not mutate Render workspace, plan, billing, credentials, originals, existing reports, standing data or anonymous test access controls. Original 251 tracking cases and historical failures remain below; this dated checkpoint supersedes older open/merged statements for these PRs.

## Final-code integration checkpoint — October 14, after 04:28 UTC

**Current main is `018d29b65fadd002e28099c2932c56db609df8f4` through merged [PR #214](https://github.com/evanroden/msapo-generator/pull/214).** On exact predecessor main `2a255066a119f213ed540938060ee5d66e362b90` (merged PR #213), [required 38509979187](https://github.com/evanroden/msapo-generator/actions/runs/38509979187) and [deployed serialized two-session synthetic live 38510386132](https://github.com/evanroden/msapo-generator/actions/runs/38510386132) **passed**. Last applicable adaptive Chromium/WebKit on product main `0dced2428955f657736e7aa74ac555a31dc82a05` passed [38504975128](https://github.com/evanroden/msapo-generator/actions/runs/38504975128). PR #213 adds synthetic AUTH01–03 source/target/starting importer/regeneration identity and exact immutable original reopen across separate Python processes. This is **not** actual owner report acceptance and a process restart is **not** a Render code redeploy. Tests-only PR #213 did not trigger the path-filtered adaptive workflow, nor does the script/docs/workflow-only PR #214.

**PR #214 opt-in read-only persistence witness is merged, not exercised against a selected production original.** Exact PR #214 head `a0a117a44fa34ad210cab4e8d401e33c2ab5ac57` [required 38510951554](https://github.com/evanroden/msapo-generator/actions/runs/38510951554) passed all three jobs: full pytest/synthetic Word and PDF, production healthy container, and 512MiB/0.5-CPU resource probe. This adds manually dispatched [Shared Fixture Redeploy Read-only](https://github.com/evanroden/msapo-generator/actions/workflows/shared-fixture-redeploy-readonly.yml) and [its bounded script](../scripts/qa_shared_fixture_redeploy_readonly.py). It requires one *explicitly identified existing synthetic* fixture ID, independently recorded full original SHA-256, and exact full served SHA before and after an observed *different* served code deployment. It downloads only that unchanged original in a disposable Chromium runner, compares full byte hashes/sizes, brackets each download with matching served SHA, blocks off-host traffic and outputs **hash-only receipts**, never source bytes or screenshots. The witness is manual-only: **no before/after production original run, hash comparison or certified Render redeploy retention exists at this checkpoint**. Do not automatically upload any owner DOCX or alter disks, billing, secrets, authenticated route, shared originals or standing reports to satisfy this.

**New main integration gate:** [required 38511539695](https://github.com/evanroden/msapo-generator/actions/runs/38511539695) was **in progress** when checked. The earlier [live dispatch 38511559774](https://github.com/evanroden/msapo-generator/actions/runs/38511559774) was **SKIPPED**, not successful acceptance. After Required completes, obtain exact current-served main live evidence; never infer success from deployment, a skipped dispatch or previous commit. The manual verifier has no user-selected synthetic fixture ID/hash, so the actual disk witness cannot honestly be run without those inputs. The source-patch PR #211, clear-button repair PR #212, synthetic AUTH coverage PR #213, CONT crosswalk PR #206 and the PR #214 verifier are merged; old failures remain preserved at exact SHA.

**Remaining external/owner acceptance:** (1) one chosen immutable synthetic shared fixture's same full SHA/size across two distinct *observed* Render served code builds and completed comparison receipt; (2) genuine AUTH01 older-month same-site, AUTH02 another site under same contract, AUTH03 truly partially completed current-month DOCX with owner-provided independent expected sections and source/target identifiers; (3) physical shipping Safari/iPad/foldable interactions; (4) every native Microsoft Word and Adobe-rendered page for the actual owner layout, diagrams/contacts, pagination, page privacy and prices. Anonymous `?workflow=monthly&monthly_qa=fixtures` is intentionally discoverable and **not confidential**. No user original upload or on-platform data purge has occurred. No phase is declared release-accepted.

**Historical entries below retain their stated commit/time and may describe older drafts as open; the new top checkpoint supersedes them for current status.** Preserve the 113 ORIG, 97 SIM, 6 SRC, 6 original P1 repair/editing, 3 AUTH, 20 ADP-A and 6 ADP-J tracking rows (251 total); these rows are tracking cases, not an assertion that each independently passed authentic acceptance.

## Latest verified integrated checkpoint — October 13, 23:55 ET / October 14, 03:55 UTC

**Main `0dced2428955f657736e7aa74ac555a31dc82a05` has now cleared all three independent synthetic gates after merged PR #212**: [required tests 38504975272](https://github.com/evanroden/msapo-generator/actions/runs/38504975272), [adaptive Chromium/WebKit DOM 38504975128](https://github.com/evanroden/msapo-generator/actions/runs/38504975128) and [serialized exact-served live 38505669642](https://github.com/evanroden/msapo-generator/actions/runs/38505669642) each **completed SUCCESS**, with successful individual pytest, container health, 512 MiB / 0.5-CPU resource and synthetic-live jobs. The live workflow exercises two independent first-attempt synthetic Chromium sessions on the served SHA, source replay and real generated DOCX/PDF, source edits, clear/reentry/refresh and isolation. These results are specific to `0dced24`. Earlier failed WebKit [38503264365](https://github.com/evanroden/msapo-generator/actions/runs/38503264365) remains an accurately recorded failure of earlier `0f5a765`; the content-bound Clear repair is integrated and checked but causal certainty and shipping Safari fidelity are not inferred.

**Documentation-only PR #206 remains open until its CONT crosswalk and historical cases have been reconciled and reviewed.** Latest pre-update branch `0593ba6273bc2ae74efbbe4fac11752d6de8cacd` [required tests 38505029106](https://github.com/evanroden/msapo-generator/actions/runs/38505029106) passed. This new dated checkpoint records the main outcomes before integration; require a fresh passing exact PR-head suite after this edit, then merge the docs with no product logic change. Its postmerge main required test outcome is distinct from the already-accepted `0dced24` live gate.

**Outstanding release acceptance:** one chosen original fixture's SHA-256 verified unchanged across an *observed* actual Render redeploy (not merely its existing attached 1 GB disk); genuine owner-selected **AUTH01–03** for previous-month same-site, same-contract alternate-site and partially edited current-month DOCX; physical Safari/tablet/fold layout verification; per-page Microsoft Word/Adobe with owner-specific charts, contacts, privacy and visual fidelity. The deliberately hidden shared fixture test page has **no login** and is **not confidential**. No owner originals have been uploaded, no Render workspace/storage/billing settings were changed, no standing data was purged and neither phase is declared release-accepted. Preserve all 251 crosswalk tracking entries and old red tests.

## Latest integrated checkpoint — October 13, 23:11 ET / October 14, 03:11 UTC

**Product main `0dced2428955f657736e7aa74ac555a31dc82a05` now includes merged PR #212, the content-bound explicit Activity Clear repair.** Exact PR #212 final head `f0feb91449ba195e420d059a18d4dc2fcac540ef` [required 38504289205](https://github.com/evanroden/msapo-generator/actions/runs/38504289205) **PASSED** all pytest cases, synthetic Word/PDF, production container and 512 MiB/0.5-CPU probe; [adaptive 38504289078](https://github.com/evanroden/msapo-generator/actions/runs/38504289078) **PASSED** first attempt on Chromium and WebKit across all workspaces and the real synthetic Starting report shared-fixture journey. In both engines the explicit report Clear yielded the exact durable journal, survived reload, supported reentry, kept the coworker separate, retained original DOCX SHA and passed zero browser errors/external requests. The previous merged-main [WebKit failure 38503264365](https://github.com/evanroden/msapo-generator/actions/runs/38503264365) remains a recorded **real failure on `0f5a765`**, not retconned by a later branch pass. Hypothesis: content-scoped native Clear button identity avoids stale registered baseline after edit/reentry. Passing this one first-attempt PR run does not establish root cause beyond doubt or physical Safari ergonomics.

**New merged main `0dced24` exact gates now underway:** [required 38504975272](https://github.com/evanroden/msapo-generator/actions/runs/38504975272), [adaptive 38504975128](https://github.com/evanroden/msapo-generator/actions/runs/38504975128) and after successful Required, automatically serialized served-commit live two-session replay. **Do not claim any main pass or deployed acceptance until those runs actually finish.** No auth, credential, paid reader, fixtures, domain, Render disk or user data were modified by this repair; scope was `app/monthly_report_guided.py`, a focused AppTest and passive diagnostics in the existing synthetic browser test.

**Remaining final gates:** (1) passing exact-main Chromium/WebKit plus public served SHA live replay, (2) reconciliation and merge of documentation PR #206 and verification of its new main Required/live checks, (3) authentic owner-selected AUTH01–AUTH03 source originals with independently specified month/site/section expectations, (4) selected shared fixture unchanged byte/hash across an actually observed Render deployment; current observed attached disk alone is insufficient, (5) per-page MS Word/Adobe and shipping Safari/foldable physical acceptance. The hidden shared fixture test route is anonymous and **not confidential**; no owner original was uploaded. Older checkpoints and 251 tracking rows below remain historical, bounded to their tested commits.

## Current integration and unresolved WebKit gate — October 13, 23:04 ET / October 14, 03:04 UTC

**Current product main is `0f5a765840585607890d307d2ad9bba0caee68ae`; PR #211 is merged.** [Exact integrated required 38503264366](https://github.com/evanroden/msapo-generator/actions/runs/38503264366) and [deployed first-attempt synthetic two-session live 38503893547](https://github.com/evanroden/msapo-generator/actions/runs/38503893547) both **passed** on this SHA. However, [merged-main adaptive 38503264365](https://github.com/evanroden/msapo-generator/actions/runs/38503264365) **FAILED**, despite [PR #211 exact-head adaptive 38457114209](https://github.com/evanroden/msapo-generator/actions/runs/38457114209) passing. Chrome completed all native shared-fixture checks; WebKit successfully completed upload/hash, coworker, Starting import, manual Activity edit, Ctrl+Enter clear and reentry with refresh, then one native **Clear Activity for this report** button click did not produce an exact durable journal update within 45 s. The [real failure artifact 11867345023](https://github.com/evanroden/msapo-generator/actions/runs/38503264365/artifacts/11867345023) contains failed-WebKit screenshot, exact outcome and application log. The visible editor/preview still showed the prior reentry text; do **not** reclassify this as an accepted Clear or inferred source failure. Previous synthetic deployed success is valid only for the Chromium gate it executed.

**Isolated repair [draft PR #212](https://github.com/evanroden/msapo-generator/pull/212), branch `completion/content-scoped-activity-clear-20261014`, first head `f0feb91449ba195e420d059a18d4dc2fcac540ef`:** Native Clear button formerly reused one key for different Activity edit baselines; it now binds its keyed browser action to the exact current block fingerprint and report epoch. AppTest asserts key rotates on actual clear/reentry and stays stable after idle rerun. The unchanged first-attempt browser journey captures one trusted pointer/click (passive listener) and a bounded SHA-256 of the last saved journal on failure, without content disclosure, new retries or changing the 45 s journal assertion. [PR required 38504289205](https://github.com/evanroden/msapo-generator/actions/runs/38504289205) and [adaptive 38504289078](https://github.com/evanroden/msapo-generator/actions/runs/38504289078) were **in progress at this checkpoint**, **not accepted**. Review exact-head outcomes before any merge; a new main merge requires new main Required/Adaptive and serialized served SHA live evidence.

**The documentary crosswalk [PR #206](https://github.com/evanroden/msapo-generator/pull/206) remains draft and unmerged:** its last exact docs head `8481cff7caac9f617985d69335a43fcc4f15986c` [required 38503407314](https://github.com/evanroden/msapo-generator/actions/runs/38503407314) **passed**. The original 113 ORIG, 97 SIM, SRC01–06, CONT01–10, AUTH01–03, ADP-A01–20 and ADP-J01–06 tracking rows remain unchanged. Add the actual PR #212 result and final main evidence before merging this docs-only crosswalk; postmerge main required/live are separate. No owner AUTH DOCX files uploaded, real fixture redeploy persistence/byte hash unverified, no shipping physical Safari/Word/Adobe per-page acceptance, and no Render workspace/plan/config changes authorized or performed.

## Latest integrated checkpoint — October 13, 22:51 ET / October 14, 02:51 UTC

**Code main is now `0f5a765840585607890d307d2ad9bba0caee68ae` after merged [PR #211](https://github.com/evanroden/msapo-generator/pull/211).** The source-bound native Activity vendor/date correction is **implemented in main**, not an outstanding uncommitted proposal. Exact PR #211 final head `54e82534a558604bcbd46c22e9963383b451b773` passed all jobs in [required Tests 38457114203](https://github.com/evanroden/msapo-generator/actions/runs/38457114203) (pytest, healthy production container and bounded 512 MiB / 0.5-CPU resource probe), plus [adaptive Chromium/WebKit 38457114209](https://github.com/evanroden/msapo-generator/actions/runs/38457114209). This is **PR-head synthetic acceptance**; main's new [required 38503264366](https://github.com/evanroden/msapo-generator/actions/runs/38503264366), [adaptive 38503264365](https://github.com/evanroden/msapo-generator/actions/runs/38503264365) and its automatic serialized public live run are **pending at this time**. Do not reassign the previous main success to the new head.

**Previously deployed integrated main `2ad4207eace248705878d1c2e736028b5ec6e540` passed** [required 38453445010](https://github.com/evanroden/msapo-generator/actions/runs/38453445010), [adaptive 38453445375](https://github.com/evanroden/msapo-generator/actions/runs/38453445375) and [two-session first-attempt public live 38454455589](https://github.com/evanroden/msapo-generator/actions/runs/38454455589). That success is prior to the new native-source patch. PR #211's initial [38454513486](https://github.com/evanroden/msapo-generator/actions/runs/38454513486) failed one **real** cached reader/native prefix duplication regression, later corrected with source/page-linked dedup and explicit-clear safeguards. Keep the failure and correction history; do not convert the red run to a pass.

**Implemented CONT04/CONT08 bounded scope:** typed price-free Activity cells from uniquely recognized single-site vendor CSVs; evidence-supported ISO event dates and vendor/company identity; dated TXT events; labeled vendor/date DOCX metadata; untouched original bytes and reviewer deletions; unchanged work-order counts and vendor-versus-ENFRA-service-call separation; hidden contact labels and price evidence. Foreign/mixed-site CSVs are withheld from native *and* optional reader Activity until explicit site review. The patch does **not** claim correct independent dates for multiple unstructured DOCX events, locale-ambiguous dates, all vendor schema variants or authentic reports.

**Still open for release acceptance:** confirm exact `0f5a765` main CI/browser and independently served live SHA; prove unchanged hash of a specifically selected shared original across a real Render redeploy; run owner-supplied authentic **AUTH01 previous month same site, AUTH02 same contract other site, AUTH03 real partially edited current month** with independently expected sections and complete Word/PDF/manual correction/review; inspect shipping Safari/device postures and native Microsoft Word/Adobe output page-by-page. The shared test link `?workflow=monthly&monthly_qa=fixtures` is intentionally anonymous/discoverable, not confidential. A mounted 1 GB Render disk is not proof of restorable fixture bytes. Do not modify infrastructure, billing, credentials, standing reports or shared originals to meet the gates. Integrate this docs-only PR #206 after final functional main evidence, then run its own exact-main checks.

**Historical checkpoints below are snapshots at their stated commit/date, not claims about present main.** Original 113 scenario rows, 97 SIM rows, SRC01–06, CONT01–10, ADP-A01–20, ADP-J01–06 and documented failed CI/live executions remain unchanged.

## Current integration/recovery checkpoint — October 13, after 19:43 UTC

**Code main is `2ad4207eace248705878d1c2e736028b5ec6e540`, not fully release-accepted.** [Main required CI 38453445010](https://github.com/evanroden/msapo-generator/actions/runs/38453445010), [adaptive Chromium/WebKit 38453445375](https://github.com/evanroden/msapo-generator/actions/runs/38453445375) and serialized exact-served [live 38454455589](https://github.com/evanroden/msapo-generator/actions/runs/38454455589) **all passed** independently on this exact integrated commit. That live check includes two first-attempt synthetic sessions, 18/18 replay comparisons, accepted Generate, actual Word/PDF signatures and content, Activity clear/re-entry/refresh and stale-tab reset isolation. PR [#210](https://github.com/evanroden/msapo-generator/pull/210) is merged. Preserve all earlier red executions as history, but do not present them as current failures on the accepted synthetic gate.

**CONT04/CONT08 source fix is committed, not yet merged:** PR [#211](https://github.com/evanroden/msapo-generator/pull/211) on `completion/native-activity-vendor-dates-20261013` now retains verified per-event TXT dates, labeled DOCX vendor/date identity and typed vendor CSV work/status/date, with price/contact filtering and manual/mixed-site exclusion. Original full-suite [38454513486](https://github.com/evanroden/msapo-generator/actions/runs/38454513486) failed the existing cached-reader duplication case when dated native wording met an undated cached suggestion. The linked-reader de-duplication was corrected, and amended intermediate head `cea11e52fbed31934e9a5cb432369928d9f61e47` [Tests 38456214139](https://github.com/evanroden/msapo-generator/actions/runs/38456214139) independently **passed 2,444 pytest tests / 2 existing openpyxl warnings, production container and capped resources**. Later header-alias, vendor-contact and additional regression changes advance the head to `54e82534a558604bcbd46c22e9963383b451b773`, whose own required/adaptive checks are **pending at this checkpoint**. The earlier intermediate pass must not be attached to the later head. No owner authentic files have been uploaded, and source corrections after native prefill remain subject to separate manual-review acceptance.

**The CONT01–CONT10 crosswalk below is now indexed in this PR #206 and its original 113 scenario / 97 simplification / SRC01–06 rows are preserved.** Integrate this documentary crosswalk only after final code head and exact-main evidence are known. The app's deliberately shared no-login testing route is not confidential. A previously observed existing Render 1 GB disk at `/test1` proves an attached volume, not a selected fixture's restart/redeploy byte integrity or actual free space. AUTH01–AUTH03 actual owner reports, physical Safari/fold posture and Word/Adobe per-page fidelity remain **not executed**. No credential, account, billing, infrastructure, external message or live-standing-data changes were authorized or performed.

**Next:** finish PR #211 current-head required/adaptive CI; review and integrate if green; verify that merge's exact-main required/adaptive CI, served SHA and serialized live first-attempt sessions; refresh this ledger with exact heads and reports. Independently verify a chosen shared fixture's original hash before/after an actual Render restart/redeploy with explicit scope, then obtain the three owner-labeled authentic originals and target/expected-content metadata. Preserve original and generated user data; rollback by code revert, not reset.

## Prior verified checkpoint — October 13, after 19:15 UTC

**Product code has advanced to merged main `2ad4207eace248705878d1c2e736028b5ec6e540`** through [PR #210](https://github.com/evanroden/msapo-generator/pull/210). This merges the verified native MSAPO page-break correction and a source-specific fix for shared fixture Download/Start controls, atop merged preview-message guard PR #209. **Neither phase is fully accepted:** merged-main integrated CI, public exact-served run on `2ad4207`, authentic DOCX scenarios AUTH01–AUTH03, independent Word/Adobe/hardware and named remaining source/UX issues must be tracked separately. The previous `56dff7` main acceptance below remains valid only for that earlier code.

- **Exact PR #210 head `534dfc8007eefddbaa03476f644c23499ec77141`:** Required [38452482413](https://github.com/evanroden/msapo-generator/actions/runs/38452482413) passed **2,432 pytest cases / two openpyxl test-fixture warnings**, production health, native synthetic Word/PDF and 512 MiB/0.5-CPU resource gates. Chromium/WebKit adaptive [38452482350](https://github.com/evanroden/msapo-generator/actions/runs/38452482350) passed all workflows. Its [synthetic browser artifact 11841372485](https://github.com/evanroden/msapo-generator/actions/runs/38452482350/artifacts/11841372485) contains **52/52 shared-fixture checks** with no external requests or browser errors. Independent ZIP inspection verified both engines' own three DOCX downloads (initial, coworker, after reset) were byte-for-byte identical to **their respective** immutable original hashes, with no cross-fixture substitution.
- **True failure and correction history retained:** PR #210's earlier WebKit branch [38449899865](https://github.com/evanroden/msapo-generator/actions/runs/38449899865) failed on an uncaught canceled-image `EncodingError` after the other synthetic checks; further exact-head [38450968791](https://github.com/evanroden/msapo-generator/actions/runs/38450968791) exposed a **different, real wrong-source download bug**: WebKit selector displayed the WebKit fixture but after reset received Chromium's original bytes, confirmed from artifact 11840950888. The durable originals did not change; a constant download-button key reused the prior resource and the combobox label could update before Streamlit committed the next native action. Fix commits bind both Download and Start keys to full fixture ID + original SHA, reject delayed Start for another selection before a reset/import, and require the actual fixture-specific control to mount before testing one click. A fresh AppTest changes between two immutable DOCX fixtures and verifies widget identity; all prior native byte assertions were retained. The fully amended first-attempt browser + full CI passed above, **not** just a blind rerun of the red head.
- **Native MSAPO output proof:** independent inspection compared actual 5-page synthetic PO PDFs from artifact 11831597215 (old) and 11839968212 (new). Both had the same **55 unique contiguous numbered scope items**. Old pages 3 and 5 began with detached `review.` continuations; updated pages 3 and 5 begin with intact items 18 and 50 and contain no out-of-page text blocks in either Chromium/WebKit output. A separate **60-item real LibreOffice render** and DOCX native paragraph-property test passed in the 2,432-case suite. This is invented content and LibreOffice, **not** owner MSAPO approval in Word/Adobe.
- **Render resource boundary:** read-only Render deployment/service lookup confirmed auto-deploy from main, existing **1 GB persistent disk at `/test1`** and last observed served commit `56dff7ce9e6b61ee8ddb7d20a564f794493a3c4e` before the PR #210 merge. It does **not** independently prove free space, persistence of a chosen shared fixture across a subsequent redeploy, or live service revision `2ad4207`; verify those rather than inferring them from GitHub merge.
- **Owner data and source gap:** no authentic owner reports were uploaded automatically. Anonymous fixture route `?workflow=monthly&monthly_qa=fixtures` remains intentionally shared/discoverable, **not protected**. The owner must identify genuine older same-site, same-contract different-site, and partial current-month DOCX files with source/target labels and independent expectations for AUTH01–03. Native Activity vendor/event-date identity (CONT04/08) remains **uncommitted** after an earlier denied source write; no source fix or local 36-test status is claimed as merged. The original 113 scenarios, 97 SIM, SRC01–06, CONT, ADP-A/J and historical failures remain in indexed rows below.

Next: verify actual main `2ad4207` required + adaptive CI, observe the served SHA/renderer and serialized two-session live first-attempt run, then integrate this indexed documentary crosswalk as the final read-only merge and rerun affected exact-head gates. Owner-authentic, shipping Safari/physical posture and Microsoft Word/Adobe remain open until executed.

## Previous verified continuity checkpoint — October 13, after 18:58 UTC

**Do not declare either phase complete.** The latest confirmed deployed main SHA is `56dff7ce9e6b61ee8ddb7d20a564f794493a3c4e` (PR [#209](https://github.com/evanroden/msapo-generator/pull/209), preview/full-native-edit scheduling). Render's read-only deployment list shows this exact commit **live**, auto-deployed from main; it has an **attached 1 GB persistent disk at `/test1`**. This establishes mount presence and configured size, **not** free capacity or shared-fixture byte integrity across redeploy. Do not change Render plan, credentials, disk or source originals to satisfy a test.

- **Main exact-head CI on `56dff7`:** required [38449779359](https://github.com/evanroden/msapo-generator/actions/runs/38449779359) and Chromium/WebKit adaptive [38449779141](https://github.com/evanroden/msapo-generator/actions/runs/38449779141) both **passed**. Native edit/preview scheduling PR [#209](https://github.com/evanroden/msapo-generator/pull/209) originally passed 2,428 tests/two openpyxl test-fixture warnings, production container, 512 MiB/0.5 CPU cap and every adaptive browser workflow on head `0fd729e1789b41c82fc0beca1f1c1e59b6f8cee7`. Main CI is **not** the same as its separate live check.
- **Public exact-served live `56dff7`:** [38450835167](https://github.com/evanroden/msapo-generator/actions/runs/38450835167) **passed two independent serialized first-attempt Chromium sessions**, both source replay comparisons **18/18**, accepted/completed Generate, current DOCX/PDF text/signature/privacy checks, Activity edit/empty/re-entry, refresh, reset and stale-tab isolation. Artifact **11841305104** is synthetic only. Previous deployed [38447160037](https://github.com/evanroden/msapo-generator/actions/runs/38447160037) passed on `e7c11e9`. Original live rejection [38427749463](https://github.com/evanroden/msapo-generator/actions/runs/38427749463) remains a genuine historical failure.
- **Native MSAPO pagination:** original PR [#205](https://github.com/evanroden/msapo-generator/pull/205) and historical PR [#208](https://github.com/evanroden/msapo-generator/pull/208) are **unmerged** with their exact failed CI retained. Integrating the reviewed two native MSAPO files on `56dff7` produced PR [#210](https://github.com/evanroden/msapo-generator/pull/210), head `0535fe285fad946a5be40e3c9bfcff953e86d577`, required [38449899931](https://github.com/evanroden/msapo-generator/actions/runs/38449899931) **passed**, including the 60-item LibreOffice page-integrity test and resource cap. Its adaptive [38449899865](https://github.com/evanroden/msapo-generator/actions/runs/38449899865) **FAILED** the *last* WebKit shared-fixture `no browser errors` assertion: one unhandled `EncodingError: Loading was canceled.` after exact edit, clear, re-entry, hash, coworker isolation, reset and original-byte checks **passed**. Artifact **11839968212** preserves the outcome. Do not recast a browser error as an acceptable pass. A follow-up diagnostic commit `e662b8b` on PR #210 retains the exact zero-error gate but records bounded engine/action-stage/stack metadata on the next first-attempt CI. A green rerun alone will not prove root cause.
- **Anonymous actual-report test route:** `?workflow=monthly&monthly_qa=fixtures` uses existing shared DOCX storage and per-browser isolated Starting report runs; anyone who discovers the path can list/download chosen fixture originals without login. No genuine owner reports have been uploaded and no **AUTH01–03** actual-source/output scenario has been accepted. Select only owner-labeled originals. Need disk persistence test across an observed actual redeploy with identical SHA of a bounded chosen fixture, without arbitrary deletion or unsupported resource changes.
- **Uncommitted vendor/event identity:** CONT04/08 remains open. Some native Activity extraction omits source-supported vendor and per-event date; earlier source-write request was denied and **no equivalent source patch was committed**. Keep the existing source/correction and business-scope checks, and do not claim the prior local 36-test report is integrated CI. Tested contact grids **0/1/4/40** exist with actual synthetic Word/LibreOffice PDF assertions (e.g., `test_monthly_report_contact_native_scale.py`), but real native MS Word/Adobe inspection is a separate environment.

Next integration: resolve PR #210's **actual** WebKit error with a non-weakened browser gate; require its full exact-head tests; merge/reconcile only when safe. Then perform merged-main required, adaptive and serialized exact-served live checks. Update this ledger with the new SHA, logs, output hashes and any remaining physical/owner caveats. PR [#206](https://github.com/evanroden/msapo-generator/pull/206) adds the CONT crosswalk only; it is documentation and must be refreshed after any further functional merge.

## Continuation requirements — CONT01–CONT10 (current crosswalk)

These are **ten acceptance categories, not ten newly discovered defects**. Historical P1 tickets and the original SIM/SRC scenario rows remain separately indexed. “Implemented” is not equivalent to authentic/deployed acceptance; each row explicitly preserves its unverified slice.

| ID / original ticket | Code and currently verified scope | Still open / qualification |
| --- | --- | --- |
| **CONT01** / P1-R01 | PR [#201](https://github.com/evanroden/msapo-generator/pull/201) merged shared anonymous fixture storage, isolated run copying through the original Starting report importer, Activity incarnation/initial-value guard, site-selection repair. Both engines passed synthetic real-importer CI [38432162098](https://github.com/evanroden/msapo-generator/actions/runs/38432162098), and required tests/container/resource gates passed. PR [#204](https://github.com/evanroden/msapo-generator/pull/204) adds one authoritative explicit report-only Clear action with exact journal tests. | Genuine owner fixtures, Render disk/restart persistence and post-final-merge full main/deployed checks. No-login access is intentional and discoverable, not confidential. |
| **CONT02** / P1-R01 | Old second-replay Generate rejection [38427749463](https://github.com/evanroden/msapo-generator/actions/runs/38427749463) preserved. The repaired `e091679b` [38439079464](https://github.com/evanroden/msapo-generator/actions/runs/38439079464), `a10404b` [38440502927](https://github.com/evanroden/msapo-generator/actions/runs/38440502927), and `61dcbae` [38443488764](https://github.com/evanroden/msapo-generator/actions/runs/38443488764) live runs completed two independent first-attempt sessions, second 18/18 comparison, accepted Generate, actual synthetic DOCX/PDF and reset/isolation. | Repeat the serialized served-SHA gate after later functional merges; causal proof of the original blank editor is limited. Do not replace rejection assertions with button waiting or retries. |
| **CONT03** / P1-U01 | PR [#202](https://github.com/evanroden/msapo-generator/pull/202) merged canonical source date/site form restoration after a fresh session. Its exact head [38438988867](https://github.com/evanroden/msapo-generator/actions/runs/38438988867) passed 2,427 tests and adaptive [38438989014](https://github.com/evanroden/msapo-generator/actions/runs/38438989014) passed; source bytes/hash and one form on rerun are asserted. | Authentic resumed draft, changed bytes under same filename, late readers and all current-source preflight acknowledgments need further evidence. |
| **CONT04** / P1-U04 | Merged PR [#211](https://github.com/evanroden/msapo-generator/pull/211) preserves source-supported vendor/ISO event dates in labeled DOCX, dated TXT and typed single-site vendor CSV Activity; keeps reviewer edits/deletions, native reader dedup, contact/price exclusion and vendor vs ENFRA onsite-call separation. Exact PR-head [required 38457114203](https://github.com/evanroden/msapo-generator/actions/runs/38457114203) and [adaptive 38457114209](https://github.com/evanroden/msapo-generator/actions/runs/38457114209) passed. | New integrated main/deployed verification is separate. Real multievent DOCX, ambiguous date, foreign/mixed-site data, actual owner output and Manual source review remain unaccepted. |
| **CONT05** / P1-U02 | PR [#199](https://github.com/evanroden/msapo-generator/pull/199) introduced direct editable sections and canonical issue/historical-exclude-restore cards, retaining report-only remove versus resolve/standing deletion. PR #204 added explicit report-scoped Activity Clear and Chromium/WebKit isolated journal/reload checks. | Full real-report, repeated upload/deletion and conflict recovery still require owner acceptance. Native WebKit blur-only empty-field failure [38439765439](https://github.com/evanroden/msapo-generator/actions/runs/38439765439) remains historical and was not specifically proved fixed by Ctrl+Enter/button alternatives. |
| **CONT06** / P1-U01 | Canonical date/site form `monthly_report_source_details.py`, period-item historical/exclude/restore and required price/missing-source gates remain in the actual editor. Original CI prevents generic-warning waiver of blocking price/foreign-client issues. | Per-source authentic corrections, unknown/ambiguous site/date and stale acknowledgment recovery need three real scenarios; no filename-based automatic dating. |
| **CONT07** / P1-U03 | Native picture reuse, approved layouts, contact tables and per-section previews implemented, with synthetic native-output and browser evidence at PR #199/main. No replacement of existing approved ENFRA diagrams by invented artwork. | Actual Scorecard/Subcontractor pages; contact page start and intact rows for 0/1/4/40; full-page output geometry and owner images/Word/Adobe review remain open where not individually evidenced. |
| **CONT08** / P1-U04 | Source-first Activity/direct-entry, native TXT/CSV, source restore, failed-source paths, bounded reader calls and distinct ENFRA onsite versus vendor routing exist; synthetic tests retain partial work-order coverage as unknown. Merged PR #211 blocks mixed-site CSV native/reader auto-addition and guards deliberate Activity clears against late cached reader suggestions. | Confirm real multipage/email/images and corrected/deleted facts against the specific owner originals, especially ambiguous vendor/site/date; no paid/external calls or unreviewed foreign-site facts. |
| **CONT09** / P1-U05 | Water review already has one-time automatic inclusion after explicit review, original order, source page captions/exclusion and removed-page guard. Resumed source-date correction is now reachable via PR #202. | Verify owner Water pages, rejected pages and duplicate prevention through rerun/reimport into Word/PDF. |
| **CONT10** / SIM inventory | PR #199 and earlier merged simplification cover ordered sections, shared-version vs recoverable working copy, direct editing, actual current output downloads, PO and Expenses retained workflows; README/index now describe current behavior. | Measure fresh/resumed/mixed-failure visible text, required decisions and clicks. Not all 97 simplification records are automatically closed by a merged PR; retain original rows and record any remaining actual interface gaps. |

Original handoff crosswalk: **P1-R01 → CONT01/CONT02; P1-U01 → CONT03/CONT06; P1-U02 → CONT05; P1-U03 → CONT07; P1-U04 → CONT04/CONT08; P1-U05 → CONT09.** Original P1 and SIM acceptance rows remain authoritative for cases outside the renamed IDs. 

## Current checkpoint — October 13, after 17:42 UTC

**Main is `a10404b41583a34ed32463e4864259ffd395513b`, but release acceptance is not green across all gates.** Main required [Tests 38439765467](https://github.com/evanroden/msapo-generator/actions/runs/38439765467) passed (including container and 512 MiB/0.5 CPU resource gates). The new exact-served main also passed two independent serialized synthetic [live sessions 38440502927](https://github.com/evanroden/msapo-generator/actions/runs/38440502927). These newer outcomes supersede the prior “pending on merged-main” note below **only for those specific gates**.

**Adaptive DOM [38439765439](https://github.com/evanroden/msapo-generator/actions/runs/38439765439) FAILED on merged main** during the shared-fixture WebKit journey, although its PR #202 exact-head run [38438989014](https://github.com/evanroden/msapo-generator/actions/runs/38438989014) passed and the merged-main Chromium workflow passed. After a successfully saved manual edit/refresh, WebKit deliberate emptying through `textarea.fill("")` and Tab did not yield an exact durable journal acknowledgment within 45 seconds. The [failed synthetic artifact 11834467717](https://github.com/evanroden/msapo-generator/actions/runs/38439765439/artifacts/11834467717) captures an empty visible Activity textarea while the generated preview still displayed the earlier manually corrected text. This establishes a **missing durable acknowledgment for that executed interaction**, not a proven root cause. Do not reinterpret a successful live Chromium export, previous passing WebKit branch, or output preview as acceptance of this failed WebKit clearing action. Preserve the existing test assertion; diagnose input/blur/rerun provenance and recoverability instead of retry-until-green.

Independent visual inspection of PR #201's original adaptive artifact [11831597215](https://github.com/evanroden/msapo-generator/actions/runs/38432162098/artifacts/11831597215) was completed for selected synthetic book/tabletop/PO/Expense/shared-fixture screenshots. The Monthly book capture showed decoded native Activity page 2 next to its editor; tabletop's bounded upper area showed only the upper portion of the selected image at 125%, so full-page reading/fit remains a separate usability check. The shared fixture screenshot immediately after import still showed a lazy cover-preview placeholder; it cannot establish all actual preview pages were visually accepted. These are scoped screenshot observations, not real owner-file fidelity.

**Remaining:** diagnose/fix WebKit deliberate clear and rerun exact browser gate on the integrated head; finish uncommitted vendor/event-date native extraction through an allowed, reviewable source path; confirm actual Render disk/redeploy behavior before authentic uploads; obtain owner-selected sources and targets/expectations for AUTH01–03; complete shipping Safari/hardware and Word/Adobe review. The documentation-only checkpoint PR #203 changes no application behavior.

## Historical verified checkpoint — October 13, after 17:34 UTC

**Phase 1 and Phase 2 remain open pending authentic report and physical/rendering acceptance.** This is an evidence checkpoint, not a completeness percentage. Previous dated entries below are historical; preserve their executed successes and failures at the SHA tested.

| Gate | Exact identity | Result and limits |
| --- | --- | --- |
| Existing adaptive/Monthly integration | PR #199 → main `bfbd0b7fb3d5aca7fa810abc5cbc75a7c3ae0de9` | Main Tests [38426633049](https://github.com/evanroden/msapo-generator/actions/runs/38426633049) and adaptive [38426633243](https://github.com/evanroden/msapo-generator/actions/runs/38426633243) passed. Historical live [38427749463](https://github.com/evanroden/msapo-generator/actions/runs/38427749463) failed after the second 18/18 replay compare at an explicitly rejected Generate receipt; earlier passes remain valid only in their tested slices. |
| Shared no-login fixture route + Activity/site-selection repair | PR [#201](https://github.com/evanroden/msapo-generator/pull/201) head `3e0ea7f7a9d99acafde4f9f5b2058f39e5deffdb`, merged as `e091679b362b686db8aec06821b41269f1b4f2aa` | Exact PR Tests [38432161703](https://github.com/evanroden/msapo-generator/actions/runs/38432161703) **2,426 passed / 2 warnings**, container and 512 MiB/0.5 CPU passed. Adaptive/browser [38432162098](https://github.com/evanroden/msapo-generator/actions/runs/38432162098) passed Chromium and Playwright WebKit including actual Starting-report synthetic shared-fixture importer. Merged main Tests [38438187814](https://github.com/evanroden/msapo-generator/actions/runs/38438187814) and adaptive [38438187789](https://github.com/evanroden/msapo-generator/actions/runs/38438187789) passed. |
| **Live replay/export regression cleared for tested build** | Public exact-served main `e091679b362b686db8aec06821b41269f1b4f2aa`; [serialized live workflow 38439079464](https://github.com/evanroden/msapo-generator/actions/runs/38439079464), artifact [11834471293](https://github.com/evanroden/msapo-generator/actions/runs/38439079464/artifacts/11834471293) | **Passed on first attempt** in two independent sessions; second replay comparison **18/18**, Generate action **accepted and completed**, native Word/PDF content/privacy assertions, Activity edit/clear/re-entry/refresh, reset and cross-tab stale action. This corrects the last observed gate outcome on its deployed SHA; it does not prove the previously suspected blank-value causal path, owner actual-report fidelity or every future run. |
| Saved source date/site correction controls | PR [#202](https://github.com/evanroden/msapo-generator/pull/202) head `9fe172ff64f36bf7b563cb324276020701b006de`, merged as `a10404b41583a34ed32463e4864259ffd395513b` | Exact PR Tests [38438988867](https://github.com/evanroden/msapo-generator/actions/runs/38438988867) **2,427 passed / 2 warnings**, container/resources passed; adaptive [38438989014](https://github.com/evanroden/msapo-generator/actions/runs/38438989014) passed. Added fresh-session real `run_web.py` AppTest: saved TXT original can correct canonical date/site, preserves original bytes/hash, remains one form on rerun. **Its merged-main deployed/browser result is separate and pending at this checkpoint.** |
| Vendor/event date extraction | **Uncommitted; not merged** | Current native Activity extraction can omit vendor/event header identity on certain files. A proposed connected source write was denied; do not claim a fix or bypass that denied route. Existing date/site metadata extraction is not evidence this Activity prose behavior is fixed. |
| Actual owner fixtures AUTH01–AUTH03 | Owner-selected immutable DOCX originals not provided | Synthetic upload/hash, shared-fixture visibility, normal importer, isolated run reset passed browser CI on PR #201. Actual same-site previous-month, different-site same-contract and confirmed half-finished current-month source/output cases are **not executed**. Anonymous route `?workflow=monthly&monthly_qa=fixtures` is hidden but publicly discoverable; anyone finding it can list/download uploaded fixtures. No login was requested or added. Storage restart/redeploy retention is **not** independently verified by an `EPC_DATA_DIR` setting or GitHub test. |
| Physical/renderer acceptance | Not executed | Chromium, Playwright WebKit, synthetic DOCX/PDF and injected CSS geometry do not establish shipping Safari, physical folding, Microsoft Word/Adobe pagination, owner reports or actual-device performance. Keep the individual ADP-A/J, CONT and original SIM/SRC ledger rows open where they lack that evidence. |

**Next isolated gates:** confirm merged-main `a10404b` required/adaptive CI, served SHA and serialized synthetic live results; verify the shared fixture route and restart persistence with a selected Render workspace before inviting authentic uploads; finish and test the vendor/event-date extraction without bypassing denied operations; then obtain owner-labelled DOCX files, target contract/sites/month and independently supplied expected results for AUTH01–AUTH03. Preserve the full 113 Phase 1 scenarios, 97 SIM records, SRC01–06, CONT01–10 and ADP-A01–20/ADP-J01–06 evidence crosswalk below. Revert code on rollback; do not purge standing data, fixtures, or report history.

## Historical checkpoint — 16:35 UTC, October 13

- [PR #201](https://github.com/evanroden/msapo-generator/pull/201) is draft, head **`677156ce5f3337f41ca5bfefd312d5f9db9ea8cf`**, tree **`01fab9b2c64c69bf52fdd9063b0a6d767aca3b2c`**, matching local `5859e91`. Main/public remain `bfbd0b7`; the shared route is not deployed. Required **Tests38430759059 passed: 2,426 tests / 2 warnings / 387.04 s**, production container and 512 MiB/0.5 CPU resource jobs passed. No authentic files have been uploaded.
- **DOM38430759088 failed only in the new shared-fixture harness.** Both engines saved/listed their fixture, then a page-text selector could not find the selected name because locked Streamlit renders it as the combobox input value. WebKit's failure screenshot shows the exact saved fixture, AUTH03 metadata and download/start actions. The repair will assert that native value plus the saved manifest/hash, retaining all subsequent importer/download/refresh/reset checks. Those later steps were not reached and are not passes. Artifact **11830767439**, SHA256 **`68693c954710c018c13faf7ff41f28baf4329878ff05418783a6d5998c5819dc`**, preserves this first outcome.
- **SITE02: the actual Monthly browser journey passed in Chromium and Playwright WebKit.** A single native mouse click deselected Demo South, the server displayed only Demo North and removed the combined report editor; Space restored both sites and the exact existing Activity draft. Trusted pointer/key events and geometry are in `monthly-adaptive/results.json`; both `*-site-selection-pointer-keyboard.png` screenshots were retained. All **76 Monthly assertions** passed, including actual generated previews, sticky/reverse boundaries, book/tabletop transitions and unblurred input. Shared geometry, Expense and Purchase-order journeys also passed separately. These results narrow the public Cloud Browser pointer observation to that interaction path; they do not establish shipping Safari/touch or every site configuration.
- **SITE03: PO/Expense focused state review** at local `5859e91`: 104 existing tests passed in 4.77 s with temporary data and zero network attempts. Separate AppTest probes exercised PO UMMC → Clifton Springs → Tulane → RRH → unresolved, and Expense account changes invalidating foreign jobs while retaining a valid selected job on rerun. No generation/submission/share occurred. These overlap full CI and are not an added total or pointer proof. PO uses one site; Expense uses account and per-line jobs.
- Independent next-batch work is uncommitted and excluded from this CI head: restored-source date/site controls currently disappear because they depend on session upload markers; native vendor extraction loses date/vendor headers and emits separate paragraphs. Fixes must retain canonical source ownership, manual wording, explicit page review and date/site safety. PR #201's Activity protocol repair still requires deployed serialized live evidence; LIVE06 is not cleared by these branch passes.

## Previous checkpoint — after 16:23 UTC, October 13

- Subsequent publication checkpoint: Activity/site-state code is now remote **`156c5e6fc291cc0eb7502007e061a05192e647df`**, tree **`fe0425702daafbfae9c92330faac66eb8a0751e6`**, exactly matching local `c6be309`. The following branch snapshot describes its immediately preceding publication. Browser pointer coverage and these notes are the next commit; no current-head CI/live pass is implied.
- Shared fixture work is **published on the branch**, not deployed: remote `completion/shared-fixture-testing-20261013` head **`7442d4314b00d844d054bc86f71c18eb8b6e726d`**, tree **`c67ab625698e074a383657e7043ffe9d80ebb6e6`**, matches local `3f42ebc` by tree. There is **no PR, required CI or deployed shared route yet**. Shared storage/UI/same-importer local162-test evidence remains bounded; no authentic files have been uploaded. The owner-authorized anonymous access policy is unchanged and no authentication decision is pending.
- The Activity protocol repair and three new site-state AppTests are **committed locally as `c6be309`**, pending publication/current-head gates: canonical initial widget value, report-incarnation scope included in the widget ID, and a missing callback value no longer interpreted as deliberate clearing. **41 focused tests passed**; the final **35-test subset passed** and overlaps those41. `private_route_review` found no blockers: canonical defaults do not alter identity, the editor incarnation stays stable, deliberate empty remains valid, a missing value is not clearing, and interrupted receipts are preserved. The exact origin of LIVE06’s blank canonical Activity remains unknown; these protocol tests are not an established live root cause or a passing production repair. Generation/fingerprint rejection remains intact. The next checkpoint must name its published head and exact CI/browser/live evidence.
- The owner raised site-selection behavior. Existing **21 AppTests** and **3 new production `run_web` AppTests** passed single/combined selection, uncheck-all, custom sites, separate saved drafts and workflow round-trip cases. These are separate scopes; no total is claimed. In public **`bfbd0b7` isolated synthetic QA**, keyboard Space changed Demo South to false and settled at **Sites selected:1 — Demo North**. Accessibility-tree text/label/coordinate click and check actions caused no change; the input was enabled, no overlay was found and focus remained on the summary. This is a bounded observation, **not a proven application pointer defect**. The actual Monthly Playwright journey is being strengthened to click Demo South off and use keyboard to turn it on in both engines; that browser gate and current exact-head CI are pending.
- Merged/deployed adaptive evidence remains C199-RELEASE, INT05 and ENV03 on `bfbd0b7`. The latest executed live result remains **LIVE06 failed after the second replay Compare18/18 passed**, with Generate rejecting a changed fingerprint and working/durable Activity empty. Both preceding fresh reliability sequences and first replay/export/reset passed. Neither the new site AppTests nor the locally committed protocol repair clears that failure.

## Previous checkpoint — 16:08 UTC and subsequent local verification, October 13

- **PR #199 merged at 15:58 UTC** as `bfbd0b7fb3d5aca7fa810abc5cbc75a7c3ae0de9`. Reviewed head `fb095dda`, base `0741865`, reviewed tree `9cdbb455`. Required CI **38425247637 passed: 2,336 tests / 2 warnings / 309.47 s**, production container and **512 MiB / 0.5 CPU** resource gates. Adaptive DOM **38425247659 passed both Chromium and Playwright WebKit**. Shared **46**, Expense **86**, PO **32** and Monthly **72** are separate harness scopes, not a summed coverage total. See C199-RELEASE and DOM10.
- Artifact **11827834127**, SHA-256 `99f19ed144040d86e1195eaf31f19145860133093bef7d51872483d1451cda28`, was reviewed before merge. Actual Monthly selected page 2 decoded in book (**816×1056**) and tabletop (**1020×1320**) while retaining unblurred input/focus. This closes the specific earlier transient blank-image observation using bounded selected-image retention and stronger assertions. Actual synthetic Monthly five-page output, original PO quote/generated MSAPO, and Expense **$49.00 editable workbook / five-page PDF** were checked. Expense returned from receipt inspection to packet page 2 / 125% with identity and reading offset retained. This is bounded synthetic browser/output evidence, not authentic, shipping Safari, physical-device or full ADP acceptance.
- On merged main, **DOM38426633243 passed**; required **Tests38426633049 passed:2,336 tests / 2 warnings / 389.39s**, with container/resource jobs passed. Main DOM artifact **11829061866**, SHA256 `c8429999e473f452332bc50e56bb35794951eb295c305074fe67751667679b91`, is recorded; its screenshots have not been independently re-reviewed after the reviewed branch artifact. Serialized live **38427749463 failed at 16:08:12 UTC** on this main; see LIVE06. Both Activity reliability sequences passed, and the second source replay Compare now passed18/18. The subsequent Generate was explicitly rejected after the canonical fingerprint changed and both working/durable Activity became empty. This newly observed clearing is under diagnosis, not a timeout or recurrence of the original hydration symptom. The public Purchase-order footer was observed read-only at **16:04 UTC** serving **`bfbd0b7fb3d5aca7fa810abc5cbc75a7c3ae0de9`**; no report was opened/generated. Deployment is observed independently of the merge. Design pin was not reverified. The former second-replay Compare failure in38339777959 remains historical; the latest LIVE06 passed that comparison and failed later at generation with unexpected canonical Activity clearing. No broad reliability acceptance is inferred from the earlier bounded passes, DOM or deployment.
- **Current fixture policy:** at **15:36 UTC**, Evan explicitly declined authentication and requested a hidden **shared, anonymous** fixture area for coworkers/agents. Anyone discovering its route may list, upload, read, replay and download shared fixtures. Owner-only authorization and anonymous-access rejection are **superseded requirements**, not passes. No authentication approval is pending. Immutable originals, explicit source/target/scenario/partial-file labels, independent expected content, isolated disposable runs, reset leases, no external readers/live-data fallback and exclusion from public Git/build/static assets/CI/logs remain required.
- The new branch **`completion/shared-fixture-testing-20261013`** contains **implemented and committed locally as `22c8344`** shared storage/UI/production-importer wiring. The intended navigation is `?monthly_qa=fixtures`; it is not yet a deployed feature or an invitation to upload actual files. Root’s current nine-file shared storage/run/admission/UI/route/URL/QA-isolation/Starting-import selection **162 passed / 19.48s**; agent’s earlier shared selection **107 passed / 10.85s**, shared UI/core **90 passed / 6.69s**, and route/URL **13 passed / 6.40s** overlap and are not added. The new URL test initially failed because AppTest does not execute browser cookie bootstrap; that corrected harness outcome is not a production defect. Earlier45/56-test scopes also overlap. Actual import/edit/refresh integration is implemented; fresh required CI and the browser harness remain pending. Review found the three raised blockers resolved, with no remaining blocker in that bounded review. The cumulative initial-copy admission guard is integrated with **128 MiB reservations / 256 MiB free headroom**; it does not bound all generated run data or authorize deletion. No authentic files have been uploaded.
- LIVE06 diagnosis hypothesis: the current Activity text area omits an explicit canonical initial value, while `on_change` can receive an empty frontend initialization and treat it as an intentional edit. The report/reset epoch scopes the callback but not the widget ID, possibly permitting stale frontend state after reset/reimport. A canonical-initial-value plus incarnation-scoped widget-ID repair and protocol regression are being implemented; reproduction/current tests and live repair are **not yet established**. The generation/fingerprint rejection remains required and is not being weakened.


Historical checkpoints below retain their original observations. Any pre-15:36 owner-authentication proposal is superseded by the explicit shared-access decision above; an old blocked/private status is historical, not a current request for credentials or approval.

## Previous checkpoint — 15:46 UTC, October 13

- Main/public remain `0741865`. PR #199 head **2af357b462717dd0465b29bbcebb614077b06903** passed required CI **38422533174**: **2,336 passed / 2 warnings / 384.65 s**, container and 512 MiB/0.5-CPU jobs, checkout **d45270435dcd3cf6de5c09793ef6b5d59754e377** into `0741865`. Resource sample peak343552000 bytes, OOM/kill deltas0. Adaptive browser **38422533195 passed**, job115383356880, artifact**11827271774**. Shared46, Expense86, PO32 and Monthly68 assertions are separate harness counts, not summed distinct requirements. All four manifests have no failed assertions.
- Reviewed bounded passes: both engines now show the shared next pane; Expense rapid split/signature edits reach the canonical draft before actual49.00 workbook/five-page PDF generation; receipt inspection returns packet page2/125%/identity/offset and corrections withhold obsolete output. PO exact return preserves page2/125%/identity/offset without full reruns. Monthly18/18, realfive-page output, sticky/reverse, fragment-only navigation and unblurred transitions passed. Synthetic LibreOffice24.2.7.2 Expense/PO pages were inspected; no clipping/collisions observed, with single-word PO continuations retained as a pagination-quality limitation. No authentic/Word/Adobe/Safari/hardware acceptance is implied.
- **Artifact review held the merge despite green CI:** both Monthly book captures had page2 selected but only a placeholder. The harness captured immediately after geometry acknowledgment; it did not await the selected raster. Tabletop subsequently decoded page2, so this is proven transient absence, not a persistent-stall conclusion. An outgoing compact hidden response supplied no images and the client removed its prior decoded page. Current repair retains only the selected same-generation/layout image while observer-visible and fewer than two images are supplied; hidden/new-generation surfaces still release it and total imagery stays at most two. Native book/tabletop checks now require the selected page to decode before screenshot, while preserving the unblurred focus/node assertion. **8 Node lifecycle tests passed**; read-only review found no blocker; new exact-head CI/browser proof is required before merge.
- **Owner scope change at15:36UTC:** Evan explicitly declined authentication and requested a hidden shared testing area for coworkers and other agents. Fixture list/upload/read/replay/download will intentionally be accessible without login to anyone discovering the route. The original owner-only/unauthorized-access-denial requirements are superseded for this route, not secretly counted as passes. Original bytes stay out of Git/build/static assets/CI/logs; immutable originals, explicit source/target/partial-file expectations, per-run isolation, reset leases and no live-data fallback remain required. Shared storage facade is implemented separately (17 shared tests plus unchanged40 protected-vault tests passed); UI/importer wiring is the next increment. No credentials, private Render operations or hosting changes are needed for this scope.

## Previous checkpoint — 15:28 UTC, October 13

- Main/public remain `0741865`. PR #199 **`e67c85852149bfcce6bbdb4f01e9f31eca83a5f4`** passed required CI **38417323125**: **2,295 passed / 2 warnings / 367.14 s**, container/resource; checkout `ced26d1` into `0741865`. Browser **38417323298 failed**, artifact **11824459260**. Monthly again completed both engines with the stronger real-output/fragment/unblurred checks. Shared Chromium's next pane and Expense Chromium's packet return still lacked imagery. Both Expense engines got past the previously failing second receipt. Chromium generated/downloaded the actual $49.00 workbook/five-page packet before the return failure; WebKit's packet setup retained $37.75 and a missing second split amount/signature warning. This is interrupted editing evidence, not a financial-calculation conclusion.
- Wire evidence shows overlapping outgoing/incoming preview fragment requests and an interrupted packet fragment, followed by no returned packet rerender. The previous acknowledgment-only-on-rerender fix was insufficient when no rerender arrived. Current code retries only the **idempotent bounded view request** twice at two-second intervals, then offers **Retry preview request**; it never repeats edits, report generation, saves or external actions. Cleanup/background checks remain; matching server acknowledgment stops all retries. The unchanged first-attempt browser assertions still need to pass.
- Independent review reproduced a retry-cap gap: stale component invocations could bypass a timer-only limit (three sends became five). The final guard enforces the three-attempt budget at transmission, retains the recovery control through rerenders and clears the old error only on explicit Retry, a new request signature or matching acknowledgment. A lifecycle regression repeats five stale invocations after exhaustion and proves no new request/timer; new DPI requests receive a fresh budget. Final reviewer found no remaining blocker in this diff. Current Node **7 passed**; `pytest -q tests/test_reference_preview.py tests/test_monthly_report_preview_store.py tests/test_expense_packet_fixture.py` **32 passed / 1 renderer-marker skip / 4.77 s**. An earlier command named nonexistent test modules and collected no tests; it is not a pass. These focused scopes overlap earlier checks.
- Pinned Streamlit 1.61.1 source and an executed direct `ScriptRequests` probe show a queued full rerun followed by a fragment request can become a fragment-only queue. To protect editing, shared viewer viewport requests and pending polls now defer while the actual app root's `data-test-script-state` is busy and resume on its idle acknowledgment. No input is cloned/read/stored and no framework package/configuration is patched. Node regression covers a queued full edit, running state, idle release and already-scheduled poll. Current local **7 lifecycle tests passed**; focused Python **53 passed / 2 renderer-marker skips / 14.57 s**. Browser verification is pending.
- PO's current failure is its old synthetic receipt reading temporary widget state after explicit comparison return. The application retains the canonical applied view and page image; the fixture now acknowledges that applied view, while keeping exact returned page/zoom/offset and decoded-image assertions. Expense uses the same stronger canonical receipt. Neither failure was waived or converted into a pass on the old head.
- Disconnected vault primitive **87b9b4a** is implemented with **40 passing synthetic tests**; root's combined vault/docs selection **98 passed / 0.30 s** includes those 40 and must not be added to them. Every list/read/upload/download/replay-copy operation requires the injected current server owner verifier; no configured verifier or UI caller exists. Immutable DOCX bytes/hash and owner-confirmed manifests use atomic/fsynced owner-scoped storage. Descriptor traversal rejects symlink swaps; explicit pending-upload recovery keeps committed fixtures readable and counts retained bytes without purge. Fresh run copies are separate. This does **not** implement authenticated Render upload/preview/download, production-importer replay, reset leases or verified redeploy retention; AUTH01–03 remain blocked.
- Root owns the next integration/publication. Both remaining workers were interrupted after the preview review; root completed the narrow Expense receipt. It acknowledges the canonical draft after the entire rapid split/signature batch without serializing individual edits, and failure diagnostics retain only expected-value booleans/full-run number. Focused Expense fixture **2 passed / 1 renderer-marker skip / 3.68 s**, including pending-versus-completed draft and later-correction rejection without generation. Existing exact workbook/PDF assertions remain. Documentation index **58 passed / 0.12 s**. These scopes overlap earlier checks.
- The owner is available again. The next access question is approval for fixture-only owner authentication and protected transport on the existing Render service; no security change has been authorized yet. Pinned Streamlit1.61.1 exposes `st.App` custom routes/middleware (also verified against official1.61 documentation), so the transport can use the existing service rather than a framework monkeypatch/new host. Authentication implementation/enablement and authentic files remain pending. Keep PR #199 draft until exact integrated required CI and reviewed browser gates pass; do not accept an old green head.

## Previous checkpoint — 14:52 UTC, October 13

- Main/public remain `0741865`; PR #199 exact head **`29b650f8b076ef3a22b52dcdc7d6ea97b907679f`** passed required CI **38415731849**: **2,289 passed / 2 warnings / 376.22 s**, production container and capped-resource jobs; checkout `526c351` into `0741865`. Browser **38415731769 failed**, artifact **11823802939**. **Shared layout, actual Monthly and actual PO completed both Chromium and Playwright WebKit.** Expense WebKit completed its receipt/mileage journey; Chromium still failed loading the newly active second receipt. Keep the failure and do not merge yet.
- The earlier Monthly WebKit wire-cache error did not recur. It remains unresolved historical failure evidence, not a claimed cache fix. New wire traces contain 202 Chromium / 214 WebKit metadata events, no raw payloads; no cache/runtime configuration changed. Read-only diagnosis reproduced a possible age/advertisement/reference race using installed Streamlit's cache class, but that synthetic ordering is not proof of the original event.
- Current preview repair adds **server-applied viewport acknowledgment**. The old browser `sent` flag treated dispatch as success, so an interrupted callback could leave an active pane permanently believing its request was applied. Each rerender now reconciles the actual canonical view; unacknowledged requests carry a distinct bounded request ID so Streamlit can deliver them even if the old state value was stored. A Node regression reproduces missed delivery and proves no repeat after acknowledgment; a Python regression distinguishes widget value from applied source-view state. This is a proven missing-handshake repair; whether it clears the observed Expense failure still requires the next browser run.
- Local current preview checks: **54 passed / 1 renderer-marker skip / 10.93 s**; later reference/Expense isolation selection **11 passed / 1 renderer-marker skip / 5.09 s**; Node lifecycle **6 passed**. Do not add overlapping counts. Removed the redundant Monthly Preview caption while preserving the viewer's current/updating/stale state and semantic section title; this recovers upper page space without hiding errors.
- Expense implementation/test commit **0479952** now invokes the genuine production workbook/Calc/PDF builder in marked disposable storage. Local direct renderer assertions passed: signed form plus four receipt pages, three split reimbursement lines across two sources, $49.00, editable formulas, original hashes unchanged, obsolete packet withheld after correction. Browser journey adds actual downloads, packet page/zoom and deliberate receipt inspection/exact return; it is **pending CI**, not an executed browser pass. Adaptive CI now installs Calc (already present in the production container). No financial calculations or share/submit behavior changed.
- Root owns integration/shared preview. The Expense agent has committed and finished; `cache_review` now owns only new disconnected private-vault primitives/tests. These remain fail-closed without an injected approved server-side authorizer and will have **no UI/authentication configuration or live storage use**. A usable authenticated Render fixture route remains blocked on the actual approval/access boundary and is not satisfied by an unconnected primitive. Authentic files, Safari/hardware and owner acceptance remain separately open.

## Previous checkpoint — 14:40 UTC, October 13

- Main/public remain `0741865`. PR #199 head **`6f0c9023870fbabc268e238372d4c1dd83012d49`** passed required CI **38413189571**: **2,287 passed / 2 warnings / 383.44 s**, container and resource gates; merge checkout `cef1b91` into `0741865`. Browser **38413189905 failed**, artifact **11822708860**. No merge or new production-heavy test was launched.
- **Actual Monthly Chromium completed the strengthened journey:** independent known-value 18/18, real five-page Activity, sticky release/reverse with page 2 decoded, unblurred value/focus/selection through measured book/tabletop, title clear of chrome, compact return. Preview navigation held full runs **7→7** while fragment runs increased **10→13**; explicit later input commit legitimately caused run 8. This verifies the namespace-only fragment repair in this bounded browser/input. It does not accept authentic gray-freeze behavior or all monthly scenarios.
- **Actual PO completed both engines again.** Expense Chromium completed; WebKit's newly active second receipt still had no image. Shared Chromium likewise failed loading the newly active Scorecards preview. The viewer previously bound its workspace/pair before adapter classes necessarily existed. Current repair binds the already rendered app-owned container keys, so later active changes cannot be missed. A regression deliberately omits adapter classes on first mount; actual browser proof remains pending.
- Monthly WebKit's second checkbox was disabled because an actual Streamlit connection dialog reported **Cached ForwardMsg MISS** (`b77567ac55ca857032341b56b47f9c99`). This is not a selector timeout to waive. The next isolated harness records bounded wire-cache metadata (message kind/hash/size, rerun/fragment and finish ordering), never payload/widget/report content. No cache settings or framework version were changed. The shared harness now records failure geometry/screenshots and executes each engine independently; a Chromium failure cannot hide WebKit's outcome.
- Local checks for this increment: wire/observer privacy/runtime **5 passed / 5.37 s**; preview lifecycle **5 passed**; both edited browser scripts compile. These scopes overlap existing coverage and are not added to CI counts. Root owns integration/shared preview edits. `cache_review` is read-only investigation; `expense_packet_acceptance` owns only the isolated Expense fixture/browser journey and its tests. No concurrent remote writes.
- Owner authentication/access approval, three authentic fixtures/expectations, native Safari/hardware and final owner acceptance remain blocked separately. No authentic bytes, credential changes, service settings, submissions, email or sharing were used. Keep PR #199 draft until the exact current required/browser gates pass and actual artifacts are reviewed.

## Previous checkpoint — 14:24 UTC, October 13

- Main/public remain `0741865`. PR #199 head `98ce0cc471a9549d41b6f8bab5fd55e818c9a9bd` passed required CI **38411498834** (container/resource and full suite). Browser **38411498858 failed**, artifact **11822766667**. **Actual PO completed in both Chromium and Playwright WebKit** with real five-page output and source/output return. Expense Chromium passed; Expense WebKit passed the strengthened title/inactive-pane assertions but its newly active second receipt remained an unloaded placeholder. Monthly WebKit completed this harness; Chromium timed out waiting for the initial 18/18 Compare acknowledgment. These are bounded outcomes, not final journey acceptance.
- Runtime instrumentation on the earlier actual Monthly run showed **zero fragment reruns** and full runs rising **12→17** during page/boundary navigation with unchanged content hashes. Locked Streamlit 1.61.1 source inspection and an actual widget-metadata regression found the cause: restoring the entire copied context inside the QA fragment erased Streamlit's current fragment/render identity. The repair captures **only the QA namespace and reset lease**, keeps framework context current, and binds viewport/poll/retry callbacks before any cache access. Real widget metadata now proves distinct section fragment IDs; a stale callback after reset cannot mutate state or recreate its erased namespace. Worker-thread context remains preserved.
- The existing synthetic diagnostic captions also added hundreds of pixels to preview boundaries. They now use hidden inert DOM metadata, with the same allowlisted counters/hashes and tests; no report/input text is captured. Browser acceptance now requires actual selected-page decoding and **unchanged full-app count with increasing fragment count** during navigation/section scrolling.
- WebKit tabletop's fixed upper surface may be clipped by IntersectionObserver to the lower ancestor. Active tabletop visibility now additionally uses the actual positive viewport-intersecting reference rectangle; inactive/hidden/background references remain blocked. A Node regression exercises clipped observer state, active receipt change and background suspension. The workspace measures the persistent Streamlit header before computing usable segment bounds; title hit-testing verifies it is not hidden by chrome.
- Latest focused Python selection: **50 passed / 1 renderer-marker skip / 14.68 s**. Separate updated observer selection: **3 passed / 2.72 s**. Node: **22 passed** (17 geometry + 5 lifecycle). Counts overlap and are not added. These latest edits need their own exact-head CI/browser run. No live rerun or new private access was performed.

## Previous checkpoint — 14:13 UTC, October 13


- Main/public remain `0741865`; exact-main CI and failed live evidence below remain current. No new production-heavy replay has been launched while local/CI browser defects are being resolved.
- PR #199 published `dba839c1296a81e12ebbfe93e8187273dfcc4325` passed required CI **38409751242**: **2,284 passed / 2 warnings / 396.98 s**, container and 512 MiB / 0.5 CPU gates. Checkout `7107816` merged that exact head into main `0741865`.
- Browser **38409750243 failed**, synthetic artifact **11820348334**. Shared fixture and Expense assertions passed both engines. **Chromium PO completed** actual five-page MSAPO generation, original-quote comparison/exact output page+zoom+offset return, no full-app reruns for preview navigation, book/tabletop/compact and unblurred typing. WebKit PO failed at initial workspace mount; screenshot shows first-party module import failure. Its harness previously rejected every non-http URL; browser-local blob/data modules are now allowed while external network remains denied, with rejected requests recorded. This is a harness hypothesis pending the next executed run, not a proven application fix.
- Actual Monthly both engines passed known-value 18/18, real five-page Activity imagery, unique app IDs, measured sticky top, section-boundary release and ordered next-section arrival. WebKit then lost page 2 on reverse scroll; Chromium retained page 2 but the later injected book geometry correctly became compact because the open sidebar left only ~264 CSS pixels in the first segment. The harness now explicitly checks that fallback, then supplies usable asymmetric segments. It also requires the selected returned page to decode, and records full exception locations.
- Visual review found a defect missed by Expense's passing assertions: an inactive Mileage caption overlapped the active receipt reference in tabletop. Inactive reference surfaces now use `display:none` (the authoritative editors stay mounted); app-owned title/return controls restore independently after fragment replacement, with changed-value guards. Actual Expense checks now require the correct visible title inside the upper region and no inactive reference descendant boxes.
- Preview reading anchors now survive zero-size/hidden surfaces and temporary unknown pagination; only real changed pagination clamps to a surviving page. Local regression reproduces hidden remount/cache reload and subsequent resize. **21 Node checks passed** (17 geometry + 4 lifecycle); focused workspace/preview-store/copy/reference Python selection **34 passed / 4.81 s** (overlaps Node via wrapper, do not add totals). Browser verification of these latest fixes remains pending.
- Root owns all remaining integration after the usage-limit worker interruption. Keep PR #199 draft until exact-head required and actual-workflow browser gates pass and artifacts are reviewed. AUTH01–AUTH03, new owner authentication/access approval, authentic files, shipping Safari and physical-device acceptance remain open; no authentic bytes or external submission/share actions were used.

## Previous checkpoint — 13:59 UTC, October 13


- **Main and freshly observed public footer are `0741865eca3b3dbc2bf7d2818b700d33f8790986`.** Exact-main CI **38339222180 passed**. Serialized live **38339777959 failed**; preserve artifact **11785679075**. Both fresh sessions passed Activity hydration, durable edit/refresh, deliberate clear/refresh, re-entry/refresh, and exact re-entered wording in real Word/PDF. The first session also completed replay 18/18 and its exports/reset. The second replay committed, then **Compare fixture facts produced no completion acknowledgment within 25 seconds**; generation was not reached for that replay. Its working report/Activity hashes match the intended replay. This is neither a new empty-editor failure nor an export timeout in this run. The root cause remains under investigation; no retry has been substituted for failure.
- PR #199 head **9a60b6d** passed required CI **38339019340**: **2,262 passed / 2 warnings**, production container and capped-resource gates; checkout merge ref `3e7b0fc` into `6937f3f`. Browser CI **38339019339 failed**, artifact **11786106507**: shared viewer and actual Expense passed both engines. PO reached real MSAPO generation, then its test awaited removed private `state.timer`; Monthly's two engines stopped at a clipped React Aria checkbox input. Root fixes require a real PO fragment/page acknowledgment and normal visible-label clicks; assertions remain. Updated actual PO/Monthly acceptance is pending.
- Usage-limit interruption stopped the worker sessions. Root recovered their changes into commits: guided dated-item integration **565fe4e**, workflow-return probe **7a49e36/743a1ec**, monthly pointer harness **ab56bc3**, PO acknowledgment harness **06c2757**. The guided tests include exact exclusion/restoration/historical text, interrupted decisions, durable recovery and absence of excluded price/receipt bytes from all DOCX package parts. The isolated three-workflow return test passed after correcting its own query-value/PDF/cache fixture setup; it proves committed values, uploads, split lines and server preview identity/requests, not JavaScript page/zoom/caret or physical hardware.
- Recovered integration focused checks: `test_monthly_report_guided_period_items.py`, `test_workflow_return_preservation.py`, `test_monthly_report_period_items.py`, `test_workspace_browser_observations.py`, and `test_docs_index.py`: **80 passed in 10.98 seconds**. Node preview lifecycle: **3 passed**. These are bounded local checks with the already documented local NumPy 2.3.5 exception; production locks remain unchanged.
- Root is publishing these reviewed increments with the prior local helpers/observations and current-main ancestry. New-head CI/browser acceptance remains required; **do not merge PR #199 on its older green full suite while its browser gate is red**. Authentication/access approval and authentic file/hardware acceptance remain outstanding. No real reports were uploaded, no service settings changed, and no submissions/email/share actions occurred.

## Historical checkpoint — 02:56 UTC, October 13

- **PR #200 merged as main `0741865eca3b3dbc2bf7d2818b700d33f8790986`.** Its exact head `6f3c8b3` passed CI **38338662857**: **2,223 passed / 2 warnings**, production-container and 512 MiB / 0.5 CPU resource gates. Checkout was PR merge ref `42f8792` into `6937f3f`. Synthetic native artifact **11786416101** and other synthetic output artifact **11786321888** are bounded output evidence. Exact-main CI **38339222180 is running**; new served SHA and serialized live acceptance remain pending. The `6937f3f` replay failure is not cleared by this merge.
- Draft PR #199 published **9a60b6d905bb8fe548661a9c5f49ef4e9ef6f20b**. Required CI **38339019340** and adaptive browser CI **38339019339** are running. Shared loaded-viewer and actual Expense steps passed; PO was running at this checkpoint, Monthly not yet executed. Final job status, artifacts and screenshots must still be inspected. This is not acceptance of all six journeys.
- Root reconciled main `0741865` into the local integration branch without a content conflict. Since the last published PR #199 head, local commits add bounded synthetic runtime observations (`0b2f993`, three privacy/runtime checks), manual period-item helper (`62311b4`, agent reports 127 passed / 1 renderer marker skip), and stronger selected-page image/reading-offset checks (`0b16d49`). Root's separate docs/observations/period selection passed **74 tests**. Guided period-item wiring is still owned by `review_hydration`; workflow switch/return review by `private_route_review`. These unpublished changes have no exact-head CI or deployed acceptance yet.
- The real preview runtime fix remains bounded: root focused preview/reference run **29 passed / 1 renderer-marker skip**. New diagnostics collect only synthetic content hashes, counters, bounded long tasks and DOM focus types; no report text, credentials, network calls or authentic input. Missing private owner authentication, authentic files/expectations, Safari and physical hardware remain separately blocked while the owner sleeps.

## Historical checkpoint — October 13, local integration `c85651e`

- **Main remains `6937f3fdc0ace6639e27deaaacc169e0de4a52b7`; integrated CI 38336524571 passed and the served footer was observed at 02:27 UTC.** Live **38337069339 failed only after the second session's source replay**: both fresh sessions had passed Activity hydration/edit/refresh and the earlier exports. The second replay compared **18/18**, then its Generate action timed out waiting for the DOCX. This is a distinct export/request/fingerprint problem, not a newly observed empty-editor recurrence. Preserve failure artifact **11785458318** and every earlier bounded pass.
- **PR #199 latest published checkpoint is `d42747d`**. Required CI **38337977894 failed: 4 failed / 2,251 passed / 2 warnings in 295.69 seconds**; container and resource jobs passed. The four failures were obsolete novice issue-narrative expectations, two old issue-oracle checks, and the structural PO handoff assertion. Current local fixes passed the combined four-file selection: **28 passed in 11.42 seconds**; required full-head CI still needs rerun. Adaptive workflow **38337977783 failed**: the shared loaded two-page fixture passed its Chromium **and** Playwright WebKit step; the actual Expense fixture failed at the first split interaction because a pointer event was intercepted. **Actual PO and Monthly steps were skipped, not passed.** Evidence artifact **11785695904** is retained. Diagnose application geometry versus fixture synchronization from that trace; neither cause is presumed here.
- Earlier `d807419` required CI **38337327831** finished **2,240 passed / 1 failed / 2 warnings**. The failure was an AST assertion about the single PO handoff's new structural placement; production-container and resource jobs passed. Local correction **ed50079** preserves the intended one-route protection and was included in a **31-passed** focused group. Current full-head CI is still required.
- Local **c85651e** adds exact-report QA action receipts and retains failed-generation evidence: **9 AppTests passed with real LibreOffice exports**, plus a separate **7 lifecycle/gate checks passed**. Browser confirmation of the repaired replay sequence is pending. **e24ffa9** updates the independent issue oracle to check exactly the included canonical cards; **14 tests passed**, and all original **18 known-value/replay checks remain**.
- Source preview reset/late-fragment rejection **30cf1cd** has **13 focused passes**. PO ticket reset **ed50079** is in the separate 31-test group. Layout ownership lifecycle **be06550** and dominant-page retention **d156ee5** passed their Node regressions. Stronger Expense fixture **2378ee1** waits for real images and fragment acknowledgments; actual browser outcome remains pending after the pointer-interception failure. Do not add these overlapping counts.
- Canonical issue cards are implemented with bounded regression evidence; all three Monthly/PO/Expense layout paths are wired. **No complete actual-workflow adaptive journey is accepted yet.** `review_hydration` now owns removing preview-timer full-app reruns; `private_route_review` owns a bounded plain-item old-period resolver. Root owns integration, publication, rerun admission and interpretation of failed browser evidence.
- Reliability [PR #200](https://github.com/evanroden/msapo-generator/pull/200) is separate from the adaptive PR, head **6f3c8b3998ee462dc9ecfca33058d1786fda2f9e** based on main `6937f3f`; **CI38338662857 running**. Root's exact-main-based QA UI selection passed **7 tests in 6.52 seconds with real LibreOffice**, separately from the agent's 9 combined checks. Root plans to merge only after required CI, verify deployment, then run serialized live acceptance while adaptive repairs continue.
- Preview timer repair **9050640** removes the demonstrated timer-triggered full-app reruns. Author reports **50 focused passed / 1 marker-dependent skip**; the diagnostic AppTest observed **2 full runs before versus 1 after**. This is bounded rerun evidence, not gray-freeze or actual browser acceptance. Root's current local code is **57c962e**, including **2c0fb9d** novice assertions adapted to one Add issue action and one canonical card.
- This update changes only this ledger from exact local base **c85651e**. Root will publish the next coherent increment. No owner questions about new authentication, genuine partial-report identity or hardware while the owner is offline; those specific gates remain pending, with independent work continuing.

The earlier checkpoint sections below are historical observations. Their then-pending/running statuses are superseded only by the newer exact-run results above and in the evidence register.

## Historical checkpoint — 02:39 UTC, October 13

- **Main `6937f3f` live run 38337069339 failed on its second fresh session.** First session passed prefill/replay 18/18, real Word/PDF exports, Activity hydration/edit-refresh and reset. Second session passed prefill/export/Activity hydration/edit-refresh and source-replay 18/18, then timed out after 175 seconds waiting for the replay DOCX. Screenshot says the comparison became outdated despite no deliberate edit after comparison. Artifact **11785458318** is retained. This is a generation/request/fingerprint investigation, **not recurrence of the empty Activity editor**; no passing rerun has been substituted. Agent `review_hydration` owns diagnosis. Neutral replay AppTest remained fingerprint-stable across four reruns, so event-specific drift/interruption is still under investigation.
- PR #199 published **d807419e1e605a857e700fe8abaee9a2de739d86**. Its stronger browser run **38337327841 failed** after Chromium geometry and text/page/zoom assertions when the uncaught-error check caught stale callbacks reading a removed page size. Artifact **11785318575** retained. Expense/PO steps did not execute after this failure. Previous head `963f144` full CI **38336703875 passed**, but that is not a pass for newer content.
- Lifecycle repair source **5ef2373**, integrated **42b7895**, explicitly disposes prior component observers/listeners, rejects queued stale callbacks, and keeps timers invocation-local. A runnable Node regression mounts a one-page placeholder then two real pages and invokes the old queued callbacks and cleanup. Focused **31 passed** reported by author; next actual browser run remains required.
- Canonical issue cards source **941fd56**, integrated **11f41ec**, now provide Add/Remove/Clear/Restore and one editable/export model. Unresolved issues carry without routine monthly confirmation; report omission does not resolve an issue or delete history. Source/proposal integrity gates and image provenance remain. Author's **112 focused tests passed**. Root's first integrated selection was **48 passed / 1 failed** because the new test still used the pre-#197 Save progress label; **9c1535f** reconciles it to Save shared version, with **14 issue/shared-label tests passed**. This was a test integration mismatch, not evidence of lost issue data.
- PO actual browser fixture now calls the real builder/master/LibreOffice (`2fb107b`); earlier stub-generated PDFs prove staging only. Actual monthly app harness (`e1f81ae`) uses the production QA/guided/native-preview path, independent fresh cookies and disposable storage, with all external readers/submission paths denied. CI installs LibreOffice for these actual-renderer checks. No local browser pass is claimed.
- Segment-bounded enlargement (`f3c92ab`) retains exact prior page/zoom on Escape. Resource admission/reset source guards, all three workflow layout implementations and stronger actual workflow gates are being published together. Root will hold this coherent batch for exact integrated checks, not merge failing browser gates.

## Previous incremental checkpoint — 02:32 UTC, October 13

- Public browser footer now independently shows **6937f3fdc0ace6639e27deaaacc169e0de4a52b7** after the deployment delay. This was read-only observation of an existing synthetic namespace; no new export or mutation. Exact-main integrated CI **38336524571 passed**; serialized live **38337069339 is running**.
- PR #199 advanced to **963f144f01f3faadd3842d88d4d361796714b884**. **Adaptive browser CI 38336703871 passed** in Chromium and Playwright WebKit after the reference flex-height fix, retaining the pin/release/reverse and transition assertions. Artifact **11785227536** contains 28 checks and screenshots. Inspection found Chromium's first wide screenshot preceded the preview component mount (surface null), so this is bounded wrapper/transition evidence. The next harness waits for actual rendered two-page PDF imagery and asserts viewer mount, page and zoom retention; it does not quietly reinterpret the earlier capture as fully loaded evidence.
- Prior PR #199 full CI **38336061786 passed** on `7d66bfb`; full CI **38336703875** on `963f144` was running. No old-head CI is assigned to newer work.
- Actual PO adaptive integration **0335ced**, integrated locally **5f77e36**, passed **102 focused checks** after its independent isolation prerequisite. Its new actual-app Chromium/WebKit harness and the expense harness are queued for CI. They are separate from the shared layout fixture. No PO submission/share or real-source upload occurred.
- CMMS missing-status completion now requires an explicit source/finish-column-bound rule at the actual mapping operation. Core mapping rejects omission of that choice; unknown coverage remains blank. Local **22 tests passed**, commit **a7896a7**. Neutral reruns retain the choice; a changed mapped column invalidates it.
- Source-preview image work now uses the existing preview work admission slot and global bounded store, and owner-reset generations reject old view callbacks (`21c95d5`). Local source/isolation **6 passed** (overlapping prior counts). Root is publishing these increments, the loaded-viewer harness and the preview-caption duplicate-ID fix next.
- New monthly actual-app browser harness is being authored independently. Private authentication/access approval, authentic source identity, Safari and physical-device evidence remain pending while the owner is offline.

## Previous incremental checkpoint — October 13, after PR #198 merge

- **Latest main is `6937f3fdc0ace6639e27deaaacc169e0de4a52b7`**, the merged revised PR #198. Integrated CI, Render deployment and live acceptance of this new main are pending. The previous main `96567d9ebac1d4d10dc54da89d3ff7320b1a7e59` passed integrated CI **38335373518** and the bounded live run described next.
- **Live 38335944575 succeeded on `96567d9` before the hydration repair:** two independent fresh namespaces, known-value prefill **18/18**, actual **Word files and 26-page PDFs** with content checks, Activity edit/refresh, independent source replay **18/18**, scoped reset and two-tab stale rejection. [Synthetic evidence artifact 11784991719](https://github.com/evanroden/msapo-generator/actions/runs/38335944575/artifacts/11784991719). This bounded success preserves the earlier **38315296356 failure** and does not prove the subsequently revised repair or universal reliability.
- Revised PR #198 head `1136aea41ac81fd10892e32ee727d5b43923c9ec` passed **38335804704**: **2,221 tests, 2 warnings**, production-container and **512 MiB / 0.5 CPU** resource checks. CI checked PR merge ref `2318f14` into `96567d9`. The earlier **30 passed / 1 failed**, corrected **19 passed**, later **37 passed**, and separate **2 post-export AppTests passed** remain bounded local history; overlapping counts are not summed.
- Draft [PR #199](https://github.com/evanroden/msapo-generator/pull/199), branch `completion/phase1-phase2-20261013`, published head `7d66bfb4ba3a8a4b1b96bc9c917421f482b34a6f`: full CI **38336061786 running** at this checkpoint. The first actual DOM workflow **38336061830 failed** the retained first sticky assertion: reference height **1,128 px**, top **−199.828 px**, expected measured top **37.59 px**. **17 pure geometry tests passed**; browser installation worked in CI. Local CSS flex-height repair `31df00c` awaits publication/verification. There is **no sticky DOM pass** yet.
- Expense integration source `f1a2617`, cherry-picked as local `ce4ec06`, pairs each single left editor with the original receipt, keeps mileage review, and shows the actual current packet only through its existing signature gate. Independent expense isolation **2 passed before UI mutation**; focused integration **14 passed**; broader expense checks **97 passed, 1 renderer-dependent skip, 15 deselected**. These overlapping counts are separate. Actual browser expense journeys and sharing remain pending.
- Canonical source date/facility resolver source `42ea953`, integrated locally as `c71908b`: **26 focused source/Water checks passed**; changed-head CI/browser proof pending. Historical-retention and explicit exclusion paths remain to implement/verify. PO isolation **1 passed before layout mutation**; PO integration and issue-card work are ongoing.
- This documentation update starts from local integration `ce4ec06`; local branch content is newer than PR #199's recorded published head. Root owns further publication, CSS/harness fixes and integration. No uncommitted root files were touched by this ledger update.
- Owner is offline and requests no clarifying questions. Leave new authentication/security approval, genuine partial-report identification and physical-device checks pending; continue independent code and CI work. No authentic bytes were transmitted.

## Resume here

1. Refresh merged main `bfbd0b7fb3d5aca7fa810abc5cbc75a7c3ae0de9`, required Tests38426633049, merged-main DOM38426633243 and current served identity. Reviewed PR #199 exact-head CI/DOM and merged-main CI/DOM passed. LIVE06 failed explicitly rejected Generate after both Activity sequences and second replay Compare passed; canonical Activity unexpectedly became empty. The public footer independently served `bfbd0b7` at 16:04. Preserve the earlier failed artifacts and their bounded corrections.
2. Continue the **shared anonymous fixture** increment published on `completion/shared-fixture-testing-20261013` at7442d431 (treec67ab625, equal to local3f42ebc). No PR/CI/deployment exists yet. Reconcile root/worker ownership before edits. Preserve the implemented same-importer integration, exact generation/target checks, cumulative initial-copy admission and162-test local pass. Complete its actual browser harness, fresh exact-head required CI/resource gates and deployment verification. No login or owner-authentication approval is pending. Hidden navigation is not privacy; the UI must plainly disclose shared anonymous access.
3. Open the shared-route PR and complete exact-head checks/review before merging through the existing publication path, observe its actual served build, then verify synthetic shared upload/select/download/import/edit/reset and two-session separation. Authentic files have not been supplied or uploaded. Once that route is verified, request the three explicitly labeled reports and independently authored expectations, including the genuinely half-finished file; do not infer their identities from filenames.
4. Diagnose LIVE06: on servedbfbd0b7 both fresh Activity hydration/edit/durable refresh/clear/refresh/re-entry/refresh and re-entry Word/PDF passed; first replay18/18/export/reset passed; second replay Compare now passed18/18. Generate explicitly rejected a changed fingerprint7ec54bfb879a→255e6263636d, and diagnostics show both working/durable Activity hashes e3b0c442… (empty). Preserve this newly observed canonical-clearing evidence and determine its source. It is not the old Compare failure, a timeout, or recurrence of the original hydration symptom. Do not retry away evidence or accept local passes as production repair.
5. Finish and review Activity protocol commitc6be309, record its publication at the next checkpoint, and run current CI/browser/live evidence. SITE01’s production-run AppTests and public keyboard observation do not establish pointer behavior: retain the new real-browser off/on checks in both engines. Continue the unclosed routine SIM/SRC cases, authentic per-page/native/privacy checks and broader ADP matrix. The reviewed Chromium/Playwright-WebKit journeys are bounded passes. Shipping Safari, screen-reader/touch/IME, physical postures, authentic reports and owner acceptance remain separate. Keep every requirement ID and distinguish implementation from evidence.

The owner explicitly requests incremental commits/merges and detailed continuation notes because the session may stop at a usage limit. Record failed and successful runs independently; no old-head result becomes acceptance of a new integrated head.

## Checkpoint and exact evidence register

| Evidence ID | Commit / operation | Observed result | Scope and remaining limitation |
| --- | --- | --- | --- |
| B01 | Starting main `abb28d7a019d0913e4df843bb7fc40f5db085a6b`; [integrated CI 38314722258](https://github.com/evanroden/msapo-generator/actions/runs/38314722258) | Passed October 12 at 22:12:19 UTC | Integrated baseline code evidence only; subsequent merges require fresh integration checks. |
| L01 | Same starting deployed build; [executed live 38315296356](https://github.com/evanroden/msapo-generator/actions/runs/38315296356) | **Failed** at Activity editor hydration after 60 seconds; known-value prefill **18/18**, actual synthetic Word/PDF content and **3 total / 2 completed / 1 open / 66.7%** had passed | Correct output does not clear the unhydrated editor. [Failure artifact](https://github.com/evanroden/msapo-generator/actions/runs/38315296356/artifacts/11776722119). Do not revive older unrelated failures as the current diagnosis. |
| L02 | [Live run 38321128779](https://github.com/evanroden/msapo-generator/actions/runs/38321128779) | Skipped | No executed acceptance; cannot supersede L01. |
| C195 | [PR #195](https://github.com/evanroden/msapo-generator/pull/195), reviewed head `045cc9e2fa03e7ab9d62b7d6f12938d9f6e66082`; [CI 38313891196](https://github.com/evanroden/msapo-generator/actions/runs/38313891196) | Branch passed; **merged** as `fd4629427669eb32e12f0f42ebdc652d632da041` | Vendor summaries/MSA copy; branch evidence is distinct from integrated/live verification. |
| C196 | [PR #196](https://github.com/evanroden/msapo-generator/pull/196), reviewed head `4e19e78a085b7b7fd1e6d11e3993b6e670e33fb8`; [CI 38314273572](https://github.com/evanroden/msapo-generator/actions/runs/38314273572) | Branch passed; **merged** as `340c26e25645a381dad35c274336b0171c1661b1` | Concise guidance; no measured fresh/resumed/mixed-failure word or click comparison yet. |
| C197 | [PR #197](https://github.com/evanroden/msapo-generator/pull/197), reviewed head `bb360cc74164398b0ea603f08cbc34463e334053`; [CI 38318679487](https://github.com/evanroden/msapo-generator/actions/runs/38318679487) | Branch passed; **merged** as `96567d9ebac1d4d10dc54da89d3ff7320b1a7e59` | Shared-save labeling. This intermediate main is verified by INT02/L03; latest main after #198 is newer. |
| C198 | [PR #198](https://github.com/evanroden/msapo-generator/pull/198), original head `f93f5b2b64872e9b20f0b05b11004d08e2ad15d8`; [CI 38320482747](https://github.com/evanroden/msapo-generator/actions/runs/38320482747) | Historical branch passed; **original mechanism was not accepted unchanged** | Review found pending-receipt overwrite risk. Enhanced intermediate composite check: **30 passed, 1 failed** in failed-persistence recovery. Subsequent fixes and C198-R3 supersede the implementation; this failure evidence is retained. |
| ENV01 | Approved read-only Render inspection and public footer | Main `6937f3fdc0ace6639e27deaaacc169e0de4a52b7` served footer observed at **02:27 UTC**; one configured instance, `plan1c-2g`, disk **1 GB mounted at `/test1`** | Configuration is not measured capacity or redeploy retention. Keep **512 MiB / 0.5 CPU** gate and existing plan. Read-only served proof is separate from LIVE04 failure and authentic acceptance. |
| C198-R2 | PR #198 intermediate head `7005c3f9a38df01e89bef67a4b71c34d37083e10`; [CI 38335482005](https://github.com/evanroden/msapo-generator/actions/runs/38335482005) | Superseded by `1136aea`; no final outcome newly verified for this intermediate run | Do not use an intermediate running/old-head check as current acceptance; use C198-R3. |
| INT02 | Main `96567d9ebac1d4d10dc54da89d3ff7320b1a7e59`; [CI 38335373518](https://github.com/evanroden/msapo-generator/actions/runs/38335373518) | **Passed** integrated required checks | Establishes the post-#195–#197 main. It does not cover the subsequently merged #198 or PR #199 work. |
| LIVE02 | Public redeploy of `96567d9ebac1d4d10dc54da89d3ff7320b1a7e59` | Historical transient 502 during redeploy; later L03 passed | Not a persistent defect claim. Current `6937f3f` is independently served-verified by ENV01, with LIVE04 outcome separate. |
| C198-R3 | Reviewed PR #198 head `1136aea41ac81fd10892e32ee727d5b43923c9ec`; [CI 38335804704](https://github.com/evanroden/msapo-generator/actions/runs/38335804704), checkout PR merge ref `2318f14` into `96567d9` | **Passed: 2,221 tests, 2 warnings; production-container and 512 MiB / 0.5 CPU gates** | Revised receipt/recovery/source-completion repair merged as `6937f3f`; exact main CI passed INT03, served identity ENV01. LIVE04 contains bounded hydration success and a separate replay-generation failure. |
| L03 | [Live 38335944575](https://github.com/evanroden/msapo-generator/actions/runs/38335944575), served main `96567d9ebac1d4d10dc54da89d3ff7320b1a7e59` | **Passed** two fresh namespaces: prefill 18/18; real synthetic 26-page output; Activity edit/refresh; source replay 18/18; reset; two-tab stale rejection | [Artifact 11784991719](https://github.com/evanroden/msapo-generator/actions/runs/38335944575/artifacts/11784991719). Executed before the hydration repair. Preserves L01 failure; not evidence for new repair, complete authentic privacy or universal reliability. |
| INT03 | Main `6937f3fdc0ace6639e27deaaacc169e0de4a52b7`; [CI 38336524571](https://github.com/evanroden/msapo-generator/actions/runs/38336524571) | **Passed integrated required CI** | Main code evidence; separate served identity ENV01 and partially failed live outcome LIVE04. Does not cover newer PR #199/local commits. |
| C199 | Draft [PR #199](https://github.com/evanroden/msapo-generator/pull/199), published `d42747d`; [CI 38337977894](https://github.com/evanroden/msapo-generator/actions/runs/38337977894) | **4 failed / 2,251 passed / 2 warnings, 295.69 s**; container/resource passed | Failures: novice old issue narrative, two old QA issue oracles, structural PO handoff. Fixes `2c0fb9d`, `e24ffa9`, `ed50079` passed combined **28 tests / 11.42 s** locally. Required next-head CI and DOM04 repair still pending. |
| DOM01 | [Adaptive DOM 38336061830](https://github.com/evanroden/msapo-generator/actions/runs/38336061830), first real Streamlit fixture browser execution | Historical **failed sticky assertion**: reference height 1,128 px; top −199.828 px versus 37.59 px | Retained failure. Flex correction later passed DOM02 bounded wrapper geometry and DOM04 loaded shared-fixture checks; actual workflow journeys remain separate. |
| GEO01 | `node --test tests/workspace_geometry_test.cjs` in DOM01 | **17 passed** pure resolver tests | Simulation/logic evidence only; cannot clear DOM01 or prove browser sticky, physical fold, six workflow journeys or accessibility. |
| EXP01 | Expense `f1a2617` / `ce4ec06`; independent isolation before mutation | **2 isolation**, **14 integration-focused**, **97 broader / 1 renderer skip / 15 deselected** passed as separate scopes | Receipt/mileage/current-packet path implemented. DOM04 actual first split pointer interception failed; stronger image/ack harness `2378ee1` pending rerun. No expense journey/native share acceptance. |
| SOURCE01 | Date/facility resolver `42ea953` / `c71908b` | **26 source/Water checks passed locally** | Canonical corrections implemented. Actual corrected output/focus pending. `private_route_review` owns remaining bounded plain-item old-period resolution; authentic access remains blocked. |
| PO01 | Independent PO isolation before layout mutation; layout `0335ced` / `5f77e36` | **1 isolation** before mutation; separate **102 focused** integration checks passed | Actual PO source/MSAPO staging wired; real renderer fixture `2fb107b`. DOM04 skipped PO after Expense failure; no browser journey or submission acceptance. |
| LIVE04 | [Live 38337069339](https://github.com/evanroden/msapo-generator/actions/runs/38337069339), exact served `6937f3f` | **Failed second session's replay Generate** after replay comparison 18/18 and 175-second DOCX wait; both sessions' earlier hydration/edit/refresh and prefill exports passed; first session replay/export/reset passed | [Artifact 11785458318](https://github.com/evanroden/msapo-generator/actions/runs/38337069339/artifacts/11785458318). Screenshot comparison became outdated without deliberate post-comparison editing; exact event/fingerprint cause remains under investigation. No passing rerun substituted. |
| C199-H1 | [Required CI 38336061786](https://github.com/evanroden/msapo-generator/actions/runs/38336061786) at `7d66bfb`; [38336703875](https://github.com/evanroden/msapo-generator/actions/runs/38336703875) at `963f144` | Historical **passed** required checks | Earlier head evidence only; newer `d807419`, `d42747d` and local receipts are not covered. |
| C199-H2 | [Required CI 38337327831](https://github.com/evanroden/msapo-generator/actions/runs/38337327831), `d807419` | **2,240 passed / 1 failed / 2 warnings**; production-container and resource jobs passed | Failure was AST structural placement assertion for the single PO handoff. `ed50079` preserves that protection with **31 focused passes**; current whole-head CI remains pending. |
| DOM02 | [Adaptive DOM 38336703871](https://github.com/evanroden/msapo-generator/actions/runs/38336703871), `963f144` | **Passed** Chromium/Playwright WebKit wrapper/transition checks | [Artifact 11785227536](https://github.com/evanroden/msapo-generator/actions/runs/38336703871/artifacts/11785227536), 28 checks. First Chromium wide capture had surface null; its pass is bounded and not retroactively loaded-image proof. |
| DOM03 | [Adaptive DOM 38337327841](https://github.com/evanroden/msapo-generator/actions/runs/38337327841), `d807419` | **Failed** uncaught-error check after Chromium geometry/text/page/zoom checks | [Artifact 11785318575](https://github.com/evanroden/msapo-generator/actions/runs/38337327841/artifacts/11785318575). Stale callback read removed page size; subsequent workflow steps did not run. Lifecycle fix and Node regression retained. |
| DOM04 | [Adaptive workflow 38337977783](https://github.com/evanroden/msapo-generator/actions/runs/38337977783), `d42747d` | **Shared loaded two-page Chromium + Playwright WebKit step passed; actual Expense first split pointer interception failed; actual PO and Monthly skipped** | [Artifact 11785695904](https://github.com/evanroden/msapo-generator/actions/runs/38337977783/artifacts/11785695904). Workflow result failed. Shared fixture is not actual-workflow acceptance; no presumed application-versus-harness cause. |
| QA-ACTION01 | Local `c85651e`, exact-report QA action receipts and retained failure details | **9 local AppTests passed with real LibreOffice exports**; separate **7 lifecycle/gate checks passed** | Stronger request acknowledgment and diagnosis; replay-generation browser success is still unverified. Preserve actual failure rather than retry until green. |
| ISSUE01 | Canonical cards `941fd56` / `11f41ec`, label reconciliation `9c1535f`, independent oracle `e24ffa9` | Author **112 focused passes**; initial integrated **48 passed / 1 failed** stale Save label; corrected **14 issue/label passes**; separate oracle **14 passes** | Add/Remove/Clear/Restore, unresolved carry and one included export model implemented. Oracle checks exact included cards; all original **18 checks** retained. Counts overlap; actual removal/clear browser/export sequence pending. |
| RESET01 | Source reset/obsolete fragment `30cf1cd`; PO old-ticket release `ed50079` | Source **13 focused passes**; PO correction included in separate **31-passed** group | Rejected late source fragments and released obsolete tickets; actual reset/race/browser exercise still required. |
| LIFECYCLE01 | Preview disposal `42b7895`; layout-owner cleanup `be06550`; dominant preview page `d156ee5` | Focused preview author **31 passed**; layout/page Node regressions passed | Old-callback/page-change/cleanup protections implemented. DOM04 loaded shared-fixture step passed; actual workflow race and gray-freeze acceptance remain open. |
| EXP02 | Stronger actual Expense harness `2378ee1` | Real-image loading and fragment acknowledgments implemented | Browser acceptance pending after DOM04. No simulated PDFs or missing images may stand in for actual source/result surfaces. |
| CMMS01 | Missing-status explicit finish-date mapping `a7896a7` | **22 local tests passed** | Choice binds source/finish column; unknown coverage remains blank. Neutral reruns retain choice, changed mapping invalidates it; actual mapping UI/output acceptance pending. |
| C200 | [PR #200](https://github.com/evanroden/msapo-generator/pull/200), head `6f3c8b3`; [CI38338662857](https://github.com/evanroden/msapo-generator/actions/runs/38338662857) | **Passed: 2,223 tests / 2 warnings**, container/resource; merged as `0741865` | Exact-main INT04 passed; public served0741865; LIVE05 failed at second replay Compare acknowledgment. |
| REGRESSION01 | `2c0fb9d`, `e24ffa9`, `ed50079`; four failed-CI files rerun together locally | **28 passed / 11.42 s** | `test_monthly_report_novice_workspace.py`, `test_monthly_report_qa_ui.py`, `test_monthly_report_qa_activity_after_export.py`, `test_smartsheet_handoff_entrypoint.py`. Updated canonical issue assertions and exact included-card oracle retain original 18 checks and one handoff. Not a full-head CI pass. |
| RERUN01 | Preview timer full-app rerun removal `9050640` | Author **50 focused passed / 1 marker-dependent skip**; diagnostic AppTest full runs **2 baseline → 1 fixed** | Demonstrated unnecessary full rerun removed without replacing queue. Actual browser, interrupted typing, gray-freeze and live-generation outcomes remain unverified. |
| LIVE-HARNESS01 | Root `db86974` replaces added python-docx dependency with standard-library OOXML inspection | Harness dependency correction integrated locally | Existing live runner does not install python-docx. This removes that new dependency without pretending the browser replay generation passed. |
| ENV02 | Local Python environment | Pinned NumPy 2.5.2 import caused a bus error; local-only NumPy 2.3.5 installed for development checks | Repository locks are unchanged. Local checks are not locked-runtime CI; require production dependency/container/resource gates. |
| BASE-SRC | Source inspected at B01 | `requirements.lock` pins Streamlit **1.61.1**; preview viewer **730 px** / mount **760 px**; section debounce **1.5 s**, one preview thread; preview stores **64 MiB PDF / 8 MiB raster**, DPI **96/120/150** | Source facts, not browser measurements or proof of complete adaptive support. Recheck after implementation. |
| H113 | [Prior canonical ledger](MONTHLY_REPORT_STAGE1_CLOSURE_2026-10-10.md#all-113-original-proposed-acceptance-checks--coverage-decision) | Preserves all 113 original scenarios and bounded historical results | Its old `7702256d` live pass is historical; does not accept B01 or later. Original F01–F16, issue #101 P1–P12 and U01–U06 remain mapped there. |
| INT04 | Main `0741865eca3b3dbc2bf7d2818b700d33f8790986`; [CI 38339222180](https://github.com/evanroden/msapo-generator/actions/runs/38339222180) | **Passed** exact-main required CI after merged #200 | Public footer observed at13:56 UTC; separate LIVE05 failed. |
| LIVE05 | [Live 38339777959](https://github.com/evanroden/msapo-generator/actions/runs/38339777959), served `0741865` | **Failed second replay Compare acknowledgment**; both fresh Activity edit/clear/re-entry/refresh and exact Word/PDF cases passed; first replay18/18/export/reset passed | [Artifact11785679075](https://github.com/evanroden/msapo-generator/actions/runs/38339777959/artifacts/11785679075). Second replay generation not reached. No failed outcome replaced with a retry. |
| C199-H3 | `dba839c`; [CI38409751242](https://github.com/evanroden/msapo-generator/actions/runs/38409751242), merge checkout `7107816` into `0741865` | **2,284 passed / 2 warnings / 396.98 s**, container/resource passed | Covers recovered dated-item/workflow-return/observations; later fragment/chrome changes need current-head CI. |
| DOM05 | `dba839c`; [DOM38409750243](https://github.com/evanroden/msapo-generator/actions/runs/38409750243) | **Failed**; shared/Expense assertions passed; actual PO Chromium passed, WebKit module import failed; Monthly sticky passed then WebKit page lost / Chromium correct compact fallback mismatched harness | [Artifact11820348334](https://github.com/evanroden/msapo-generator/actions/runs/38409750243/artifacts/11820348334). Visual review found missed inactive-Expense-caption overlap; strengthened tests/fixes follow. |
| C199-H4 | `98ce0cc`; [CI38411498834](https://github.com/evanroden/msapo-generator/actions/runs/38411498834), merge checkout `ddb0b47` into `0741865` | **2,284 passed / 2 warnings / 228.34 s**, container/resource passed | Does not accept its failed DOM06 or new `6f0c902` head. |
| DOM06 | `98ce0cc`; [DOM38411498858](https://github.com/evanroden/msapo-generator/actions/runs/38411498858) | **Failed overall**; actual PO both engines passed; Expense Chromium passed, WebKit second active receipt stayed placeholder; Monthly WebKit assertions passed, Chromium initial Compare acknowledgment timed out | [Artifact11822766667](https://github.com/evanroden/msapo-generator/actions/runs/38411498858/artifacts/11822766667). Review also found title/chrome overlap and full Monthly reruns; stronger corrected-head checks pending. |
| RERUN02 | Local `5e7ebad`, published `6f0c902`; actual widget-metadata and namespace/reset tests | Local focused **50 passed / 1 renderer-marker skip**; subsequent observer **3 passed**; Node **22 passed** | Only application namespace/lease restored in fragments and callbacks; hidden diagnostics avoid geometry distortion; active tabletop measured visibility/header clearance. Actual browser gates pending. Counts overlap. |
| C199-H5 | `6f0c902`; [CI38413189571](https://github.com/evanroden/msapo-generator/actions/runs/38413189571), checkout `cef1b91` into `0741865` | **2,287 passed / 2 warnings / 383.44 s**, container/resource passed | Browser failure is separate; newer fixes still need current-head CI. |
| DOM07 | `6f0c902`; [DOM38413189905](https://github.com/evanroden/msapo-generator/actions/runs/38413189905) | **Failed overall**; PO both engines and Monthly/Expense Chromium completed; Monthly WebKit cache-miss connection error; Expense WebKit/shared Chromium next-pane imagery failed | [Artifact11822708860](https://github.com/evanroden/msapo-generator/actions/runs/38413189905/artifacts/11822708860). Monthly Chromium full runs 7→7 with fragment progress proves the bounded fragment repair. New stable ancestor binding and cache diagnosis remain pending. |
| C199-H6 | `29b650f`; [CI38415731849](https://github.com/evanroden/msapo-generator/actions/runs/38415731849), checkout `526c351` into `0741865` | **2,289 passed / 2 warnings / 376.22 s**, container/resource passed | New applied-view acknowledgment/Expense packet journey require their own gates. |
| DOM08 | `29b650f`; [DOM38415731769](https://github.com/evanroden/msapo-generator/actions/runs/38415731769) | **Failed overall**; shared, actual Monthly and actual PO passed both engines; Expense WebKit passed, Chromium newly active second receipt lacked image | [Artifact11823802939](https://github.com/evanroden/msapo-generator/actions/runs/38415731769/artifacts/11823802939). No cache error this run; previous failure not erased. |
| VIEWACK01 | Current local applied-viewport acknowledgment and request-ID regression | Node six lifecycle checks; focused preview54/one skip and reference/Expense11/one skip | Separate dispatch/applied state; current browser outcome pending. Counts overlap, skipped renderer not a pass. |
| EXP-PACKET01 | Local `0479952`; genuine Expense production builder in isolated marked storage | Agent focused7/one marker skip; direct real local Calc assertion passed, root reference/Expense11/one marker skip | Real signed five-page PDF/editable workbook and content invalidation checked locally; new actual browser packet journey pending. |
| C199-H7 | `e67c858`; [CI38417323125](https://github.com/evanroden/msapo-generator/actions/runs/38417323125), checkout `ced26d1` into `0741865` | **2,295 passed / 2 warnings / 367.14 s**, container/resource passed | Current scheduling/ack recovery/vault increment needs its own gates. |
| DOM09 | `e67c858`; [DOM38417323298](https://github.com/evanroden/msapo-generator/actions/runs/38417323298) | **Failed overall**; Monthly both engines passed; shared Chromium next image absent; Expense Chromium genuine packet/download passed then return image absent, WebKit packet setup edit incomplete; PO old widget-state receipt failed both | [Artifact11824459260](https://github.com/evanroden/msapo-generator/actions/runs/38417323298/artifacts/11824459260). Exact failure states, wire metadata, real synthetic Expense XLSX/PDF retained. No cache dialog in this run. |
| VAULT01 | Local `87b9b4a`; `test_monthly_report_fixture_vault.py` | **40 passed**, plus root combined vault/docs98 overlapping | Disconnected fail-closed filesystem primitive only; no authenticated route/importer/Render retention or AUTH acceptance. |
| VIEWACK02 | Current client scheduling and bounded receipt recovery | **7 Node lifecycle passed**; focused Python53/two marker skips | Defers view events while app editing rerun is pending/running; two bounded delivery retries then explicit recovery; no test harness retries or weakened imagery assertion. Browser pending. |
| RETURN01 | Local `743a1ec`, included C199-H3 | Isolated actual three-workflow AppTest passed; full suite includes it | Committed text, original files/hashes, splits, overrides, server preview request identity and zero external/live writes; not browser caret/page/zoom or device proof. |
| PERIOD01 | Local `565fe4e`, included C199-H3 | Canonical dated-item UI, exact receipts, exclusion/restore, recovery and native DOCX package assertions passed | Source-linked date corrections; narrow Historical context/exclude choices preserve facts and do not waive price/AI/image gates. Actual routine/authentic browser acceptance open. |
| C199-RELEASE | [PR #199](https://github.com/evanroden/msapo-generator/pull/199), reviewed head `fb095dda`, base `0741865`, tree `9cdbb455`; [CI38425247637](https://github.com/evanroden/msapo-generator/actions/runs/38425247637) | **2,336 passed / 2 warnings / 309.47 s**, production-container and 512 MiB/0.5-CPU gates passed; merged at 15:58 as `bfbd0b7fb3d5aca7fa810abc5cbc75a7c3ae0de9` | Reviewed-head evidence; merged-main required checks are separate INT05. No authentic/owner completion. |
| DOM10 | Reviewed `fb095dda`; [DOM38425247659](https://github.com/evanroden/msapo-generator/actions/runs/38425247659) | **Passed Chromium and Playwright WebKit**; shared46 / Expense86 / PO32 / Monthly72 separate assertions | [Artifact11827834127](https://github.com/evanroden/msapo-generator/actions/runs/38425247659/artifacts/11827834127), SHA256 `99f19ed144040d86e1195eaf31f19145860133093bef7d51872483d1451cda28`. Monthly page2 book816×1056/tabletop1020×1320 decoded with unblurred focus; genuine synthetic five-page Monthly/Expense and actual PO output. No physical/native Safari proof. |
| INT05 | Main `bfbd0b7fb3d5aca7fa810abc5cbc75a7c3ae0de9`; [Tests38426633049](https://github.com/evanroden/msapo-generator/actions/runs/38426633049), [DOM38426633243](https://github.com/evanroden/msapo-generator/actions/runs/38426633243) | **DOM passed; required2,336 passed / 2 warnings / 389.39s**, container/resource passed | MainDOM artifact11829061866 SHA256 `c8429999e473f452332bc50e56bb35794951eb295c305074fe67751667679b91`; screenshots not independently re-reviewed. Does not cover unfinished shared-fixture branch. |
| LIVE06 | [Live38427749463](https://github.com/evanroden/msapo-generator/actions/runs/38427749463), servedbfbd0b7; job115401500635 | **Failed16:08:12** at explicitly rejected second-replay Generate. Both fresh Activity hydration/edit/durable refresh/clear/refresh/re-entry/refresh and re-entry Word/PDF passed; first replay18/18,26-page exports/reset passed; second Compare18/18 passed | [Artifact11830465529](https://github.com/evanroden/msapo-generator/actions/runs/38427749463/artifacts/11830465529), SHA256 `dff72f7b8212814fdf41b87d543bd6d3a8734afe4625f7784917ad38e3bc09e3`. Request1c54d1f922d8/generation34512d3a4259/revision1 changed fingerprint7ec54bfb879a→255e6263636d; working and durable Activity hashes e3b0c442… are empty. Newly observed canonical clearing under diagnosis; not timeout, old Compare failure or original hydration recurrence. |
| ENV03 | Read-only public Purchase-order footer, 16:04 UTC | Served **`bfbd0b7fb3d5aca7fa810abc5cbc75a7c3ae0de9`** | No report opened/generated; no state-changing live test or design-pin verification. Supersedes 13:56 served observation for identity only. |
| ACCESS01 | Owner instruction, 15:36 UTC | Explicitly declined authentication; authorized hidden **anonymous shared fixtures** for coworkers/agents | Owner-only authorization and anonymous-denial requirements superseded, not passed. Hidden route is discoverable; original-byte storage still excluded from Git/build/static/CI/logs. |
| SHARED01 | Shared implementation initially22c8344; published branchhead7442d4314b00d844d054bc86f71c18eb8b6e726d, treec67ab625698e074a383657e7043ffe9d80ebb6e6 equal to local3f42ebc | Root nine-file **162 passed / 19.48s**; earlier107,90,56,45,40,17,13 scopes overlap and are not summed | Published branch only: no PR/required CI/deployment or authentic file. Production importer/edit/refresh and128MiB initial-copy admission locally verified; browser and actual redeploy retention remain pending. |
| ACT-PROTOCOL01 | Local Activity widget protocol/site-state commitc6be309 after LIVE06; publication/CI pending | **41 focused passed**; final **35-test subset passed**, overlapping; independent review found no blockers | Canonical initial value, incarnation-scoped widget ID and absent callback is not intentional clear. Exact live blank origin unknown; no live root-cause/repair acceptance. Generation/fingerprint gate retained. |
| SITE01 | Owner site-selection concern; production `run_web` AppTests and publicbfbd0b7 isolated synthetic observation | Existing **21 AppTests** and new **3 AppTests** passed separate scopes. Public keyboard Space deselected Demo South; settled summary showed1 selected, Demo North | AX text/label/coordinate click/check attempts did not change state; enabled input, no overlay, focus stayed summary. Cause unestablished, not a proven app pointer defect. New actual Monthly Chromium/WebKit pointer-off/keyboard-on gate pending. |
| OWNER | Owner/Safari/hardware/authentic acceptance | Pending | No complete authentic-output or physical-device acceptance is claimed. |

No total is formed by adding overlapping test-suite counts. A branch test, integrated test, browser observation, synthetic export and authentic renderer comparison are different evidence types.

## Ownership and active work

PR #199 is merged. The current shared worktree is on `completion/shared-fixture-testing-20261013`, based on main `bfbd0b7`; remote branch head is `7442d4314b00d844d054bc86f71c18eb8b6e726d`, tree `c67ab625698e074a383657e7043ffe9d80ebb6e6` equal to local `3f42ebc`. Activity protocol/site-state commitc6be309 is local and the browser site-selection extension is still being added; no shared-route PR/CI/deployment yet. Reconcile status and active assignments before touching files. Do not revive older agent file ownership or overwrite those changes.

| Slice | Current ownership / branch | Continuation point |
| --- | --- | --- |
| Integration/publication and route titles | Root; `completion/shared-fixture-testing-20261013` | Watch INT05; preserve ENV03/LIVE05 separation. Own core route/title/URL integration and commits/PR publication. |
| Shared fixture storage/UI/runs and browser evidence | `shared_fixture_storage`, coordinated by root | Shared feature published with162 local passes. Actual browser fixture journey and Monthly pointer-off/keyboard-on site checks being added; both engines pending. No authentic bytes supplied. |
| Activity protocol repair / review | `cache_review` implementation; `private_route_review` independent review | Localc6be309 canonical defaults/incarnation keys/missing-callback guard;41 and overlapping35 focused passes; independent review found no blockers. Exact LIVE06 blank origin remains unknown. Initial-copy admission already integrated; no new storage policy change. |
| Monthly/PO/Expense adaptive release | Root | Reviewed C199-RELEASE/DOM10 merged. Broader ADP, shipping Safari/hardware and authentic acceptance remain; full-main required CI/DOM passed; failed LIVE06 and broader acceptance remain. |
| Canonical source/issue and production live follow-up | Root | Implemented source/date/period/CMMS/issue slices retained. LIVE06 second replay Compare passed; subsequent rejected Generate exposed unexpected canonical Activity clearing. Root/cache_review diagnosis ongoing. Complete routine/assertion mapping rather than claiming all SIM cases. |
| Evidence/documentation | `execution_ledger`, only this ledger, docs/README.md and fixture notes | Maintain all251 IDs and history; document anonymous shared scope accurately. Root commits/publicizes the coordinated increment. |

## Status conventions and row evidence

Each inventory row has independent implementation, exact-head CI, deployed/browser, synthetic output, authentic output, accessibility/device and owner columns. **H** means historical implementation/evidence exists in H113 but individual current attribution remains to be reconciled; it is not a current pass. **Partial** means a bounded slice exists; **Pending** means no qualifying evidence is recorded; **Pending authentic** means the shared route, real input, independent expectations or specified output check lacks qualifying evidence; **Superseded access** records the owner’s15:36 change from owner-only to anonymous shared fixtures without claiming the old security checks passed; **Remaining** means the requested complete behavior is not implemented/verified. **KEEP** preserves an intentional safeguard; it never waives a required check.

B01 proves baseline integrated CI only and is not assigned as proof that each row's scenario ran. Family-level SIM implementation is not evidence that every numbered historical item is complete. Exact historic per-item SIM wording is not present in the repository at this checkpoint; all **97 identifiers are retained below without inventing their numeric-to-copy mapping**. The October 12 audit, when available, supplies that precise attribution. The supplied handoff is sufficient to continue engineering against each family contract now.

For every new result, append an evidence entry with: exact commit/PR and served/design identity, synthetic or private input identity/hash, target contract/sites/month, actual steps/assertions, executed outcome, public synthetic/private authentic evidence location, and remaining limitation. Each relevant row then references that entry. Keep private input/output hashes, reports, contacts, receipts and screenshots out of public notes and CI artifacts.

## P1 reliability, source editing and authentic scenarios

| ID | Requirement / next assertion | Implementation | Exact-head CI | Deployed/browser | Synthetic output | Authentic output | Accessibility/device | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1-R01 | Canonical Activity agrees across visible editor, draft, preview and downloads; clear/re-entry/interruption/reset/stale tabs cannot resurrect deleted work | Merged #201/#204/#212 native hydration, revision receipts and content-scoped Clear; original changes retained | Exact main `ad55fb6`: Required [38513548917](https://github.com/evanroden/msapo-generator/actions/runs/38513548917) and adaptive Chromium/WebKit [38513548892](https://github.com/evanroden/msapo-generator/actions/runs/38513548892) SUCCESS | Exact served [38513993073](https://github.com/evanroden/msapo-generator/actions/runs/38513993073): two first-attempt synthetic sessions, Activity edit/clear/reentry/refresh, 18/18 compare, Generate, reset and stale tab PASS. Historical failures at other SHAs remain recorded. | Both isolated sessions generated synthetic Word/PDF including reentered Activity without tested prices/foreign identities | Owner authentic confirmation pending | Physical Safari/hardware pending | Owner final acceptance pending |
| P1-U01 | Item-specific date/site/period/unreadable remedies update canonical source state and fresh preflight fingerprint | Merged #202 canonical source date/site correction survives return/fresh session; date/period safeguards remain | Source-correction exact branch [38438988867](https://github.com/evanroden/msapo-generator/actions/runs/38438988867) passed and overall main `ad55fb6` CI/DOM passed; not every named source issue independently verified | Synthetic source-form restoration and source-bound work exercised in app; individual authentic cases still pending | Native original byte/hash retained and sample source edits have coverage | Authentic input and corrected output pending | Physical focus/error handling pending | Owner acceptance pending |
| P1-U02 | Direct tables and one issue-card model; Add/Remove/Clear are report-only, durable and distinct from resolving standing history | Merged #199 issue/period controls, #204 and #212 explicit Activity Clear; existing restored-item logic retained | Main `ad55fb6` Required and adaptive tests passed; full original issue/table scenario crosswalk not independently closed | Scoped synthetic Add/Clear/reentry/refresh receipts; every table/issue variant not claimed | Synthetic export and price/privacy path pass; authentic selected export pending | Pending authentic | Hardware and accessibility variants pending | Owner acceptance pending |
| P1-U03 | Same-site reusable pictures/procedures stay in original section; bounded fallback/recovery and real Scorecard/Subcontractor lineage | Historical partial implementation; owner content-specific placement/pagination remains open | Synthetic image, contact and page-invariance checks in main Required passed; real owner layout not established | Chromium/WebKit source/preview interactions passed on bounded synthetic cases | Synthetic Word/PDF tested, not Microsoft Word/Adobe exact-page approval | Pending authentic and image placement review | Physical hardware pending | Owner acceptance pending |
| P1-U04 | One grounded upload route; vendor Activity identity and optional Add/Replace/Dismiss; manual edits and limited CMMS coverage preserved | Merged #211 grounded TXT/DOCX/typed vendor CSV Activity, #216 multi-event ambiguity guard; vendor service distinct from ENFRA onsite work | Final code main `ad55fb6` Required 2,491 tests, Chromium/WebKit and live synthetic passed | Shared normal Starting importer and native Activity editing/exclusion validated synthetically; no claim of all schema choices | CSV work-order counts, vendor/date text, native Word/PDF and price/contact/site guards tested synthetically | Actual owner vendor source/output pending | Physical interaction pending | Owner acceptance pending |
| P1-U05 | Water last reviewed page triggers inclusion once/in order; all-excluded and deliberate removal stay excluded; working captions | Existing reviewed Water/page-selection controls and source correction path; edge acceptance remains | Source/Water targeted checks and main Required suite passed; no universal real Water attachment acceptance asserted | Bounded synthetic Water controls; real all-excluded/page-captions scenario pending | Synthetic page/price filtering tested; owner output pending | Pending authentic | Device-specific review pending | Owner acceptance pending |
| AUTH01 | Real previous-month same-site report into next month; standing material carries but old monthly facts must not become current | Shared anonymous fixture importer merged #201 and synthetic AUTH01–03 process-isolation checks merged #213 | Exact main `ad55fb6` 2,491 Required tests and adaptive Chromium/WebKit PASS; #213 synthetic AUTH01–03 passed in Required suite | Shared Starting importer and isolated replay exercised on synthetic originals; route deployed but intentionally anonymous/not confidential | Local/process-separated synthetic AUTH01 source/target evidence only, plus generic live Word/PDF; no real owner report | **NOT RUN on authentic owner DOCX**, source/target/expected sections needed | Native Word/Adobe and Safari pending | Owner original/independent expected results pending |
| AUTH02 | Real different-site same-contract import; approved schema/contract material only; foreign site work excluded | Shared anonymous fixture importer merged #201, synthetic multi-site AUTH checks #213 and source-site exclusion #211/#216 | Exact main `ad55fb6` Required and Chromium/WebKit PASS; per-owner foreign-site content still unverified | Synthetic site-selection, source isolation and replay validated; no foreign client in tested outputs | Synthetic AUTH02 boundary and original SHA checks; not owner real site outputs | **NOT RUN on authentic owner DOCX** for two actual sites | Physical/browser layout and Word/Adobe pending | Owner source/target site and expected sections pending |
| AUTH03 | Real owner-identified partially completed current-month report; preserve blanks/manual edits and clear without resurrection | Shared importer merged #201 and synthetic AUTH03 checks #213; Activity revision/Clear guards #204/#212 | Exact main `ad55fb6` Required/Adaptive and first-attempt live PASS for separate synthetic exercises | Synthetic partial imported/re-entered/cleared with identity and history guards; no actual owner half-finished file validated | Synthetic source/target independent-process and accepted DOCX/PDF outputs; not authentic | **NOT RUN: owner must identify genuinely partial current-month DOCX** and expected kept/blank/changed fields | Physical Safari, Word/Adobe pending | Owner file and independent expected results pending |

P1-R01 must include the original failing fresh-namespace sequence and event/revision acknowledgments. Capture DOM, canonical/widget state, source identity, generations and request acknowledgments on timeout. Increasing sleeps, hiding assertions, accepting a hidden duplicate editor or retrying until green does not meet it. Local isolated cases must also cover clear-all, new text, repeated generation, source totals accepted twice, correction after acceptance, unsent/partial text where supported, persistence failure/retry, identity switch and reset leases.

## Shared authentic-fixture boundary and superseded access requirements

At15:36 Evan explicitly chose a hidden **shared anonymous** route. The name AUTH01–AUTH03 remains a stable scenario identifier; it no longer implies owner authentication. Fixture list/upload/read/replay/download will be available to anyone discovering `?monthly_qa=fixtures`. The browser cookie separates disposable workspaces; it is not a login. No current authentication question or credential change is pending.

| Original access requirement | Current disposition |
| --- | --- |
| Only Evan may access fixtures; authenticate and authorize each operation | **Superseded by ACCESS01**, not implemented-and-passed |
| Reject unauthenticated list/read/upload/replay/download and keep copied download URLs private | **Superseded for shared fixtures**; anonymous access is intentional and must be disclosed |
| Keep authentic bytes out of public repository/build/static assets/CI/logs | **Retained**; anonymous app sharing is not permission to publish fixture artifacts through development channels |
| Immutable originals/hash, source/target/scenario, owner-labeled partial file and independent expectations | **Retained**; missing labels are not inferred from filenames |
| Fresh isolated run, same production importer, no live fallback/external readers, worker/fragment reset leases | **Retained**, current integrated proof pending |
| Run reset preserves fixture originals; permanent purge requires a separate explicit decision | **Retained**; no automatic expiry or purge added |

SHARED01 reuses the original byte-integrity engine through an explicitly shared storage facade, without calling anonymous visitors authenticated owners. The fixture library is outside disposable QA roots. A fixture is copied into a fresh generation-bound run, verified against its immutable hash, and passed through the same production Starting-report inspection/setup/import/merge pipeline. No expected-content prefill or mock parser replaces extraction. Metadata includes explicit target identity, source identity, scenario and independently supplied expectations. A cumulative admission guard covers initial copies only; generated runs still require their existing bounded resources.

**Current deployment overrides the historical SHARED01 local-only checkpoint:** merged PR #201 exposes the intentionally anonymous shared DOCX route and production Starting importer; synthetic adaptive checks and main `ad55fb6` Required/Adaptive/served-live gates passed. Merged PR #213 exercises invented AUTH01–03 source/target identity and independent-process original reopen. This is **not proof of a selected original surviving a Render code redeploy**, nor authentic owner report acceptance. PR #214's manually dispatched read-only hash-only verifier remains unexecuted without a selected existing synthetic fixture ID, full original SHA, and two distinct observed served builds. Preserve unchanged-original downloads, explicit disclosure of discoverable anonymous access, reset isolation, standing data and no live external readers. See [shared fixture testing](SHARED_FIXTURE_TESTING_2026-10-13.md) and [historical private boundary](PRIVATE_FIXTURE_BOUNDARY_2026-10-13.md).

## Original 113-scenario crosswalk

The original IDs below are prefixed `ORIG-` only to avoid collisions with SIM and ADP identifiers. `ORIG-S01` means exactly old-ledger **S01**, and so forth. Scenario wording and old closure-work mapping are copied from H113. Historical bounded results remain linked there; the original **Not run** label is not converted to a proven defect. Current acceptance still requires the scenario's real input, target, steps and specified environment.

| ID | Original scenario; closure mapping | Current requirement mapping | Implementation | Exact-head CI | Deployed/browser | Synthetic output | Authentic output | Accessibility/device | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ORIG-S01 | New monthly report with no draft; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S02 | Choose multiple sites; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S03 | Start fresh from master; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S04 | Use prior-month report; F01/F10 · P1/P2/P5 | AUTH01 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S05 | Use different site's report; F01/F10 · P1/P2/P5 | AUTH02 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S06 | Use incomplete report; F01/F10 · P1/P2/P5 | AUTH03 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S07 | Change month before Start; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S08 | Return during active work; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S09 | Open older pinned design; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S10 | Unsupported starting file; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-S11 | Checkbox square and label pointer; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | SITE01 existing21/new3 AppTests passed; exact new-head CI pending | SITE01 keyboard settled correctly; pointer no-change cause unknown; both-engine real-browser gate pending | Pending | Pending / AUTH where needed | Touch/screen reader remain pending | Pending |
| ORIG-S12 | Keyboard and touch site selection; F01/F10 · P1/P2/P5 | SIM-S/C; ADP-A16 | H113: F01/F10 · P1/P2/P5 | SITE01 existing21/new3 AppTests passed; exact new-head CI pending | SITE01 keyboard settled correctly; pointer no-change cause unknown; both-engine real-browser gate pending | Pending | Pending / AUTH where needed | Touch/screen reader remain pending | Pending |
| ORIG-P01 | Read start/retention copy; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P02 | Edit and change sections; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P03 | Auto-retain then refresh; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | INT03 passed; new PR199 head pending | LIVE04 hydration/edit/refresh passed both sessions; wider case pending | Historical bounded H113 | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P04 | Force recovery disk failure; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P05 | Brief reconnect while editing; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P06 | Close/reopen in active period; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P07 | Delayed write then later edit; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P08 | Edit two sections around failed retry; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P09 | Standing contact correction; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-P10 | Start fresh after abandonment; F01/F09 · P1/P2 | P1-R01; ADP-A10/A11 | H113: F01/F09 · P1/P2 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N01 | Find Activity, Training and downloads; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N02 | Use section jump navigation; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N03 | Unexplained language review; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N04 | Collapse and reopen help; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N05 | Keyboard-only operation; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N06 | Zoom 200%; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N07 | Narrow viewport; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N08 | Heading structure/screen reader; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N09 | Validation announcement; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-N10 | No None/null in empty tables; F04/F07/F08/F09/F10 · P11/P12 | SIM-G; ADP-A04/A17 | H113: F04/F07/F08/F09/F10 · P11/P12 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A01 | Valid activity source becomes grounded draft; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Historical bounded pass H113 | Historical bounded H113 | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A02 | Multiple sources combine once; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A03 | Manual correction then new file; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A04 | Deliberate deletion not restored; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A05 | Copilot shorten with review; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A06 | Work-order option effect; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A07 | Several photos and captions; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A08 | Corrupt image next to valid; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A09 | Uncertain date/status; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A10 | Remove source with derived edit; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A11 | Active-work return for Activity; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | INT03 passed; new PR199 head pending | LIVE04 hydration/edit/refresh passed both sessions; wider case pending | Historical bounded H113 | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-A12 | Export Activity once correctly; F05/F11 · P10 | P1-R01/U01/U04; SIM-A | H113: F05/F11 · P10 | INT03 passed; QA-ACTION01 local newer | LIVE04 earlier passes; second replay Generate failed | LIVE04 first session actual outputs; second replay output missing | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-V01 | Find Trane upload in Activity; F02 | P1-U04; SIM-MC | H113: F02 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-V02 | Find ENFRA onsite calls; F02 | P1-U04; SIM-MC | H113: F02 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-V03 | Redirect vendor uploaded in call area; F02 | P1-U04; SIM-MC | H113: F02 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-V04 | Unity/USH empty call neutrality; F02 | P1-U04; SIM-MC | H113: F02 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-V05 | Separate vendor and onsite rows; F02 | P1-U04; SIM-MC | H113: F02 | B01 baseline only | Historical bounded pass H113 | Historical bounded H113 | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-V06 | Compare section preview and exports; F02 | P1-U04; SIM-MC | H113: F02 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C01 | Capital source document/table maps native columns; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C02 | Scanned proposal image; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C03 | Mixed price in body/native table; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C04 | Price in pictures/alternate metadata; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C05 | Blank retained price column safe; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C06 | Manual proposal edit survives source rerun; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C07 | DOCX/PDF package/image scan; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-C08 | Ambiguous source table prompts focused choice; U03 · pricing safety | SRC06; ADP-A18 | H113: U03 · pricing safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D01 | Hospital staff Training framing; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D02 | Add monthly training event; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D03 | Reject vendor staff enrollment; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D04 | Thermal first-fill contract storage; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D05 | Explicit NR unchanged; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D06 | Ambiguous similar site labels; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D07 | Show capacity provenance; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D08 | Changed thermal source/historical snapshots; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D09 | Collapsed contact name/role/site; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D10 | Contact current and future update; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D11 | Old completed report unchanged; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D12 | Reuse outage diagram; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D13 | Failed thermal write/retry; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D14 | Ambiguous thermal site prompt; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D15 | Future month thermal reuse; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D16 | Empty event preserves notes; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D17 | Add first/subsequent requirement; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D18 | Missing-site correction; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-D19 | Combined invalid/add-column preserves note; F06/F07/F14 · U04 · standing data | SIM-O/SC/T; ADP-A11/A16 | H113: F06/F07/F14 · U04 · standing data | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R01 | Preview updates after edit; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R02 | Rapid edit rejects older preview; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R03 | Preview/export contention; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R04 | Multi-page preview legibility; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R05 | Preview failure retains prior image; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R06 | Export fresh pinned master; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R07 | Continue saved report; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R08 | Every included section; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R09 | Download real DOCX/PDF; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | INT03 passed; QA-ACTION01 local newer | LIVE04 earlier passes; second replay Generate failed | LIVE04 first session actual outputs; second replay output missing | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R10 | File identity in names; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R11 | Authentic authored PDF comparison; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R12 | Production design pin verified; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R13 | Contact table after diagrams 0/1/4/40; F03/F09/F12/F13/F15/F16 | P1-U03; 0/1/4/40 contacts; ADP-A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R14 | Imported narratives all sections; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-R15 | Footers/blank bullets before/after import; F03/F09/F12/F13/F15/F16 | P1-U03; ADP-A12/A18 | H113: F03/F09/F12/F13/F15/F16 | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-Q01 | Display name is attribution only; Privacy/output safety | SRC06; AUTH access/privacy | H113: Privacy/output safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-Q02 | Private evidence minimized; Privacy/output safety | SRC06; AUTH access/privacy | H113: Privacy/output safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-Q03 | No private artifacts in public repo; Privacy/output safety | SRC06; AUTH access/privacy | H113: Privacy/output safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-Q04 | Malformed/unsafe inputs bounded; Privacy/output safety | SRC06; AUTH access/privacy | H113: Privacy/output safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-Q05 | Only current passive links remain; Privacy/output safety | SRC06; AUTH access/privacy | H113: Privacy/output safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-Q06 | Removed hidden assets do not survive; Privacy/output safety | SRC06; AUTH access/privacy | H113: Privacy/output safety | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-T01 | Tracked deletion/reviewer removed; Merged #99 import integrity | P1-U03; ADP-A16 | H113: Merged #99 import integrity | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-T02 | Supported tracked text/comments; Merged #99 import integrity | P1-U03; ADP-A16 | H113: Merged #99 import integrity | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-T03 | Unsupported structural edit rejected locally; Merged #99 import integrity | P1-U03; ADP-A16 | H113: Merged #99 import integrity | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-T04 | Corrected-copy import retry; Merged #99 import integrity | P1-U03; ADP-A16 | H113: Merged #99 import integrity | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-T05 | Prior import remap after fix; Merged #99 import integrity | P1-U03; ADP-A16 | H113: Merged #99 import integrity | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X01 | Isolated testing mode enabled; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | INT02 baseline; current INT03 pending | L03 bounded pass on `96567d9`; H113 retained | Historical bounded H113 | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X02 | Contact/thermal/logo/report data separation; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X03 | Prefill completed fixture; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | INT02 baseline; current INT03 pending | L03 bounded pass on `96567d9`; H113 retained | L03 18/18; broader acceptance pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X04 | Reset only test data; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | INT02 baseline; current INT03 pending | L03 bounded pass on `96567d9`; H113 retained | Historical bounded H113 | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X05 | Render known-value prefill; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | INT03 passed; QA-ACTION01 local newer | LIVE04 earlier passes; second replay Generate failed | LIVE04 first session actual outputs; second replay output missing | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X06 | Replay original sources separately; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | INT03 passed; QA-ACTION01 local newer | LIVE04 earlier passes; second replay Generate failed | LIVE04 first session actual outputs; second replay output missing | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X07 | Compare authentic Word/PDF elements; Native comparison controls only; authored-app Word/PDF geometry still pending | AUTH boundary; synthetic QA retained | H113: Native comparison controls only; authored-app Word/PDF geometry still pending | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X08 | Failed test write never falls back to live; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X09 | Repeat fixture deterministic; Implemented in merged #136; synthetic exact-head and integrated CI green | AUTH boundary; synthetic QA retained | H113: Implemented in merged #136; synthetic exact-head and integrated CI green | INT02 baseline; current INT03 pending | L03 bounded pass on `96567d9`; H113 retained | Historical bounded H113 | Pending / AUTH where needed | Pending where applicable | Pending |
| ORIG-X10 | Test access/side effects prove isolation; Merged #136 fail-closed QA, external-reader block; #137 merged late-preview lease | AUTH boundary; synthetic QA retained | H113: Merged #136 fail-closed QA, external-reader block; #137 merged late-preview lease | B01 baseline only | Pending (H113 retained) | Pending | Pending / AUTH where needed | Pending where applicable | Pending |

## All 97 simplification records

Each individual ID remains open for exact historic-item attribution and evidence reconciliation; the family contract and demonstrated merged slices are recorded here. Do not label a delivered control missing merely because its row-specific browser check remains pending. KEEP decisions need their original ID and reason once mapped. Count normal-flow visible words, required decisions, repeated headings and clicks on fresh, resumed and mixed-failure reports with optional help closed; hidden QA/admin/conditional diagnostics do not inflate the measurement.

| ID | Family contract / remaining row-level attribution | Implementation | Exact-head CI | Deployed/browser | Synthetic output | Authentic output | Accessibility/device | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SIM-G01 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-G02 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-G03 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-G04 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-G05 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-G06 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-G07 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-G08 | Global preview/status/table tools; one navigation; unique authorized Jump links; About details; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S01 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S02 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S03 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S04 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S05 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S06 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S07 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S08 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S09 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S10 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S11 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-S12 | Concise sites/month/start/resume; truthful draft/shared scope; secondary directories/admin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-C01 | Secondary replacement import; detected source/carry result; immutable readable design pin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-C02 | Secondary replacement import; detected source/carry result; immutable readable design pin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-C03 | Secondary replacement import; detected source/carry result; immutable readable design pin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-C04 | Secondary replacement import; detected source/carry result; immutable readable design pin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-C05 | Secondary replacement import; detected source/carry result; immutable readable design pin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-C06 | Secondary replacement import; detected source/carry result; immutable readable design pin; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O01 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O02 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O03 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O04 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O05 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O06 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O07 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-O08 | Counts/Edit/person summaries; scoped contacts; no false dirty; native contact page/rows; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A01 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A02 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A03 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A04 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A05 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A06 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A07 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A08 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A09 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A10 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A11 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A12 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A13 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A14 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-A15 | One authoritative work summary/upload/photos; grounded totals; lineage; paid-operation consent; historic individual mapping pending | C198-R3 merged; P1-U04 remainder; exact ID map pending | INT03 passed; CMMS01/QA-ACTION01 local; current head pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-SC01 | Saved capacity Edit/Replace; one notes field; NR/provenance/units/current-vs-history; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-SC02 | Saved capacity Edit/Replace; one notes field; NR/provenance/units/current-vs-history; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-SC03 | Saved capacity Edit/Replace; one notes field; NR/provenance/units/current-vs-history; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-SC04 | Saved capacity Edit/Replace; one notes field; NR/provenance/units/current-vs-history; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-SC05 | Saved capacity Edit/Replace; one notes field; NR/provenance/units/current-vs-history; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-M01 | Concise Monitoring status; accessible definition; absent report is not normal/no-start; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-M02 | Concise Monitoring status; accessible definition; absent report is not normal/no-start; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-M03 | Concise Monitoring status; accessible definition; absent report is not normal/no-start; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-M04 | Concise Monitoring status; accessible definition; absent report is not normal/no-start; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-MC01 | Vendor/onsite separation; native calls columns; no inferred Unity absence notices; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-MC02 | Vendor/onsite separation; native calls columns; no inferred Unity absence notices; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-MC03 | Vendor/onsite separation; native calls columns; no inferred Unity absence notices; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-V01 | Recognizable vendor/site/contact/MSA; direct editing and scoped removal; native columns; historic individual mapping pending | C195 merged; exact ID map pending | C195 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-V02 | Recognizable vendor/site/contact/MSA; direct editing and scoped removal; native columns; historic individual mapping pending | C195 merged; exact ID map pending | C195 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-V03 | Recognizable vendor/site/contact/MSA; direct editing and scoped removal; native columns; historic individual mapping pending | C195 merged; exact ID map pending | C195 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-W01 | Automatic once-only reviewed-page inclusion; compact controls; date/site/caption/removal; historic individual mapping pending | SOURCE01 date/site local; P1-U01/U05 remainder; exact ID map pending | SOURCE01 local 26; current CI pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-W02 | Automatic once-only reviewed-page inclusion; compact controls; date/site/caption/removal; historic individual mapping pending | SOURCE01 date/site local; P1-U01/U05 remainder; exact ID map pending | SOURCE01 local 26; current CI pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-W03 | Automatic once-only reviewed-page inclusion; compact controls; date/site/caption/removal; historic individual mapping pending | SOURCE01 date/site local; P1-U01/U05 remainder; exact ID map pending | SOURCE01 local 26; current CI pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-W04 | Automatic once-only reviewed-page inclusion; compact controls; date/site/caption/removal; historic individual mapping pending | SOURCE01 date/site local; P1-U01/U05 remainder; exact ID map pending | SOURCE01 local 26; current CI pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-W05 | Automatic once-only reviewed-page inclusion; compact controls; date/site/caption/removal; historic individual mapping pending | SOURCE01 date/site local; P1-U01/U05 remainder; exact ID map pending | SOURCE01 local 26; current CI pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-W06 | Automatic once-only reviewed-page inclusion; compact controls; date/site/caption/removal; historic individual mapping pending | SOURCE01 date/site local; P1-U01/U05 remainder; exact ID map pending | SOURCE01 local 26; current CI pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-W07 | Automatic once-only reviewed-page inclusion; compact controls; date/site/caption/removal; historic individual mapping pending | SOURCE01 date/site local; P1-U01/U05 remainder; exact ID map pending | SOURCE01 local 26; current CI pending | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-I01 | One open issue list Add/Remove/Clear; distinct report omission/resolution/history; historic individual mapping pending | ISSUE01 implemented; historic individual mapping pending | ISSUE01 bounded tests/oracle; current full-head pending | Actual card removal/clear/restore pending | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-I02 | One open issue list Add/Remove/Clear; distinct report omission/resolution/history; historic individual mapping pending | ISSUE01 implemented; historic individual mapping pending | ISSUE01 bounded tests/oracle; current full-head pending | Actual card removal/clear/restore pending | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-I03 | One open issue list Add/Remove/Clear; distinct report omission/resolution/history; historic individual mapping pending | ISSUE01 implemented; historic individual mapping pending | ISSUE01 bounded tests/oracle; current full-head pending | Actual card removal/clear/restore pending | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-CR01 | Direct Capital tables without upload; concise priority/timing; native geometry and no prices; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-CR02 | Direct Capital tables without upload; concise priority/timing; native geometry and no prices; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-CR03 | Direct Capital tables without upload; concise priority/timing; native geometry and no prices; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-P01 | Direct proposal tables; native status/scope/alternatives; all-representation price gate; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-P02 | Direct proposal tables; native status/scope/alternatives; all-representation price gate; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-P03 | Direct proposal tables; native status/scope/alternatives; all-representation price gate; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-T01 | Collapsed additions; client/hospital scope; scalar date; blank/status/hours; validation retention; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-T02 | Collapsed additions; client/hospital scope; scalar date; blank/status/hours; validation retention; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-T03 | Collapsed additions; client/hospital scope; scalar date; blank/status/hours; validation retention; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-T04 | Collapsed additions; client/hospital scope; scalar date; blank/status/hours; validation retention; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-T05 | Collapsed additions; client/hospital scope; scalar date; blank/status/hours; validation retention; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-T06 | Collapsed additions; client/hospital scope; scalar date; blank/status/hours; validation retention; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-T07 | Collapsed additions; client/hospital scope; scalar date; blank/status/hours; validation retention; historic individual mapping pending | Historical slices; exact ID map pending | B01 baseline only | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R01 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R02 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R03 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R04 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R05 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R06 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R07 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R08 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R09 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |
| SIM-R10 | Native RFI/continuations; actionable review; true sizes/current downloads; shared-save/reset scope; historic individual mapping pending | C197 and earlier slices merged; exact ID map pending | C197 branch pass | Pending item-specific check | Pending item-specific mapping | Pending / AUTH where needed | Pending where applicable | Pending |

## Six conditional safeguards

These safeguards are intentional; normal-flow simplification must not erase them. KEEP is a design disposition, not proof that current behavior passed.

| ID | Conditional behavior | Implementation | Exact-head CI | Deployed/browser | Synthetic output | Authentic output | Accessibility/device | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SRC01 | One source-linked editor; no hidden competing representation | KEEP; revised hydration merged; ISSUE01 single included-card model local | INT03 passed; ISSUE01 regressions/oracle pass; current full-head pending | LIVE04 hydration passed; separate replay Generate failure remains | Earlier LIVE04 exports bounded; final second replay absent | Pending | Pending | Pending |
| SRC02 | Deliberate picture-to-editable-contact replacement with scope/provenance | KEEP; merged slice | Pending attribution | Pending | Pending | Pending authentic | Pending | Pending |
| SRC03 | Newer-version conflict comparison with safe explicit choices | KEEP; merged slice | Pending attribution | Pending two-tab case | Pending | Pending | Pending | Pending |
| SRC04 | Optional writing help requires deliberate Add/Replace/Dismiss; failure/dismissal preserves manual wording | KEEP; merged slice | Pending attribution | Pending | Pending | Pending | Pending | Pending |
| SRC05 | Corrected #167 bounded section-page fallback and specific blocking recovery; abandoned auto-omission is not current | KEEP; corrected merged slice | Pending current mapping | Pending | Pending | Pending authentic | Pending | Pending |
| SRC06 | Limited truthful price-safety claims; required unresolved content cannot be waived by generic checkbox | KEEP; merged partial safeguards | Pending current mapping | Pending | Bounded canaries only | Pending authentic; package/image breadth open | Pending | Pending |

## Adaptive acceptance: all 20 categories

All three workflows must be covered where applicable. Geometry injection is labeled simulation; Chromium/WebKit-family runs, shipping Safari and physical fold hardware are separate. A single screenshot or source assertion cannot establish sticky boundaries, state preservation or touch usability.

| ID | Required scenario/assertion | Implementation | Exact-head CI | Deployed/browser | Synthetic output | Authentic output | Accessibility/device | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADP-A01 | Real monthly long-section sticky top, boundary release and next arrival; geometry/screenshots | Shared section/layout merged #199; broad acceptance remains | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: real long-section sticky/release/next arrival; full populated section matrix remains | Real five-page Activity section rendered | Pending where relevant | Pending | Pending |
| ADP-A02 | Reverse scroll restores section preview/page/zoom; no overlap/global swap | Boundary/page anchors plus hidden/unknown-pagination repair implemented | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: real reverse/page2/zoom retention; earlier page-loss failures retained historically | Actual selected output page decoding enforced | Pending where relevant | Pending | Pending |
| ADP-A03 | Short/empty sections, multiline headings, tall tables, controls/errors without blank padding/clipping | Keyed bounds/viewer sizing implemented | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 bounded short/empty/real-viewer checks passed; full multiline/tall-table/error matrix remains | Full short/tall/error matrix remains | Pending where relevant | Pending | Pending |
| ADP-A04 | Laptop/tablet/compact portrait/landscape, partial windows and large text; internal content fits | Shared compact/wide and all workflow layout paths wired | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 all three workflows in bounded compact/wide/book/tabletop; large-text/full width matrix remains | Pending | Pending where relevant | Pending | Pending |
| ADP-A05 | Book symmetric/asymmetric/off-center/zero-gap/nonzero-gap/app-root-offset geometry and posture labels | Measured book geometry and all workflow wiring implemented | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 measured injected book geometry and decoded own references passed; physical fold/asymmetry matrix remains | Pending | Pending where relevant | Pending | Pending |
| ADP-A06 | Tabletop upper/lower, deterministic active boundary/hysteresis, one lower work scroll root and keyboard fallback | Measured tabletop active pane/lower root; RERUN02 visibility/chrome correction | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 actual active upper references/lower work root and transitions passed; native keyboard/full hysteresis matrix remains | Pending | Pending where relevant | Pending | Pending |
| ADP-A07 | Missing/disabled/malformed APIs, one/extra/zero segments, hidden return and rapid events fail safely | Validated topology fallback and subscription lifecycle implemented | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 shared fallback/lifecycle checks passed; full actual malformed/rapid/background matrix remains | Pending | Pending where relevant | Pending | Pending |
| ADP-A08 | Unblurred typing/composition through rotate/fold/resize; exact draft/focus/selection where supported | Single editor and lifecycle/selection preservation paths implemented | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 unblurred value/focus/selection checks passed including real Monthly page2; IME/native rapid transitions pending | Pending | Pending where relevant | Pending | Pending |
| ADP-A09 | Workflow switch/return preserves sources, splits, overrides, report notes and preview page | All workflows wired; RETURN01 isolated actual-workflow return implemented | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | RETURN01 bounded cross-workflow state preserved; DOM10 exact source/output return; cross-workflow browser caret/page scope remains | Original sources/splits/overrides/notes and server preview scope preserved | Pending where relevant | Pending | Pending |
| ADP-A10 | Monthly refresh/reconnect, interrupted input, failed write/retry, stale acknowledgments and two tabs | Hydration/receipts merged; RERUN02 current fragment ownership repair | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | LIVE06 both clear/re-entry/refresh/export cases passed; second Compare passed then canonical Activity emptied and Generate rejected | Current wording in actual Word/PDF passed | Pending where relevant | Pending | Pending |
| ADP-A11 | Automatic standing contacts/thermal keep correct site/provenance/NR/snapshots/conflicts; zero writes on view change | Standing protections retained; layout integration merged #199 | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | RETURN01 bounded zero standing writes retained; complete standing-data/concurrency matrix pending | Pending scoped case | Pending where relevant | Pending | Pending |
| ADP-A12 | Slow/error/stale completion/pagination/cache eviction/contention retain truthful bounded last-good/current states | Reset/lifecycle and hidden-anchor safeguards implemented | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 real decoded selected pages/exact return passed; bounded selected-image/ack repairs tested; full cache/failure/late-job matrix remains | Pending | Pending where relevant | Pending | Pending |
| ADP-A13 | Scroll current output causes zero AI/unneeded assembly; visibility/page/DPI/priority remain bounded | RERUN02 binds only QA namespace/lease and enforces actual fragment ownership | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 navigation/scroll used fragment-only progress with unchanged full-app count; authentic image-heavy gray-freeze attribution remains | Gray-freeze/image-heavy assembly attribution remains | Pending where relevant | Pending | Pending |
| ADP-A14 | PO Upload/Paste, unresolved contact, new/change order, multipage quote, output invalidation and manual two-file handoff | PO isolation/layout and actual MSAPO fixture wired; reset ticket cleanup | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 PO original quote/actual MSAPO and exact page2/125% return passed both engines; full Upload/Paste/change-order question matrix remains | Real five-page MSAPO, original quote and exact comparison return passed | Pending where relevant | Pending | Pending |
| ADP-A15 | Expense single/multiple/split/duplicate receipts, mileage-only, partial failures, exclusions/coding and share cancellation/fallback | Expense receipt/mileage/packet paths wired; EXP02 stronger waits | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: original receipts/splits/mileage plus actual49.00 workbook/five-page packet and exact return; native sharing/cancel/failure breadth pending | Actual49.00 workbook/five-page PDF; signed split lines and exact packet return verified | Pending where relevant | Pending | Pending |
| ADP-A16 | Monthly new/returning/combined-site, all sections, image/caption, vendor, blanks, Training/rollover/preflight | Monthly wiring, SOURCE01/PERIOD01/CMMS01/ISSUE01 implemented slices | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 real Monthly18/18/five-page section/blank/transition checks passed both engines; all sections/rollover/routine matrix remains; SITE01 local site-selection passes, actual pointer/keyboard gate pending | Real synthetic section outputs; authentic scenarios not run | Pending where relevant | Pending | Pending |
| ADP-A17 | Mouse/touch/keyboard/screen reader/zoom, offsets/dialogs and reflow with no focus theft or repeat announcements | Shared semantic/view controls implemented; complete access matrix remains | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 pointer/title-clearance/focus checks passed; screen reader/touch/IME/shipping Safari and large-text matrix pending | Pending | Pending where relevant | Pending | Pending |
| ADP-A18 | Actual native documents retain geometry/images/links; monthly prices absent while legitimate PO/expense amounts stay | Native rules preserved; canonical cards/oracle and real-renderer fixtures | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 actual synthetic Monthly/PO/Expense files inspected; real monthly price/site/package-image breadth and authentic geometry remain | Authentic layout and full package/image privacy remain; no universal claim | Pending where relevant | Pending | Pending |
| ADP-A19 | Locked production dependency/container and 512 MiB / 0.5 CPU gate without plan changes | Existing plan/locks and capped resource gate retained | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | C199-RELEASE production/container/resource passed; INT05 container/resource passed; no changed plan or measured-capacity claim | Capped real output gates passed on named heads | Pending where relevant | Pending | Pending |
| ADP-A20 | Exact final commit, required CI, public served identity and smoke evidence recorded independently | Mainbfbd0b7 merged #199; unfinished shared route separate; final not reached | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | ENV03 publicbfbd0b7 observed16:04; INT05 required CI/DOM passed; latest production LIVE06 canonical-clearing/rejection failure remains separate | Exact synthetic artifacts retained; final/authentic not accepted | Pending where relevant | Pending | Pending |

## Six first-class adaptive journeys

| ID | Journey and context contract | Implementation | Exact-head CI | Deployed/browser | Synthetic output | Authentic output | Accessibility/device | Owner |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ADP-J01 | Monthly book: one ordered page; each single left editor paired with own actual right preview; section-scoped stick/release/reverse | Monthly wired; actual native fixture installed | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: own actual preview sticky/release/reverse, book page2 decoded816×1056 with unblurred focus | Real five-page section and selected page2; full section/physical matrix remains | Pending | Simulated/native separate | Pending |
| ADP-J02 | PO book: corrections/unresolved review left; exact original quote/pasted snapshot right; package review deliberately shows actual MSAPO | PO source/corrections/current MSAPO pairing wired | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: original quote/current MSAPO pairing and exact page2/125%/identity/offset return | Original multipage quote and generated five-page MSAPO; pasted/full unresolved cases remain | Pending | Simulated/native separate | Pending |
| ADP-J03 | Expense book: receipt details/splits/exclusions left; same original right, pair-scoped stick/release; mileage uses real trip review | Expense receipt/source pairing wired; original imagery gate strengthened | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: receipt/split/second-source/page2/unblurred checks passed; full receipt-boundary matrix remains | Actual original receipts plus49.00 editable workbook/five-page packet; no sharing invoked | Pending | Simulated/native separate | Pending |
| ADP-J04 | Monthly tabletop: actual active preview above; same ordered editor below as main scroll root; hysteresis/jumps/page/zoom/stale rejection | Monthly tabletop wired; RERUN02 fragment/visibility/title refinements | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: active actual upper page2 decoded1020×1320; lower single editor, focus and fragment-only navigation retained | Selected-image assertion and screenshot passed; full native keyboard/hysteresis matrix remains | Pending | Keyboard/native hardware pending | Pending |
| ADP-J05 | PO tabletop: matching quote/text above lower corrections; actual MSAPO at package review; overrides/exact return retained | PO tabletop/source/result pairing wired | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: quote/result tabletop context and exact comparison return passed | Actual MSAPO and original quote; no submission; broader unresolved-stage cases remain | Pending | Keyboard/native hardware pending | Pending |
| ADP-J06 | Expense tabletop: source matches active lower receipt; generated packet only at review; mileage context and all splits/identity survive | Expense receipt/mileage/current-packet pairing wired; RERUN02 active visibility fix | C199-RELEASE passed; INT05 required CI/DOM passed; row-specific proof bounded | DOM10 both engines: active second receipt, mileage and actual packet/exact return passed | 49.00 five-page packet/editable workbook; page2/125% return; native sharing/physical keyboard pending | Pending | Keyboard/native hardware pending | Pending |

Temporary source comparison must return to the exact prior output page/zoom in all six journeys. Focus, warning appearance or preview-height changes must not switch monthly output to unrelated sources/Copilot/settings. Optional explicit view focus persists until cleared. No layout event may approve facts, create history, trigger an external reader, submit Smartsheet or open sharing/email.

## Implementation contract and remaining proof

- Keep the first-party Streamlit app with shared measured display-context/layout/view-state primitives and stable single editor keys/mirrors. Geometry stays client-side except bounded meaningful events; it cannot trigger OCR/AI/assembly/business saves/app-wide reruns.
- Validate finite positive segment rectangles and app intersection; distinguish layout viewport, visual viewport, app root and scrollport coordinates; account for chrome/safe areas once. Do not assume symmetry, hinge angle or `50vh`. A chosen crease clearance is not a measured gap. One segment can support ordinary wide layout.
- Ordinary wide/book monthly layout uses real keyed section bounds and its own preview per section. No global document-swapping pane. Sticky top derives from actual persistent navigation; short sections do not get artificial screenfuls. No framework-input cloning/reparenting or global column selectors.
- Tabletop intentionally owns lower editor scroll and bounded upper reference, with deterministic section/receipt/stage choice and boundary hysteresis. Too-small keyboard-visible space enters stable fallback and restores context afterward. No fake product specifications or physical-device proof.
- Separate content, view and async job state; scope page/zoom/reading state by workflow/report/section/receipt/stage. Keep last-good output truthful and bounded; late generations/reset leases cannot replace current work. View changes preserve review fingerprints and cannot make stale exports current.
- Preserve immutable pins, conversion admission, bounded caches and worker/periodic-fragment QA context. Instrument full versus fragment reruns, long tasks/focus/fingerprints/jobs/leases to investigate the reported gray freeze; an uncaptured symptom is not disproved.
- Prove PO and Expense test isolation independently before mutating their live flows. Preserve calculations, source bytes/hash identity, source selection, leading-zero codes, original PO logic, expense per-receipt state and explicit manual submission/share handoffs.
- Authentic output still requires every affected page, real master frames/spans/headers/continuations, divider 10, contacts 0/1/4/40, diagrams/photos/captions/aspect ratios, furniture/links/blanks/collisions. The known unchanged-authored 40-page Adobe versus 43-page LibreOffice difference is historical renderer evidence, not universal acceptance.
- Monthly price/site privacy coverage must extend beyond text to formulas/results, images/OCR/PDF imagery, EMF/VML/WordArt, metadata/embedded objects and retained OOXML parts. Do not delete approved artwork wholesale or weaken gates to make scans green.

## Reproducible checks and non-overlapping evidence

- Required CI remains the repository's locked pytest, production container and resource workflows. C198-R3 reports **2,221 passed / 2 warnings** at its PR merge ref; do not transfer that count to PR #199 or new main without their run results.
- `node --test tests/workspace_geometry_test.cjs` passed **17 pure geometry** tests in historical DOM01, whose first sticky assertion failed. Later `python scripts/qa_adaptive_workspaces.py` passed the stronger loaded two-page shared fixture in both engines in DOM04. Actual Expense then failed pointer interaction; PO and Monthly steps were skipped. Preserve each distinct result; a shared-fixture pass is not a workflow journey pass.
- `.github/workflows/adaptive-workspaces.yml` installs locked app dependencies and Playwright 1.58.0, then Chromium/WebKit; browser installation succeeded in CI. Local truncated-ZIP installation remains an environment limitation, not permission to call geometry accepted or to weaken the assertion.
- Expense isolation uses `tests/test_expense_workspace_isolation.py` with separate AppTest sessions and bounded temporary storage. Its **2**, focused **14**, and broader **97 / 1 skipped / 15 deselected** results overlap; preserve them as separate run scopes. The renderer skip means the skipped output case remains unexecuted locally.
- SOURCE01's **26** source/Water checks cover canonical date/facility corrections; PERIOD01 separately covers bounded historical/exclusion behavior; authentic output remains open. PO01's **1** pre-mutation isolation and separate **102** integration checks remain distinct. ISSUE01 oracle **14** checks preserve all original 18 facts; QA-ACTION01 **9** real-export AppTests and separate **7** gate/lifecycle checks do not establish live replay success.
- Local Python dependency caveat ENV02 remains in force. Exact command selectors and full transcripts for each targeted local aggregate belong with that commit's execution notes; no invented selector/run count is used to turn a reported aggregate into a broader pass.

## Release record to complete before claiming finished

| Field | Current value |
| --- | --- |
| Starting baseline | `abb28d7a019d0913e4df843bb7fc40f5db085a6b` |
| Latest merged checkpoint | `ad55fb6b9e043f10812224f00c9c17b78845ff8e` (PR #216 on #217/#214/#213/#212/#211/#206) |
| Final integrated implementation SHA | Code integrated on `ad55fb6b9e043f10812224f00c9c17b78845ff8e`; **owner release acceptance not reached**; final docs PR #218 is pending |
| Exact required CI | [Main Required 38513548917](https://github.com/evanroden/msapo-generator/actions/runs/38513548917) **SUCCESS**, 2,491 tests/two openpyxl warnings, container and 512 MiB / 0.5 CPU; [main adaptive 38513548892](https://github.com/evanroden/msapo-generator/actions/runs/38513548892) **SUCCESS** |
| Public served SHA / design pin | Exact `ad55fb6b9e043f10812224f00c9c17b78845ff8e` served in [live 38513993073](https://github.com/evanroden/msapo-generator/actions/runs/38513993073); independently tested synthetic output, not owner Word/Adobe/physical acceptance |
| Serialized first-attempt fresh-namespace live runs | [ad55fb6 deployed live 38513993073](https://github.com/evanroden/msapo-generator/actions/runs/38513993073) **SUCCESS**, two first-attempt isolated Chromium sessions, each 18/18 source comparisons, accepted Generate, native Word/PDF, Activity edit/clear/reentry/refresh, reset/stale-tab guard. Historical [d261a live 38513519449](https://github.com/evanroden/msapo-generator/actions/runs/38513519449) failed reentry; preserve failure evidence. |
| AUTH01 / AUTH02 / AUTH03 inputs and expectations | Merged synthetic original importer and independent process tests #201/#213, but **zero genuine owner AUTH reports uploaded/accepted**. Need specific owner source/target/period, actual partial file, independent expectations and output review. Shared fixture route is anonymous/discoverable. |
| Authentic Word/PDF and package/image privacy | Pending; keep actual evidence out of public Git/build/static/CI/logs and disclose shared-route access |
| ADP-A01–A20 and ADP-J01–J06 actual DOM evidence | [Main Chromium/WebKit adaptive 38513548892](https://github.com/evanroden/msapo-generator/actions/runs/38513548892) **SUCCESS** on synthetic book/tabletop, PO, Expenses, Monthly and fixture Starting routes. Detailed original 20/6 rows remain bounded; physical Safari/tablet/foldable acceptance pending. |
| Safari / physical posture / owner acceptance | Pending; never inferred from injected geometry or Playwright WebKit |
| Rollback | Revert scoped code through existing workflow; retain original fixtures, standing history/designs and compatible storage. No data reset/purge. |

No new whole-report browser storage, mandatory login/cloud-draft project, automatic financial action, hosting upgrade or permanent deletion is authorized. The owner explicitly authorized anonymous shared fixture access and declined authentication; **no authentication approval is pending**. Hidden navigation must never be described as private access.

## Concise owner batches after qualifying automation

For each batch first fill in the exact served build and verified testing destination/access scope, then provide screen/control, expected result and what evidence to return on failure. Do not ask the owner to replace automation with a long engineering checklist.

1. **Reliability:** Activity enter/create/download/return/clear/re-enter/refresh; current editor and exports agree, deliberate emptiness respected.
2. **Routine use:** edit table/remove issue/correct named source date-site/review Water/create; no duplicate editors or routine unchanged approvals.
3. **Actual reports:** after the shared route is deployed and verified, use its disclosed anonymous shared upload/select area. Identify all three real fixtures and the genuinely partial file; review source/target, independent expectations and actual output pages. Anyone discovering this route may access its fixtures.
4. **Wide/book:** long monthly boundaries forward/back and page/zoom; multipage PO and split/multiple receipts, with no sending/submission.
5. **Tabletop/compact:** type through supported transition, inspect matching upper source/output and temporary-view return; exact values/splits/uploads/page/zoom retained. Label simulation and physical hardware separately.
6. **Final output:** monthly Word/PDF, PO package, expense workbook/PDF; exact renderer/page-level differences, correct price boundaries.

## Inventory accounting

This ledger explicitly enumerates **113 original scenarios**, **97 SIM records**, **6 SRC safeguards**, **6 P1 repair/editing requirements**, **3 AUTH scenarios**, **20 ADP categories** and **6 ADP journeys**: **251 tracking rows**, not 251 defects or independent test passes. Overlapping proof must be mapped explicitly, never counted repeatedly as distinct coverage.


## Retained October 16 implementation and CI history — from94116f8

This is a superseded snapshot, not another live ledger. Source commit `94116f87d298b92149b13014bfc20f39ac9e131e`;
original remaining-work SHA256 `fde4aba2de0927557c63e9b423f8be90a8985b10d366fee370b43cefe012ebce`.
The following narrative and ordered table are copied verbatim: 68,433 bytes,
SHA256 `db4fb010a35efa55ea7973e23c0b69b10739be8cf76255c0ee78e4fd57fa4c2d`. The exact source/hash marker is the duplicate guard;
do not append this segment again. Original execution body (258,120 bytes) is unchanged
above this appended archive; SHA256 `e3902837bc098537069258e1e5b55f9ab1f6bb6b2a91e2ece2839217cf8eb59d`.

<!-- ENFRA_LEDGER_ARCHIVE source=94116f87d298b92149b13014bfc20f39ac9e131e segment=narrative-through-ordered-table sha256=db4fb010a35efa55ea7973e23c0b69b10739be8cf76255c0ee78e4fd57fa4c2d -->
Cover/history scope repair 2026-10-16 19:23 UTC: PR252 head3843873's
Adaptive38952943302 history task on integrationbf1a920c48e662b02b99b05202b7dfe3e438f8ca
reached the normal two-author/two-photo/three-version setup and distinct acknowledged draft
in both engines. Chromium then failed its exact upload-only storage comparison; report,
memory assets and saved-version receipts stayed unchanged, but the failed controller inventory
was not retained before its assertion. That first cause remains unclassified. One bounded
synthetic actual-caller AppTest did not reproduce an upload-only write; no browser retry occurred.
WebKit passed upload-only, then failed because the helper wrongly called the new photograph's
immutable object and empty object-bucket lock a shared-setting change. Actual profile/standing,
history/version and unrelated report content stayed unchanged. Original artifact12069445575
(22,833,543 bytes, SHA256d4e6e7cb18edbcd73b02e99bce90df9cfbb8819809510d248d5a0aa399798ef9)
is independently retained with full hash and ZIP integrity verified.

The controller now retains bounded hashed per-path size/digest/mtime records as well as all old
group summaries. Explicit Use/No photograph may update only this browser report's working.json
and add only the exact acknowledged photograph recovery link, matching immutable object and its
empty exact bucket lock. Every preexisting file/digest/mtime except that current manifest stays
fixed; unrelated new objects, profiles, history, other journals and altered assets are rejected.
Upload-only/display/reload still require complete equality. A failed stage is recorded BEFORE
its assertions, preserving the next exact first storage difference instead of losing it.
The actual cookie-isolated native AppTest verifies upload/use/display/omission, original asset
retention, unchanged standing/history and a separately populated other namespace; only its uploader
bytes are supplied and its preview renderer is disabled. No production code, native converter,
browser, timeout, rescue or business assertion changed. The exact affected set passed84 checks
in21.10s with zero failures/errors/skips; a read-only peer review found no blocker for this scope.
Exact integrated browser verification,
history inspection/reload tail and all-page/native output acceptance remain open.
Current integration — 2026-10-16 19:20 UTC: published finishing3843873 remains unmerged;
its new history browser task reaches cover actions and has retained first failures. A local normal
merge now adds published PR2490959's narrow virtual-list resize repair and exact fresh response
pins, plus an observation-only compact Water button-binding probe. The source model's conditional
height transition and unknown historical native error owner remain explicit. Main/served proof
remains4ca42c59fe647d4cf1f766bfb2d232092e48f7cf. Exact new integrated/browser gates are required.

Current local integration — 2026-10-16 19:04 UTC: Organization notes repair and bounded first-site
observation are now composed with the normal published PR251d071 merge and the history harness
repair. The exact affected set passed201 checks in62.34s, including all22 new Organization cases
and the unchanged30 first-site actions/predicates. These scopes overlap previous counts. No new
browser run, remote publication, merge to main or served revision is claimed by this local result.
The first-site observation is a diagnostic, not an application fix; original native failures remain.

Organization notes repair, 2026-10-16 19:00 UTC (local follow-up from PR252 b2c, unmerged):
actual native editors reproduced replacement wording being overwritten by an older widget value,
and a cleared notes field disappearing before reentry. The editor now keeps blank notes editable,
uses the existing source/incarnation-bound native commit and explicit recovery rules, and preserves
same-action contact/position/Done work. A separate native Add contact test exposed an early sibling
rerun; delivered notes are now carried before that action without acknowledging a new canonical
version prematurely. Notes-only receipts leave independent contact/chart fields intact; source-linked
wording keeps its evidence editor. Twenty-two new AppTests cover stable IDs, clear/reentry, source/
epoch replacement, stale native callbacks, explicit recovery, same-action Done/Add/contact edits,
selected-site shared-save success/failure/concurrency, report-only rows, and saved-version reopening.
The exact local affected set passed 116 checks in 40.47s, including all 22 new cases; a separate
read-only peer review found no blocker. These are Python 3.12 / Streamlit 1.61.1 AppTests.
First failures remain private under `organization-notes-*-first-failure*.xml`; exact integrated CI,
served browser/native-input and output acceptance are still required. No live standing data,
customer original, local browser, or deployment was used for this implementation.

Current PR252 reconciliation — 2026-10-16 18:56 UTC: retain all source/cover/history changes
from publishedb2c75bd and the focused history harness repair, then normally incorporate published
PR251d0714850581d6c02781e73e6f8395138b5b92d7c, including PR2491649's reviewed dropdown repair.
Main/actually served proof remains4ca42c59fe647d4cf1f766bfb2d232092e48f7cf. This local candidate
is unmerged; exact integrated CI and actual history/cover browser behavior remain required.

The b2c Adaptive38947283726 first-site task passed its initial zero-site keyboard selection;
its later UMMC deselection after adding RGH failed in one WebKit path (nine of ten paths passed).
Native checked state had been observed, but no event/wire/trace record exists for that last action.
The screenshot alone cannot distinguish missed click from stale state overwrite; no checkbox
production repair is justified by that evidence. Both fresh Water engines completed all five
business stages/durable decisions; WebKit's sole native ResizeObserver error began during
September selection before upload. The new parent callback repair was absent from that revision.
Those original failures remain visible; neither this merge nor later green can erase them.

Composed history/cover/Water/native-prerequisite integration:133 passed in39.01s under locked
Python3.12.14. An initial command named an absent test path and collected zero cases; the corrected
actual-path command produced this receipt, not an application failure or a skipped case.

Exact PR2491649 Required38949313065 independently2,828/0/0/0; Adaptive38949313042 failed
only the fresh WebKit native ResizeObserver gate. Both fresh engines completed all five business
stages and every earlier family/full Water/Shared/native-output passed. The original108,297,687-byte
archive12069130703 is retained under its own verified digest. This new failure remains under focused
callback/delivery investigation and is not a browser pass or merge authorization by itself.

### Retained history harness repair and prior source/cover batch

History harness repair 2026-10-16 18:49 UTC: PR252 headb2c75bd passed
Required38947283779 on integrationae0ed8d208adfd525b8e8d7a52be10652a0eb35a;
the original JUnit independently contains3,140 cases with zero failures/errors/skips.
Adaptive38947283726 failed. Its new history job failed in BOTH engines at the initial
cookie-bound empty state, before any fixture/history/cover action or native output. Actual
Actions stderr identifies the first cause: the passive widget diagnostic rejected this new
fixture's localhost8542 socket, then subsequent Route.continue_ calls inherited that exception.
Final retained DOM was connected/notRunning but Buttons/HTML receipts remained skeletons.
The original8,401,191-byte history artifact12066847133 is retained with SHA256
4658ae7d9af557cd952bce62e4cbf7a8dd2802b33f545e018059baddaf6c0c98 and passed ZIP integrity.

The diagnostic now accepts an explicitly supplied fixture port; history opts into only8542,
while existing callers retain their prior ports and all sockets still require127.0.0.1.
The exact retained trace also proves Python None optional predicate keys were omitted by
Playwright. Their checks now accept null or undefined without relaxing supplied scope,
revision, author/activity hashes, photo count, fresh sequence, durable equality or completed
script state.52 focused Python/actual-JavaScript contract checks pass, including both socket
listeners receiving a real protobuf and rejection of wrong ports/host and wrong supplied values.
Original failures remain retained; no browser/server rerun, timeout increase, rescue gesture,
business action, merge or deployment was performed for this repair. New exact integrated browser
verification is required. The separate b2c first-site tail and fresh-Water WebKit browser-error
failures remain open and are not explained or waived by this history harness repair.

Current finishing batch 2026-10-16 18:24 UTC (PR252, still unmerged): resolved source files now
collapse to Included files and pictures with Change; unresolved/stale/ambiguous/retained/CMMS
sources keep their recovery tools. Native captions delivered with Done and same-render reader
completion remain atomic. The actual dated shared-history comparison and report-only Cover
photo browser task are added to a separate15-minute job; the existing25-minute job is retained.
Those new browser paths remain implemented-needs-verification until exact CI runs.

The Cover photograph now has one reachable ordinary report-only Change path, explicit Use/No
photograph, original retention and stale-source/incarnation/cycle guards. Its controls refresh
only AFTER all report fields and recovery commit, preserving same-click Activity text. Explicit
Starting No-photo intent is source/candidate-bound and persists as cover_photo Omit through native
output; a populated current human photo requires a separate report-level decision. Existing
unread/unknown cover art cannot be approved by a new photograph; existing saved-design recovery
and safe foreign exact-source logo exclusions remain narrow. Same-source native DOCX and one-page
LibreOfficeDev26.8alpha diagnostic confirm photo relationships/media are absent while logos and
original source remain. This is synthetic exact-output proof, not approved-master/Word acceptance.

An exact repeat-import exposed a separate logo receipt/default boundary. Automatic preferred-logo
skips retain only verified old exact-source/profile/month/role contributions; current human art
never becomes source receipt content. Normal three-way replay preserves edits, Omit, Clear and
removed logos. Those exact consumed roles also bypass downstream default refill; all mandatory
export checks remain.26 focused/165 affected and222 combined No-photo/replay checks passed on their
recorded revisions. New source/cover/history integration:178 passed,1 local LibreOffice-filter skip
in66.22s;8 native image-observation tests also pass. Scopes overlap, not summed. Original caller,
order-drift, stale-control and invalid-harness observations are retained, not overwritten.

Global release remains merged/live-synthetic4ca42c59fe647d4cf1f766bfb2d232092e48f7cf (PR248 only).
PR249b34 Required38943191284 independently2,809/0/0/0; Adaptive38943191454 FAILED only new fresh
Water WebKit native ResizeObserver error during September selection. BOTH engines completed all
five fresh-task stages to exact one-page durable inclusion; every prior family/full Water/native
clear-reentry/output passed. Overall browser gate remains failed. Original105,020,590-byte archive
and exact first-failure trace are retained. No production data-loss or page-inclusion failure was
shown by that task. PR251 currentc114f95 incorporatesb34 and has fresh Required38944314491 success;
its Adaptive38944314371 still requires independent result/evidence review.

Training currentca4101b separately includes distinct blank-status preservation and a corrected
native-widget reference. Its reference reproduced ResizeObserver errors in BOTH engines with
ZERO workspace/preview observers, matching native input/trigger geometry and one connected
input/pointer/filter/option action; authoritative session/output tails also complete. This proves
custom app observers are not necessary for these occurrences. The locked framework Zt positioner
has synchronous resize/layout writes; a precise callback model and cache-safe pinned import-graph
repair are in progress separately. No global ResizeObserver patch, error filter, timeouts or
dependency change is justified here. Neither Training nor either phase is accepted.

### First-site tail evidence (local, browser verification not run)

PR252b2c first-site had nine successful paths; WebKit's keyboard-labelled path passed its
initial Space selection, then failed the later UMMC deselection after adding RGH. Its retained
capture cannot establish native event delivery, remount, stale overwrite or a ResizeObserver
cause. The same revision's fresh Water WebKit completed all five stages and canonical durable
one-page inclusion; its terminal browser-error gate retained one native ResizeObserver error
during September selection before upload. These remain failed browser gates, not new passes.

The bounded follow-up observes only the existing two-checkbox tail with trusted native events,
same-node identity, script/identity/full-run receipts, exact-port8526 boolean widget delivery and
an optional trace. Every original gesture, predicate and timeout is retained, with no added
intergesture wait or evaluation. Native/Playwright errors are unfiltered; diagnostic cleanup
cannot replace the primary assertion. Eight focused protocol/passivity/cleanup checks pass.
This is evidence infrastructure only, not an application repair or a successful browser rerun.

### Prior branch checkpoints (superseded by current finishing batch)
### Retained workspace reconciliation

Current PR251 reconciliation — 2026-10-16 19:21 UTC: normally merged exact published PR249
head0959bb2484a629b90f4ef1e619ff3df32711a61b into prior workspace headd071485. All contract/site
identity, help, history, administration, source, truthful output-status and native Month-probe
changes remain. The workflow path filters retain the union and the25-minute job is unchanged.
This local candidate has no new integrated CI/browser proof; parent71 source checks and earlier
workspace85 checks retain their own exact revisions. The reconciled workspace/history/admin/
output/source/native-prerequisite/Month-probe/natural-three-asset gate passed97 tests in90.33s
under locked Python3.12.14. All144 workspace application blobs match d071; both trigger lists
are the exact43-path union and the complete job body is byte-identical to both parents. The
publisher, response helpers and virtualizer repair retain exact0959 bytes; its71-case gate was
not redundantly rerun. Current merged/actually served proof remains
4ca42c59fe647d4cf1f766bfb2d232092e48f7cf. Neither phase is accepted.

### Previous PR251 Month activation and workspace evidence

Previous PR251 reconciliation d071 — 2026-10-16 18:45 UTC: incorporated exact published PR249
head1649aeab52ca401f5c9b601518570ba7077a6f80 normally after currentc114f95 and a QA-only Month
activation observation. Main/actually served proof remains4ca42c59fe647d4cf1f766bfb2d232092e48f7cf;
this candidate is unmerged and needs exact Required/Adaptive verification. The client repair and
all original workspace/history/source/save contracts below are preserved.

The c114 Adaptive38944314371 first failure is not erased: Chromium's first September input click
focused the same connected native input under the same idle full-render token, but no popup was
observed; exact option selection timed out. That activation cause remains unresolved. WebKit
completed every fresh page decision and durable one-page inclusion, but a native ResizeObserver
error began during September selection, before upload. Every existing family/full Water export
passed. The separate parent repair addresses a demonstrated native overlay feedback class; it
does not establish the cause of Chromium's missing activation.

The QA-only probe preserves exactly one input click, one exact option click and the value
assertion, adding bounded passive trusted events, aria-expanded mutation oldValue chains and
same-node/render snapshots. No wait, rescue, synthetic event or value write is added. Cleanup
cannot mask the primary failure.14 affected tests passed7.86s; independent read-only peer review
found no blocker. Its extra bounded observation can affect timing, so a later green run alone
cannot explain the original activation failure. No new browser run is claimed here.

Final composed workspace/native-prerequisite/response gate:85 passed in57.10s under locked
Python3.12.14. Exact integrated CI and native browser delivery remain required.

### Earlier PR251 prerequisite reconciliation

PR251 reconciliation 2026-10-16 17:59 UTC: this local normal merge incorporates exact PR249
headb34b172cb3d7dd218e3534d3de26b7258e5a88cb into b5f57e060151e23bbee965bdcad6e9b41cef2e71.
Both ordinary first-site browser checks now assert the exact full site name in the stable
identity strip, where the removed selected-sites prose moved. Their zero-site baseline, one
native selection, month/date/source/page decisions, staging and canonical/durable assertions
remain. The new fresh Water task keeps the existing full prefilled Water/output task intact.
The workflow retains the exact33-path parent union for PR/main events, every earlier journey,
one fresh Water step/artifact and the unchanged25-minute job limit. No history browser task is
added on this branch.119 focused composed Water/identity/history/admin/source/native-prerequisite
tests pass in the locked Python3.12.14 runtime; exact new integration CI is still required.
PR251b5's earlier green Required38937329814 and Adaptive38937329670 are historical evidence,
not verification of this merged candidate. No publication, deployment, browser rerun, live write
or source transfer occurred in this local reconciliation. PR251 stays stacked behind249; after
249 integrates normally, retarget to main and inspect/run its exact workspace-only delta.

### Published parent virtual-list repair and current evidence

Published parent0959bb virtual-list repair batch 2026-10-16 19:07 UTC starts from PR249
`1649aeab52ca401f5c9b601518570ba7077a6f80` (tree07b2f2). Its Required run independently counted
2,828 tests with zero failures/errors/skips. Adaptive38949313042 passed every older family and
both fresh Water business tails, but failed the fresh WebKit terminal native ResizeObserver gate.
The original108,297,687-byte artifact12069130703 passed CRC and independent SHA256
`70d6c490a70815b8639d2b56b943f3caafe1911a6099d544bdb0736353ef811e`.
That trace places the native error at35,128.77ms during Reporting month→September option scrolling,
after virtual-list pointer interceptions. PR25019d Adaptive38950074630 repeats that fresh error at
35,893.265ms in the same month selection. Both reach the five canonical business stages. Their
fresh traces record the expected repaired primary/Tooltip request names but omit JS response
bodies; exact bytes from a different passing Shared context are not fresh-route byte proof.

The same PR250 run's separate native Training date job117138939790 passed on tested integration
`970c5730ef4dba4b03387cd3b7deb03f0f4420c0`. Both original-wheel baselines reproduced the old
announcement; both repaired references and authoritative journeys received the exact reconstructed
primary/Tooltip bytes and completed the full date/minmax/add/reload/remove/output assertions with
no page errors, external requests or native window errors across their captured documents.
All8 real output byte sizes/digests were independently rechecked. Artifact12068246399 is1,327,663
bytes, CRC passed, SHA256 `2d84974d52cd96b47d0bc54ab6a67dc242a945808f3fb2d43816faf0669c637b`.
This scoped job success does not make the overall Adaptive run green: its full Water compact
preview timeout is a separate current failure under investigation. No all-page visual, physical,
assistive-audio or Microsoft Word acceptance is claimed.

The original Zt position repair remains. A distinct unpatched owner, the actual locked Cr
virtualizer callback, synchronously flushes visible-rectangle/size changes and may flush a second
dimension correction inside native resize delivery. An actual Cr/xr/X/Z/Q source model reproduces
that feedback class using trace widths468→648, content height480 and max-height418. Its assumed
React commit changes the root height480→418; that browser client-height transition was not directly
measured, so the model does not establish the captured error's sole origin. The new narrow repair
queues only this Cr resize owner through one frame, reuses its existing latest-render callback,
and cancels/invalidates pending work at cleanup. Initial, normal scroll and window-resize paths,
resulting geometry and thrown errors remain. Both window-scroll modes, active unchanged delivery,
frame ID0, coalescing, finite correction and late/disposed work pass the source model.

The unchanged static81-source hash/edge manifest now composes both narrow resize repairs with
the existing scheduler and optional scalar-date repair. Both prior overlay generations retain
their exact identities and complete-graph validation before upgrade; all four old/requested date
combinations preserve the correct scalar state. Old/current corruption, no-write failure and
interrupted upgrade/retry checks pass (29 focused publisher checks). Fresh Water now verifies
the naturally requested primary, Tooltip AND repaired virtualizer response bodies against exact
reconstructed pins before its later target month switch. It rejects a fully valid old unpatched
virtualizer configuration and preserves the first bad response. No eager request, added gesture,
browser error filter, dependency change or global ResizeObserver wrapper is introduced. Eleven
focused model/response checks and nine unchanged fresh-task contracts pass. The final composed
publisher/legacy/lock/upgrade/SCC/resize/response/fresh-contract gate passed71 checks in388.18s
on locked Python3.12.14. Compilation, diff checks and independent source review pass. Exact
integrated browser verification is still required; current main/served proof remains4ca.

### Prior overlay-only implementation checkpoint

Current overlay repair batch 2026-10-16 18:33 UTC is based on PR249 head
`b34b172cb3d7dd218e3534d3de26b7258e5a88cb`; main and actually served proof remain
`4ca42c59fe647d4cf1f766bfb2d232092e48f7cf`. This is an implemented-needs-browser-verification
candidate, not a native-error resolution or a release.

PR249 b34 Adaptive38943191454 completed both fresh Water business tasks, then failed on a WebKit
native ResizeObserver error; no Training form was used. PR250 ca4101b Adaptive38945377473 tested
integration `dd04f9125561f2feedcd78bf16708f7de65c6f2a` against b34. Its corrected native Training
reference matched the actual input width and selected the participant on the same connected field
in both engines, without custom workspace/preview observers; both reference documents still
reported the native ResizeObserver error. Tooltip callbacks immediately preceded those errors
(Chromium3190.4/3190.5ms before3193.2ms; WebKit3038ms before3042ms). Constructor origins also serve
the framework Virtualizer, so those records alone do not identify one callback or prove every
historical native error has the same cause. The authoritative Training task independently completed
date/minmax/add/reload/remove and all8 real output checks in each engine. Chromium's native error
remained terminal; WebKit had none in that run. Business completion is separate from acceptance.
The original Training artifact12065197641 is retained with verified size1,379,230bytes, CRC and
SHA256 `f2ce4f9d38fe91664ae9e4649bf3c4d680d843f3e342a8bf0fc9b30dfa7b7d03`.

The actual locked Tooltip Zt/Xt positioner model reproduces synchronous layout writes inside its
two ResizeObserver callbacks: a finite target resize changes the observed overlay's maximum height
from73px to51px during delivery. The narrow repair coalesces only those two position callbacks
onto one animation frame and cancels pending work on lifecycle cleanup. Original position math,
initial/window/scroll positioning and thrown errors remain. Actual extracted source tests cover
both flip choices, frame ID0, duplicate delivery, exact resulting geometry, cancellation and late
delivery. A controlled DOM model is not a browser ResizeObserver timing proof. Other observer
implementations, including the Virtualizer, are unchanged; no native error is suppressed.

Publication now reconstructs an immutable81-JavaScript import closure from a static full-hash and
edge manifest (7,439,383 original bytes), preserving originals and its five-member import cycle.
One generation identifies the closed configuration; the primary entry retains a hash of its final
bytes. All generated bodies and edges validate before HTML changes. Scalar-date and full-editor
scheduler repairs compose with this overlay repair without new dependencies or copied fonts.
Shared browser QA compares naturally requested primary and Tooltip response bytes with an
independently reconstructed, fully validated publication, rather than trusting served filenames
or self-reported hashes. No eager browser loading of the whole closure is added.35 focused checks
passed before an independent review then reproduced a concurrent nondate/scalar installer HTML
lease race on a disposable bundle; that first failure is retained. A lock on the existing static
directory now spans validation and fresh scalar-state reading through final HTML replacement,
creating no lockfile.13 focused checks passed, including actual two-process installations in both
flag orderings, blocked validation while the other installer holds the lock, preserved scalar
compatibility, invalid-input no-writes and interrupted publication. The final composed model,
publication and requested-response gate passed37 checks in92.82s; independent lock/interruption
review passed5 checks. Exact integrated Required/Adaptive, corrected native reference and fresh
Water browser evidence are still required.

A second independent review reproduced a QA expected-byte race after full pinned validation:
the helper could reread a same-length changed file and adopt it as its expected response. Both
primary and Tooltip helpers now compare that reread with the independently reconstructed SHA256
before returning it. Four focused response checks pass, including both post-validation mutation
regressions; the original failure receipt is retained. This observation repair does not change
published client payloads or establish a browser pass.

### Prior verification checkpoint (superseded by current overlay batch)

Current verification batch 2026-10-16 17:55 UTC: PR249 head98111bb passed Required38940688734
and Adaptive38940688764 on integration6ae137951dd8dfc1cbd16af73ecbe8c28ad3ae12 against main4ca.
Its17 new Water regressions repair two independently reproduced recovery cases; the full prefilled
Water browser task remains intact. Required artifacts independently recount2,796 tests with zero failures/errors/skips.
Adaptive original86,757,831-byte ZIP is retained under its own verified digest; full task review
remains scoped to that exact revision.

The next exact candidate adds a separate ordinary native browser task for the freshly empty Omit
case: one zero-site action, October template bootstrap, then unsaved September with no snapshot,
real two-page PDF upload, first-page approval without premature inclusion, explicit second-page
exclusion, and exactly one durable canonical page. The October bootstrap itself correctly starts
Water as This month; it is not the empty-Omit prerequisite. The guarded disposable server has no
live-root fallback or outgoing services. This task is browser-unrun until the new exact CI;
it does not replace the existing caption/order/omission/compact-preview/generation/output journey.
31 affected checks pass locally; independent helper review is clean. Four helper contracts
also retain missing-prerequisite, anti-no-op and replaced-input-node rejection.

The same batch repairs a demonstrated native-text QA prerequisite from PR252 Adaptive38938669161:
the issue clear was attempted while its controlled DOM value was briefly empty after reload, so
the anti-no-op assertion correctly stopped before any clear. The canonical/durable issue remained
populated and later captured DOM matched it. Awaiting the exact expected existing value on the
same locator now precedes the action. Anti-no-op, actual input-event-node continuity, durable
acknowledgment, clear/reentry/reload and actual output assertions remain. No rescue gesture,
synthetic blur, business retry, timeout increase or application-state injection is added.

Earlier Water review recovery findings reproduced five actual-caller failures despite the
prefilled journey passing. Empty optional Omit slots now accept explicitly reviewed pages;
omitted wording, tables/custom schemas, captions, graphics and other writer content retain a
separate whole-section choice, including when no source files are routed.17 new and71 affected
cases passed locally. Stale source/reset/price/image/zero/NR/qualified guards remain. The original
failures and two identified intermediate test-prerequisite mistakes are preserved.

Merged main4ca42c59fe647d4cf1f766bfb2d232092e48f7cf independently passed Tests38936148403
(2,711/0/0/0), Adaptive38936148447 and automatic live38937063007. Both independent live sessions
observed that FULL served SHA and completed3 first-attempt requested/accepted/completed generations
each, with12 actual files' sizes/digests verified across the sessions. Live Prepared pointer/
keyboard passed6 checks. No Render workspace selection or owner conflict change occurred. This
is exact synthetic release proof for PR248 only, not owner AUTH, native master or phase acceptance.

PR250 now87aebb9 retains single-date/native keyboard/partial/minmax/session/output assertions;
its prior3c run stopped at an unnecessary one-second frame prerequisite on an EMPTY initial date,
before repaired paths. Actual40-case vendor model proves empty0..0 cannot be changed by its queued
cursor0, so only nonempty replacements need the unchanged frame barrier.60 targeted checks pass;
new exact browser verification remains required. Priorace WebKit full tail and54 individually
reviewed PDF pages stay scoped; earlier Chromium filter-only and ResizeObserver causes remain
unclassified. PR251b5f57e0 exact Required38937329814 and Adaptive38937329670 passed; it remains
unmerged. PR25257b6eee contains deliberate external reading, scoped Issue Evidence/Undo, quiet
Scorecards and strengthened real DOCX page-order/caption checks, still unmerged behind PR251.

The current follow-up also strengthens Water DOCX output assertions: actual embedded relationship
occurrence/order and adjacent per-page caption hashes must match the ordered working receipt.
Both retained c3eb outputs pass; swapping their real image relationships passes the older media-set
check but is now rejected.23 targeted cases pass. This verifies native package identity/order,
not independent Word pagination, PDF image order, all-page legibility or graphic/privacy acceptance.

### Prior integration checkpoint (superseded by current repair above)

Updated 2026-10-16 17:07 UTC. PR248 is merged normally into main
`4ca42c59fe647d4cf1f766bfb2d232092e48f7cf`, with reviewed parent head
`ceaba0a20115608a9e93d4b74ad2ece96cbe2dce`. Exact pre-merge integration
`f3335240573a89e05f9904a24ceb291de1f98528` passed Required38934057257:
2,711 tests, zero failures/errors/skips, independently recounted. Adaptive38934056915
passed every workflow family, including native Prepared-by and Shared clear/re-entry/reload.
Both engines verified the actual primary response bytes against the pinned client repair.
Merged-head CI and normal auto-deployment/live verification remain separate and pending.
The last independently observed served full SHA remains historical PR247
`0dca61194d1769d7871ba46d222289dadef0e8d1`.

The locked client defect is now reproduced through its actual protobuf decoder and widget
caller chain: a full editor has fragmentId `""`, as well as undefined. The earlier scheduler
repair covered only undefined, so Shared failed again in38930995952. Current code normalizes
only that known empty-string full scope and retains full-request priority across deferred
preview batching. Original/intermediate failures remain retained; no browser error is ignored.

PR249 head `9b1c350e100cf309125c7c23eebd612705fd09dd` is reconciled onto main at
`4ca42c59fe647d4cf1f766bfb2d232092e48f7cf` and retargeted to main. Its merge parents are
c3eb2eb and4ca42c5; every Water and parent workflow trigger is retained. The prior exact
c3eb2eb run Required38927678105 passed
2,738 tests; Adaptive38927678096 failed Shared, but BOTH Water engines completed real browser
PDF upload, page review/caption/order/omit/repeat/reload/reinclude, a visible compact Current
preview, generation and actual DOCX/PDF downloads. Working and durable receipts agreed on
page order [2,1], retained original hash/size and included image/caption order. These are synthetic
journey results, not owner AUTH, manual all-page/native Word or physical-device acceptance.
Fresh exact integration gates are required before this PR merges to main.

PR250 Training head ace1d3b includes the corrected parent. Its earlier Chromium path completed
add/reload and downloaded actual files; the PDF checker now accepts normal whitespace wrapping
while preserving exact words/date/person/row/inclusion assertions. The native mask's deferred
focus frame is observed before one keyboard replacement. WebKit's separate ResizeObserver error
remains terminal and unclassified; a bounded native diagnostic records its owner/delivery without
suppressing errors. Adaptive38935820687 on checkout bf14e623 failed Chromium at the participant
option before its date/session/output tail; browser errors and external requests were empty.
That same run's WebKit path reached session add/reload/removal and two accepted/completed
DOCX/PDF generations. This later error-free WebKit run does not explain the older ResizeObserver
failure. Complete two-engine Training acceptance remains open; Required38935820543 is not
independently re-read in this merge task.

PR251's prior head `fc157f0b333814512a4ca9fb7f9fc4514837d1c2` passed Required38934310568:
2,891 tests, zero failures/errors/skips, independently recounted. Adaptive38934310637 and all its
workflow steps passed on exact integration `b63d5d7846ab35ee05e43e2a5304dcfe21232148` against
base c3eb2eb. Its exact Adaptive archive was not newly downloaded/reviewed for this merge.
Those gates are historical evidence for that revision, not the new candidate. The current local
merge reconciles fc157f0 with PR249 head9b1c350 and requires fresh exact Required/Adaptive before
integration. PR251 remains a separate unmerged identity/history/admin/source/editor follow-up.
Every PR251 implementation detail and the recovered full-JUnit correction below is retained.
No new deployment or served revision is established by this local merge.

Local merge verification used locked Python3.12.14:181 focused frontend/identity/history/admin/
output/source/Water tests passed with zero failures/errors/skips. The workflow union retains all
30 path triggers for both pull requests and main pushes, plus every existing workflow family.
All application/test/workflow blobs are unchanged from fc157f0; only this ledger differs. The
local receipt is retained privately as pr251-parent-merge-focused.xml. This is scoped local
verification, not the new exact integration CI or merged/live acceptance.

An unpublished Shared report history browser task starts from published PR251b5f57e0.
It uses the existing marked fixture and actual browser cookie, normal known-value load,
photo upload and explicit Save shared version actions. The new separate15-minute CI job
keeps the existing25-minute adaptive job byte-identical. It checks real dated/author/version
grid rows, read-only wording/picture comparison, unchanged working/durable drafts, memory
assets and fresh monthly_reports history/asset/standing/journal byte+mtime inventories across
open/close/resize/reload, plus an empty second-cookie namespace. No live route, generation,
owner recovery choice or expected-value report injection is used.
The browser path is implemented-needs-verification; it has not run locally or in CI yet.
46 affected local checks passed. Independent review reproduced a linked durable-root escape
in the new test observer; its original failing receipt is retained. Both observer entry paths
now reject that root before library reads, and the final10 observer/acknowledgment tests pass.
These are test-harness checks, not browser, authentic-source or native-output acceptance.

### Superseded implementation checkpoints (history)

Main and the last independently verified served revision remain
`0dca61194d1769d7871ba46d222289dadef0e8d1` (PR247). Its terminal evidence is
https://github.com/evanroden/msapo-generator/pull/247#issuecomment-6196963277 .
No new main merge, Render workspace selection or served revision is claimed here.

PR248 is open, current parent `ceaba0a20115608a9e93d4b74ad2ece96cbe2dce`.
Previous exact5e275b Required38929196560 passed2,691 tests (zero failures/errors/skips)
and Adaptive38929196540 passed. Its final review repairs preserve omitted human corrections
through source deselect/reselect and refuse changed footer replacements over independent address
corrections. The current parent additionally repairs a reproduced locked Streamlit1.61.1 widget
batcher: a full request could lose full-editor scope to a queued preview fragment. Actual locked
method regressions failed4/8 before repair; all8 pass after it. Independent363-sequence review had
296 wrong-scope outcomes before repair and zero after, with timer/send/trigger/resolver invariants.
The earlier ecd0d45 passed Required38930996061 (independently2,704/0/0/0) but
Adaptive38930995952 failed Shared again. Actual protobuf/caller-chain review found full widgets
also pass empty-string scope, not just undefined; the first model missed that valid domain.
The current publisher normalizes only that full-scope empty string before priority selection.
Actual decoded-protobuf→widget→scheduler regression reproduced the gap; independent1,364
mixed-scope sequences now preserve full scope with timer/trigger/resolver invariants. The next
Shared journey verifies the actual primary client response bytes/SHA once, not its filename only.
44 affected and13 date composition checks pass; the exact new browser gate is still required.
The exact-version/hash publisher retains immutable assets and selects content-named client entries;
optional Training date compatibility composes with it.28 targeted,12 existing date and33 lifecycle/
geometry checks pass locally. New exact Required/Adaptive are required; old green runs do not
verify the current publisher or every historical input/image failure.

PR249 remains open, stacked on248, currentheadc3eb2eb7150961eb7c481e153dacc05b5a68816f.
Required38927678105 independently passed2,738 tests (zero failures/errors/skips), including13Water
omission and7QA image-generation cases. Adaptive38927678096 failed Shared WebKit Ctrl+Enter clear,
but its Water journey passed BOTH engines through normal upload/review/caption/order/omission,
unchanged repeat, reload/reinclude, actually visible compact Current preview and actual DOCX/PDF.
Each engine retains its own exact3,500-byte original; finalworking==durable, order[2,1], both intended
image payloads and onecaption were independently checked in outputs. Each PDF has28pages. This is
synthetic CI output proof, not genuine source, all-page visual, physical mobile or Microsoft Word
acceptance. The earlier missing-root/offscreen waits were wrong harness prerequisites, and the
QA toolbar's missing asset resolver was repaired with generation/namespace-bound source resolution.

The Shared failure in that samec3eb run is specific: manualedit/Tab/reload passed; later trusted
Delete/Control/Enter on one connected textarea carried the exactempty value ONLY in a preview
fragment; no full editor request followed. Browsererrors/externals were empty. A passingd9ab run
sent a distinct full request after its earlierfragment; that did not prove the race eliminated.
The current parent scheduler repair addresses this demonstrated scope class, pending browser CI.
Originalartifact12057293872 is retained privately with fullhash/size, separate from the selected
font-free derivative and from priorfailed artifacts.

PR250 is the separate Training follow-up stacked on249, published62e85f5. Requirements/sessions,
explicitdate/unknownhours/status/removal and cache-safe scalar-date compatibility are implemented.
Actual browsers reproduce the old second-date announcement and verify repaired typed/calendar/
keyboard one-date behavior, native accessibleClear, missingdate and partialsubmission preservation.
The b599 composed test now passes exact out-of-month rejection and durable session add/reload
in Chromium, then stops at a PDF text match: the complete title is visibly wrapped in its actual
native table, so matching is corrected to exact words with normalized whitespace. WebKit's
queued focus/mouse frame resets a later select-all before Backspace; actual vendor handlers
reproduce that sequence. Read-only focus completion before the single replacement is implemented
and awaits browser proof. The separate ResizeObserver error remains terminal while its origin
is investigated. No application date-clamping defect or complete Training tail is established.
OriginalTraining failures remain retained, including earlierWebKitResizeObserver error without a
blanket exception. Native session/export tail and physical/assistive audio remain open.

PR251 is the separate workspace cleanup stacked on249. This candidate incorporates current248
and249 source repairs and implements one identity/month/sites strip, scoped More report details,
Help, real read-only dated/author/sharedhistory, Reportactions, About diagnostics, and separate
administration routes. Site row/native checkbox identity and report attribution/privacy remain.
The first-company-master fallback and stale-master-install races are repaired without migrating
saved designs: existing built-in/master/import pins remain stable, and a new master requires an
explicit current version-base choice. Originalfiles/uploadwidgets remain intact.

The detailed source batch keeps exact accepted content/source snapshots while another selection
is staged; failed preparation preserves priorcontent. Pending changes retire oldoutputs and block
generation until explicit successful Add/removal. Review also repaired comparison-image pagination,
source/facts approvals and latewording replacement, including same-event pending humantext. RFI
empty-grid entry, section labels/scopes, retained omittedMBCx notes and omitted-picture captions
are consolidated without changing exported house headings or restoring excludedartwork.

Finished files now retain actual sharedsave status across rerenders, name the savedversion and
provide separate save/PDF retries. PDFretry converts the exact priorDOCX under existing foreground
resource bounds without assembly/sharedsave. Retry actions bind fullfile/draftidentity, report
incarnation and revision; stale/same-event/reset/conflict regressions pass. Original two output-
status failures and later stale-retry findings are retained.60 combined output/history/source/
admin/MBCx cases and59 focused workspace cases passed locally; these are stated scopes, not a
complete application gate. The full local JUnit was subsequently recovered:2,816 cases,
four failures,47 skips,zero errors in486.102s. Its console stopped at2,219 positions, but the XML
contains everycase; the suite completed. Three stale label expectations were reproduced and
corrected with business assertions intact. The fourth cross-process quarantine case reproduced
this managed runtime's Python PID versus /proc namespace mismatch, in components byte-identical
to main0dca. No production patch, skip or sandbox change was made. Currentparent Required CI
independently passed2,704 cases including all13 native lifecycle tests. PR251d6cc Required then
ran2,884 cases:2,883 passed; only the retained PO quick-path test's stale two-expander expectation
failed against the new quiet About disclosure. Its real-render/output assertions stay intact.
The exact failure archive/JUnit remains retained. No full local pass is claimed.

Unfinished implementation remains below: broader evidence/source-card consolidation, spreadsheet
and conditional artwork/recovery branches require actual task comparison and verification, and
some section-specific simplification remains. Do not relabel these as owner sign-off. Nothing in
these feature PRs is merged, newly served or a completion claim for either phase.

### Scorecards intake follow-up — 2026-10-16 16:39 UTC

Separate candidate based on PR251 `d6cc858f8bbd89b89fb2d13bb42a6f6fef2ee887`;
implemented, needs exact integrated/browser verification. Synthetic AppTest reproduced the
duplicate Utility analysis heading/field, primary upload beside already populated report-only
capacity, and an external reading started by upload alone. The native Utility analysis field
remains authoritative with its existing key; its duplicate markdown is removed. Populated
report-only capacity keeps its editable table and literal zero/NR/qualified values and units;
its uploader now lives in collapsed Add capacity for future reports with the actual reuse scope.
Missing capacity still offers primary upload. Existing saved-capacity replacement stays in
Edit or replace shared capacity; no display/open/reopen promotes report values to standing data.

Free inspection and source-bound cached results remain available on upload. A needed external
reading now requires Read capacity file beside the external/cost disclosure. Upload/display/
reopen reserve no allowance and call no provider. Delayed actions bind the displayed source bytes,
filename/fingerprint, profile/month, editor incarnation/QA generation and shared revision. Pending
reads start once; error retry remains deliberate. Replacement/clear/reset rejects late results
before cache publication; isolated testing refuses external reading before preparation. A valid
reading survives a failed reuse-cache write without another paid request. Existing reader result
validation, source-page bounds, first-fill, schema conflict, optimistic shared save and manual-
report override rules remain. The explicit standing-data Apply action also binds its displayed
source/result and base: an independently reproduced old-source approval could otherwise publish
a newly staged cached source. Human cell corrections delivered with the same click still save
through the existing current-tables/mode/actor validator without an extra click.

First failures are retained separately: five initial UI/automatic-reading cases, the stale
standing-data approval, and the failed-cache recovery. An overbound approval ID was caught before
publication and corrected to preserve ordinary same-event cell correction plus Apply. Final
affected Python3.12.14/AppTest/model suite: 135 passed, zero failures/errors/skips; two existing
synthetic sheet-title warnings.
Independent read-only review passed 66 before the last cache ordering repair and both final
cache/approval regressions afterward. All external readers/allowance calls were stubs, never
paid requests. These are source/AppTest proofs, not browser screenshots, real owner Scorecard
mapping, genuine import, native visual output, merged-head CI or a served release.

### Evidence and deliberate reading follow-up — 2026-10-16 17:10 UTC

The separate candidate on PR251 combines Equipment Issues into one optional Evidence disclosure,
with native source/update/status fields and separate section-level photos/pages kept reachable.
Bulk Clear is secondary under Issue actions and changes inclusion only. Revision/incarnation plus
rotating native action-cycle guards prevent stale Clear/Undo from binding to a later identical
report. Clear applies after all delivered section edits; Undo refuses intervening edits anywhere
in the draft. Original wording, statuses, sources, assets, history and standing records remain.
First stale-action failures are retained; final96 affected checks and43 combined checks passed.

Actual guided Activity intake reproduced one external worker/allowance reservation from upload
alone. Activity/Capital/Proposals now retain free native extraction and validated cache reuse,
while one disclosed Read selected files action binds exact selected sources, profile/month,
report incarnation, QA generation, shared revision and native attempt token. Late/stale requests
cannot spend or replace current edits; completed readings survive reuse-cache failure without
another paid request. Pending suggestions keep explicit source-bound approval. The affected
111-case suite passed with zero failures/errors/skips; no actual paid reader was called in QA.
These changes need exact integrated/browser verification and are not merged or live merely by
publication. The separate source-manager observation below was reproduced against that earlier
candidate; its bounded resolution is implemented locally and still requires integrated gates.

### Resolved source disclosure follow-up — 2026-10-16 17:33 UTC

Actual guided synthetic utility-file review and atomic Add reproduced a fully included image
source left open with repeated Include/Add controls. Local `c82e4ae` (integrated as `f72b99c`)
now closes that exact successful Add to Included files and pictures with one Change route.
Unresolved sources get one review card and the original source/page/reuse/remove/metadata tools.
Only current, unambiguous, reviewed image attachments with valid source scope resolve; missing,
priced, stale, omitted, deliberately removed, reference-only, text and CMMS sources remain open.
This is a disclosure decision, not a replacement for existing export or source-review checks.

Native regressions also preserved captions delivered with Done, including a separate reader
finishing earlier in the same render; inherited absent captions follow actual attached captions
without a display write. Failed Add retains its error and recovery controls. Original bytes,
standing records and history are unchanged by open/close. Initial failures remain retained.
The new47 targeted and188 affected local checks passed; exact local integration `d3810e6` passed
151 combined source/gallery/issue/Scorecard/native-package checks. Independent read-only review
found no lost current code or new blocker. Browser geometry, genuine source/master, native visual,
exact final CI, merge and served acceptance remain separate; broad source unification is unfinished.

Local integration then retained published PR252 `57b6eee`, reconciled Water prerequisite
`98111bb` through merge `fc6d61d`, and added the separate history harness as `90502b3`.
The Water/shared-source union passed159 affected local checks in97.30 seconds. The history job
adds only its three trigger paths and separate15-minute job; removing those additions reproduces
the original workflow exactly, including the unchanged25-minute synthetic job. Final code
`39da8f4` passed109 local history/observer, QA isolation/image, retained Water and native source/
gallery checks in68.52 seconds. The subsequent result update changes this ledger only. Independent
union review found no lost Water, caption, scoped reading, history guard or workflow code.
The new history browser task and exact CI remain unrun here; no code was published, merged to
main or observed served by this local integration.

### Failures that must remain visible

* Conditional cover gallery follow-up (2026-10-16 17:22 UTC), based on `be6cb02`:
  actual synthetic same-site DOCX inspection with an unread VML drawing reproduced two independent
  photo galleries. Selecting No cover photograph in the first was immediately reversed by the
  lower unresolved-art card. The dedicated gallery now remains the only photo-selection owner;
  the recovery card retains that exact choice without a second gallery, including after edit,
  close/reopen and later Contents artwork. Unknown-art recovery and Continue blocking remain.
  Source image selection does not grant client-export review, and No cover photograph stays valid
  when no unread art blocks import. Original bytes and standing records stay unchanged on display.
  Two original failures are retained; 49 focused source/AppTest checks pass. This is not browser
  geometry, genuine cover/master or native visual acceptance. A separately reproduced existing
  defect was separately reproduced: an ordinary New cover photograph upload could mark unrelated
  unread cover art preserved. The next checkpoint repairs that bounded safety/recovery path.

* Conditional cover-art recovery follow-up (2026-10-16 17:51 UTC), based on `867fed5`:
  four actual-source/AppTest negatives reproduced optional-photo approval of unrelated VML,
  fresh-cover omission still allowing the unread DOCX to become its native design, silent omission
  of small unassigned cover artwork, and promotion of a later Contents image when the earliest
  cover contained only small art. A separate repeated-choice check reproduced an omitted source
  photo still appearing in the transient preview. These failures remain in their first receipts.
  New cover photograph now changes only that photograph and cannot certify another drawing.
  Unread/unassigned cover art has source-specific original-Word repair/re-upload guidance; up to
  four actual unknown rasters display within a bounded recovery card. A saved report offers
  Use this report’s cover design with explicit scope: keep its current pin, logos, photo and
  footer; add none of this upload’s cover content, retain the unchanged original. The decision
  stays reversible; its gallery and proposed preview cannot republish the excluded source photo.
  Fresh reports cannot use a cover-contribution omission to certify their raw uploaded design.
  Different-site source exclusion remains valid only for exact-source automatic analysis and
  recognized-logo-only contribution; foreign facts/photos/drawings stay excluded and any newly
  included logo still requires client-image review. A fresh foreign source with zero active Cover
  contribution is also blocked when its native cover artwork is unread. No generic boolean,
  unrelated photo, stale source receipt or changed source can waive these gates. Fixed recognized
  logos and later Contents handling remain distinct. No standing/display write or canonical
  artwork/master installation is introduced. The two older photo-as-drawing completion assertions
  are corrected to the user’s safety contract; real Proposals replacement/save assertions remain.
  Exact locked Python3.12.14 / Streamlit1.61.1: 204 affected checks passed, including 19 new cases.
  Peer held-old-Continue/new-source delivery also preserved the draft/profile/pin and published no
  new original. Evidence is source/AppTest scope only: no new browser, genuine source/master,
  native-output visual/privacy, Microsoft Word or physical-device acceptance. Ordinary cover-photo
  editing has a separately assigned reachable-control follow-up; no unimplemented destination is
  promised here. Gallery No cover photograph native-output omission was still unverified at that checkpoint; the next checkpoint records its exact reproduction and repair.

* Explicit No cover photograph native-output repair (2026-10-16 18:15 UTC), based on
  `15f7481`: normal gallery action and import save left no photo block, while the raw uploaded
  native design still included that exact source photo in visible DOCX relationships and package
  media. The same invented 38,600-byte DOCX was reused before/after; source SHA and original bytes
  match. Explicit report Omit removed it; a current replacement preserved the header logo.
  No-photo now records a deliberate exact-source/candidate-bound intent, not absence, default
  uncertainty or an empty gallery. Its mapped cover_photo Omit survives imported_draft narrowly
  for that slot and prevents raw-source art from returning. Source originals/design pins and
  known logos remain. Whole-cover/current-design or foreign-source exclusion never becomes a
  report-photo Clear. New omission cannot delete populated human or even prior-equal source
  photos: a named ordinary report No cover photograph action is required first. Already omitted
  photos keep retained hashes for recovery; genuinely cleared photos remain blank; a verified
  unchanged source omission preserves a later manual photo. A retained new upload stays excluded
  until explicitly used with its exact image digest; a stale choice cannot approve changed bytes
  or waive source pricing/art gates. Native callback delivery makes gallery choices immediately
  reversible without a second event; preview keeps current independent photos truthful.
  Exact locked Python3.12.14 / Streamlit1.61.1: 224 affected checks passed, including 20 new cases.
  Actual repaired DOCX has no omitted-photo relationship or media. Its single-page PDF was
  inspected using LibreOfficeDev26.8.0.0.alpha0 (build2c87e51e…), preserving logo/title/activity
  while omitting the photo. These are invented internal-layout outputs below final report
  preflight, not accepted full generation, genuine master/cover, Microsoft Word or physical QA.
  Same-byte reimport exposed a separate existing preferred-logo source-receipt omission blocker;
  the following local follow-up repairs and tests that exact-source boundary before integration.
  First native bytes/renders and first model/control failures remain retained. A caption probe
  initially used the protocol name imgs instead of Streamlit’s typed AppTest image/captions API;
  that was corrected as an observation error without changing the image assertion.
  Correction to the earlier cover-only experiment: existing reports legitimately accept an empty
  source contribution. Exact15f AppTest now proves Cover-only current-design recovery keeps the
  draft/original; the earlier minimum-section error was an interaction symptom repaired with the
  gallery ownership path, not a reason to require source Activity content.

* Preferred-logo same-byte replay follow-up (2026-10-16 18:20 UTC), local code `a4a1e62`
  based on `15f7481`: the actual No-photo gallery/save/fresh-AppTest/reimport path rejected a
  recognized header logo because automatic use of the saved logo looked like explicit source
  deselection. Automatic setup now records only its exact recognized image-role skips. A verified
  prior contribution for the same bytes/profile/month/role remains consumed, while ordinary
  three-way replay preserves current human replacement, Omit, Clear or removal. It copies the
  prior source contribution, never the current standing/human block, and preserves receipt order.
  Missing/unverified/changed-source receipts, wrong scope/role, manual review and explicit
  deselection retain conservative recovery. Peer review then reproduced two actual caller
  failures: saved-logo/default-branding fallback refilled cleared/removed report slots after
  replay. Only these verified consumed roles now bypass those fallbacks; ordinary defaults and
  required output checks are unchanged. Display/review choice writes no manifest, and repeat
  import leaves standing versions, branding, snapshot history, originals and source contribution
  separate from current human content. First failures and the intermediate receipt-order failure
  remain retained. Exact locked Python3.12.14 / Streamlit1.61.1: 165 affected checks passed before
  integration; 26 new cases passed after the final independent-source-receipt assertion. Combined
  local head `368f2a16e543981dae49781c55d7d5f304ebe7df` includes No-photo `560d121` with
  222 affected checks passing in30.04s, including the actual fresh-session replay and ownership
  negatives. These are source/AppTest checks, not a new browser run, full generation/native visual,
  genuine import, merged/main CI or served-revision acceptance. Publication/integrated gates remain.

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
| PR248/249 integration | PR248 merged after exact green gates; PR249 head9b1c350 now based on main | Verify merged-head and served parent independently; run exact PR249 integration gates before merge. PR251's local merge of9b1c350 into fc157f0 also needs fresh exact Required/Adaptive. |
| One Water/source-page workspace | Both-engine synthetic browser/output tail verified on c3eb2eb; new integration pending | Preserve desktop/narrow upload, review/caption/order/omit/reinclude, unchanged repeat, durable reload, visible Current preview and DOCX/PDF assertions. Actual-source, all-page manual/native Word and physical-device acceptance remain open. |
| Identity/help/navigation | Implemented in unmerged PR251; historical fc157f0/b63 integrated browser gate passed | One stable contract/sites/month strip and useful Change path; combined quiet Help; one Prepared by with actual focus links; More report details for aliases/group/region; meaningful workflow-preserving deep links only. Reverify the newly merged candidate. |
| Saving/history/recovery | History/status/retries implemented in PR251; historical integrated gate passed, conflict tails still scoped | One truthful status; actual history rows or correctly named checkpoint action; report actions for confirmed scoped discard. Preserve conflict choices, both versions, unsent versus acknowledged edits, original/history/standing scope. |
| Training | Implemented in separatePR250; partial actual browser proof, complete two-engine journey open | Separate standing staff requirements from monthly sessions. Retain statuses, unknown hours, explicit deletion, same-name/course identity, rollover/history and stable input incarnation. Preserve the observed scalar-date repair and exact date/session/output assertions; diagnose Chromium's participant prerequisite separately. |
| Section/editor cleanup | Browser-observed, partly conditional | Remove duplicate headings/prose, not functions. Keep one canonical Activity editor, optional grounded writing help, evidence/price gates, CMMS coverage, scoped organization/contact editors, correct ENFRA onsite versus vendor distinction, issue recovery, proposals and RFI meaning. |
| Scorecards/thermal intake | Implemented in separate follow-up; 135 affected checks pass; browser/actual-source mapping open | Verify one Utility analysis field, report-only versus shared capacity scope, primary missing-data intake and secondary replacement, deliberate source-bound external Read/retry, current-only standing approval and zero display-driven writes. |
| Administration/design controls | Implemented in PR251 with scoped pin/concurrency regressions; specific expanded paths remain | Move storage, bulk directory and master administration out of ordinary reporting without changing permissions. Keep pins/history and explicit shared-write scope. Raw hashes belong in diagnostics. |
| Imported cover/artwork/conflicts | Gallery and bounded cover-art recovery implemented in synthetic source/AppTest scope; broader conditional/native acceptance open | Reproduce duplicate galleries/action gates before deleting them. Preserve original graphics, bounded recovery/retry, explicit uncertainty, scope/date correction and optimistic concurrency. No silent art drop or hidden shared save. |
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

<!-- END_ENFRA_LEDGER_ARCHIVE narrative-through-ordered-table -->

### Superseded restart wording — from94116f8

Verbatim 681-byte source segment; SHA256 `9b035ce9a60a00731422aa5217e0e1448325a4c9acb8e8db2493453bde201831`.

<!-- ENFRA_LEDGER_ARCHIVE source=94116f87d298b92149b13014bfc20f39ac9e131e segment=old-restart sha256=9b035ce9a60a00731422aa5217e0e1448325a4c9acb8e8db2493453bde201831 -->
## Restart and release rule

Refresh main, both PR heads and exact workflow results first. Read retained failed artifacts before
retrying an action. Keep code commits separate from acceptance claims and preserve unpublished
patches with exact base/blob identities. Save one useful TXT continuation plus necessary evidence in
the existing owner acceptance folder; never publish private client material. Rollback code by
revert, not data reset. No paid reviewer, migration, credentials, spending, security change,
business send or irreversible cleanup is authorized. Finish independent safe work when a particular
access, renderer, hardware or artwork-approval gate remains blocked.
<!-- END_ENFRA_LEDGER_ARCHIVE old-restart -->


## Progress photo implementation checkpoint — a949ecdb

Progress photo order, 2026-10-16 19:19 UTC (local follow-up from `db76135`, unmerged):
the actual ordinary guided photo editor had captions/removal/density but no ordering action.
Move earlier / Move later now live inside its existing explicit Edit photos or captions mode;
ready summaries and pending-only review remain compact. Image/caption pairs move together after
all delivered captions are collected, with exact report/source/list/incarnation/QA/action-cycle
guards. The full guided caller commits other fields and attempts browser recovery before the
existing end-of-editor refresh. Forward/reverse moves preserve density, retained Omit, source
provenance, 0/NR/qualified text/tables, unrelated sections and unchanged image reviews/originals.

Three actual guided stale-packet experiments additionally reproduced old caption IDs overwriting
newer reset/import/source-replacement captions while the old Move was correctly rejected. Caption
IDs now change with those boundaries and keep their identity during ordinary typing, density and
review changes. A separate actual Add-photo packet reproduced an early rerun losing a caption;
batch validation now precedes caption collection, and only then are new image assets appended.
Existing normalization/limits remain: this route retains the accepted print-normalized image,
not a newly introduced unchanged-source archive. Upload-only AppTest injection is explicit.

The exact local affected set passed 70 checks in 30.10s with zero failures/errors/skips, including
22 new cases: full guided Activity+multiple-caption+Move/Add delivery, durable recovery/reopen,
old native actions, source/reset boundaries, image review/provenance and stale output identity.
Actual DOCX relationships/page images preserve the changed order; no PDF conversion or native
Word visual acceptance is claimed. Original missing-control, stale-packet and Add failures and
distinct fixture/assertion mistakes remain private in `progress-photo-*.xml/log` receipts.
Exact integrated CI, served browser typing/keyboard/narrow ordering and native output review
remain required. No browser, customer original, shared production store or deployment was used.



## Progress photo native action repair — 5918438

Progress photo actions, 2026-10-16 19:38 UTC (local follow-up from `db76135`, unmerged):
the actual ordinary guided photo editor had captions/removal/density but no ordering action.
Move earlier / Move later now live inside its existing explicit Edit photos or captions mode;
ready summaries and pending-only review remain compact. Image/caption pairs move together after
all delivered captions are collected. Add, Move, Remove and Done use one native callback queue,
bound to the displayed report/source/list/incarnation/QA/cycle/content revision. The callback
reads no widget values. The full guided caller commits every delivered field and attempts browser
recovery before the existing end-of-editor refresh. Original source ownership is retained; Move
and Remove preserve Omit, density, 0/NR/qualified text/tables and unchanged image reviews/bytes.

Actual guided tests reproduced stale caption/density packets crossing reset/source boundaries,
Add/Remove/Done dropping a later caption, and an older density mirror returning after reverse
ordering. Native caption/density IDs now rotate at replacement/reset/source/list boundaries while
ordinary typing, density and review keep them stable. Captured values precede structural changes
and old-field cleanup. A separate actual next-action regression caught revision-bound buttons
rendered before the caption commit: queued callbacks are now rendered against the resulting
content revision, and derived review stamps cannot strand them. Normal caption blur followed by
one Move/Remove/Done works without a rescue action. The attempted carried-period confirmation
prerequisite is inapplicable to Progress photos; no period/review gate was changed.

The final local affected set passed 81 checks in 48.05s, zero failures/errors/skips, including
33 new cases: full guided Activity+multiple-caption+Move/Add/Remove/Done delivery, ordinary next
actions, durable recovery/reopen, stale native packets, source/reset boundaries, reverse density,
Omit/removal, review/provenance and stale output identity. Repeated accepted upload is a canonical/
journal no-op. The existing component fixture follows the caller's post-return commit/refresh
contract. Existing normalization/limits remain: Add retains the accepted print-normalized image,
not a newly introduced unchanged-source archive; uploader-only AppTest injection is explicit.
Actual DOCX relationships/page images preserve changed order, without new PDF conversion or
native Word visual acceptance. All first failures and distinct fixture/assertion mistakes remain
private in `progress-photo-*.xml/log` receipts. Exact integrated CI, served browser typing/keyboard/
narrow ordering and native output review remain required. No browser, customer original, shared
production store or deployment was used. The final peer review is separate from these test results.



## Retained Water Done and native observer publication — 1e3516e

2026-10-16 20:15 UTC publication candidate, based on published0959bb2. Main and last actual
served proof remain4ca42c5; no new release is claimed. Required38953590067 on the preceding
integration independently passed2,851 tests, container and resource gates. Adaptive38953590080
failed only Fresh Water's WebKit native ResizeObserver gate; both five-stage business tails and
the full Water upload/order/omission/preview/export journey passed. Those are preceding-build
results, not the new caption/Done repair's browser proof.

This batch adds the reviewed Water repair below, keeps the stricter unfiltered native error gate,
and extends the existing full browser journey with one native clear-caption/Done operation. It
requires the deliberately blank caption in working AND durable state, still pending review,
before continuing the original caption/order/omission/reload/Current/Word/PDF assertions.

One explicitly marked PR249 head also runs a separate diagnostic WebKit process against an
isolated copy of three exact locked frontend modules. Inline registration/callback markers seek
to distinguish native observer owners; there is no global observer wrapper, callback proxy,
timing workaround, extra UI gesture, error filter or production asset mutation. The copied
import graph and first naturally delivered body hashes must match an independently reconstructed
manifest. Registration/target/callback bounds and the first unfiltered native error are retained.
This diagnostic has its own artifact, runs only on attempt1 of the exact marked PR249 head,
and cannot make the ordinary failed journey pass. Multiple owners, missing delivery, overflow,
non-reproduction or an uninstrumented owner remain inconclusive; the last callback alone is not
causal proof. Its own exact25 source/model checks passed; no local browser was run.

The separately published529625b finishing branch now has independent Required3,295/0/0/0 plus
container/resource success. Its Adaptive also retains a distinct Chromium Month popup that opens
then closes about38ms after one native click, and a WebKit native resize error. The responsible
close trigger is unassigned. Its history failures have narrower proved test causes: an exact
temporary conversion marker was mistaken for durable storage, and the comparison locator used
an obsolete heading. Corrections remain separately reviewable; no retry erases these failures.
Current Trainingd7's separate two-engine native date/session/output job passed. All108 actual
PDF page instances and54 pages from the two unique DOCX files were reviewed with named
LibreOffice-compatible renderers; this is synthetic scope, not Microsoft Word, genuine master,
physical-device or assistive-audio acceptance. Both phases and all children remain unaccepted.

Water caption/Done repair, 2026-10-16 20:02 UTC (local from582a6bc, not published):
two actual native AppTests reproduced nonempty and deliberately blank captions being bypassed by
Done's early rerun. Done now collects the current caption/source first and requests only the existing
post-canonical/recovery-attempt refresh; changed captions still need review and cannot gain approval
from closing. The actual full run_web path preserves the same packet's Activity, both edited page
captions and vendor correction in the durable journal. Injected recovery-write failure retains the
browser's current edits, the earlier durable journal and an honest failure status. Same-packet
Activity plus Edit pages passed without changing that Open action.

A separate held native Leave-out packet reproduced removal after report-incarnation or isolated-QA
reset with otherwise identical content. Included-page callbacks now retain and check the existing
editor/QA scope before their unchanged source/block-fingerprint applier. Caption IDs bind source,
image/provenance and editor context, while ordinary typing, clear/reentry and review keep the native
field. Source-correction synchronization also updates its actual active caption key. First failures,
including test-prerequisite and initial derivative-context model mistakes, remain private and distinct.
The final affected set passes 85 tests (14 new), zero failures/errors/skips, in 95.57 seconds on
locked Python3.12.14/Streamlit1.61.1. These local source/AppTest results do not resolve the retained native ResizeObserver or compact
preview activation failures, replace required browser gates, or establish a release. No browser,
customer original, live standing data, CI rerun, merge or deployment was used for this patch.

Current Fresh native-error observation batch 2026-10-16 19:33 UTC starts from the actually
published PR249 `0959bb2484a629b90f4ef1e619ff3df32711a61b` (tree d4642df). Its Adaptive38953590080
still fails the fresh WebKit native ResizeObserver gate during Reporting month→September option
selection at46,021.636ms, although both engines finish all five business stages and independently
match the exact naturally requested primary, Tooltip and virtualizer response bodies. This is not
an absent-patch-delivery explanation or a native-error resolution. The retained original
108,495,040-byte ZIP was independently verified with CRC and SHA256 `96d3692f7414870d70d2d69c34031929a623fc1d7811c7fdd1bbe724219e22e3`.
Main and actually served proof remain `4ca42c59fe647d4cf1f766bfb2d232092e48f7cf`.

An earlier Training87 Chromium document had a real native window ResizeObserver error while
Playwright's pageerror list stayed empty. Fresh previously used only pageerror, so its Chromium
native-error absence was unproved. The new Fresh-only passive collector is installed before its
single navigation, restricted to exact `http://127.0.0.1:8529`, and keeps the first16 unfiltered
error/unhandledrejection records, total/overflow counts and an installed marker. It neither wraps
observers nor schedules work, writes DOM, replaces handlers, prevents defaults, adds UI actions,
waits or error exceptions. The final read is mandatory; missing/failed collection, any native error
or overflow fails independently of the existing pageerror and external-request checks. A failed
read cannot replace the primary task failure; first-failure and final evidence stay separate.
This closes a demonstrated QA coverage gap, not the remaining native resize application defect.
The composed gate passed37 checks in43.05s on locked Python3.12.14: actual collector JavaScript
VM/default semantics, strict Python and primary-failure control flow, unchanged Fresh task
contracts and first-response-only three-asset body verification. Compilation and diff checks pass.
These are source/AppTest checks, with no local browser execution. The new collector and exact0959
composition still require browser CI; no new live observation or acceptance is claimed.



## Retained native Progress browser candidate — 34fb3b7

Progress photos browser candidate, 2026-10-16 20:12 UTC: the QA-only delta starts from
finishing94116f8, with local prerequisite merges of Fresh collectorc769b1d and reviewed photo
source5918438. That photo application source is byte-identical to published PR252529625b;
this new journey has not run in a browser or been published. Main/served proof remains4ca.

The independent15-minute CI job reuses the marked monthly_app server on exact localhost8530,
real cookie isolation, network guards, native uploader, production guided editor and first-attempt
QA generation. One journey per engine covers two uploaded photos, captions/reviews, ordinary
caption blur then Move later/reverse earlier, density6→1, Add while a caption is unblurred,
narrow Remove retaining a later caption, Done retaining unblurred Activity, reload and actual
Word/PDF. Read-only receipts bind exact order, captions, native-photo provenance/reviews and
working/durable equality. Fresh controller inventories require unchanged standing/history
bytes/mtimes and retain every acknowledged normalized photo/object/recovery-link through removal.
Native uploaded photos have empty provenance; this is not source-linked-page review acceptance.
Passive wire observations distinguish text in a prior blur packet from text in the action packet;
neither is inferred from a final value. Fresh defaults stay exact8529; only this task opts into8530.
Both captured primary documents must pass the unfiltered native window error gate as well as
pageerror/external-request checks. Browser/server cleanup errors cannot replace the primary failure.

Exact DOCX Activity photo-page media/order/caption rasters and the known PDF Activity photo-page
aspect class are checked. Every candidate in that class must match exactly one expected image;
extra/changed/missing/duplicate/reordered photo pages fail, while unrelated aspect classes are not
claimed as inspected. PDF comparison permits demonstrated native JPEG noise but requires small
full-image error, the intended photo color and bidirectional one-pixel caption-ink containment.
A retained27-page local LibreOfficeDev26.8alpha conversion passes this bounded comparison on its
existing bytes. It is not browser generation admission, manual all-page, native Microsoft Word,
physical-device, assistive or authentic-master acceptance.

Sixteen new Progress checks passed in the composed103-case local run:102 passed, one OLD
photo test timed out20s during the initial run_web workflow-switch setup, before its photo actions.
That setup failure remains unclassified and was not rerun unchanged; concurrent local suites are
a confounder, not a proved cause. The final10 cleanup/PDF-negative targets passed in10.27s,
including original-error preservation, extra unexpected PDF photo rejection and non-photo-aspect
exclusion. These scopes overlap. Compilation/diff checks pass. UI/state read-only peer review found no
blocker; its cleanup finding is covered by the final negative cases. Exact new CI
Required/Adaptive remains necessary. Earlier probe mistakes are retained: an untyped
_draft lookup selected a boolean, the actual known fixture starts empty This month rather than
Omit, a deliberately single-section output was renumbered, and native PDF JPEG pixels cannot
satisfy exact PNG hashes. Populated Progress Omit remains conditional AppTest scope, not a new
browser claim. No local browser, paid processing, business send or production write occurred.



## Superseded PR249 publication note at1e3516e

# ENFRA Phase 1 / Phase 2 — remaining work

This is the single current remaining-work ledger. Historical evidence and failures stay in
`PHASE1_PHASE2_EXECUTION_2026-10-13.md` and the linked PR comments; they are not fresh defect counts.
Neither phase is accepted. Do not merge a stacked cleanup PR into its parent feature branch.

## Current branch and evidence boundary

2026-10-16 20:15 UTC publication candidate, based on published0959bb2. Main and last actual
served proof remain4ca42c5; no new release is claimed. Required38953590067 on the preceding
integration independently passed2,851 tests, container and resource gates. Adaptive38953590080
failed only Fresh Water's WebKit native ResizeObserver gate; both five-stage business tails and
the full Water upload/order/omission/preview/export journey passed. Those are preceding-build
results, not the new caption/Done repair's browser proof.

This batch adds the reviewed Water repair below, keeps the stricter unfiltered native error gate,
and extends the existing full browser journey with one native clear-caption/Done operation. It
requires the deliberately blank caption in working AND durable state, still pending review,
before continuing the original caption/order/omission/reload/Current/Word/PDF assertions.

One explicitly marked PR249 head also runs a separate diagnostic WebKit process against an
isolated copy of three exact locked frontend modules. Inline registration/callback markers seek
to distinguish native observer owners; there is no global observer wrapper, callback proxy,
timing workaround, extra UI gesture, error filter or production asset mutation. The copied
import graph and first naturally delivered body hashes must match an independently reconstructed
manifest. Registration/target/callback bounds and the first unfiltered native error are retained.
This diagnostic has its own artifact, runs only on attempt1 of the exact marked PR249 head,
and cannot make the ordinary failed journey pass. Multiple owners, missing delivery, overflow,
non-reproduction or an uninstrumented owner remain inconclusive; the last callback alone is not
causal proof. Its own exact25 source/model checks passed; no local browser was run.

The separately published529625b finishing branch now has independent Required3,295/0/0/0 plus
container/resource success. Its Adaptive also retains a distinct Chromium Month popup that opens
then closes about38ms after one native click, and a WebKit native resize error. The responsible
close trigger is unassigned. Its history failures have narrower proved test causes: an exact
temporary conversion marker was mistaken for durable storage, and the comparison locator used
an obsolete heading. Corrections remain separately reviewable; no retry erases these failures.
Current Trainingd7's separate two-engine native date/session/output job passed. All108 actual
PDF page instances and54 pages from the two unique DOCX files were reviewed with named
LibreOffice-compatible renderers; this is synthetic scope, not Microsoft Word, genuine master,
physical-device or assistive-audio acceptance. Both phases and all children remain unaccepted.
