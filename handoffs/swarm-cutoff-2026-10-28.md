# Cutoff handoff — 28 October 2026

Read this first, then `swarm-full-backlog-2026-10-28.json` (all 84 issue assignments) and `swarm-continuation-candidates-2026-10-28.json` (earlier exact heads).

## Status and release rules

Last conservatively confirmed count: **29 of 84 implementation-complete with testing launched**. This includes audited existing implementations; it is NOT 29 verified, deployed or newly authored fixes. Do not count partials or duplicate PRs. Six workers were active when the user requested immediate checkpointing; do not assume local processes or agents survive cutoff. GitHub Actions runs persist independently; re-fetch their actual statuses.

No merges or deployment were performed by this swarm. The user assigned release to a later agent. Release only exact-head green, reviewed, integrated candidates, retaining issue-specific served/authentic acceptance requirements. Do not substitute synthetic tests for genuine-report acceptance. Do not mutate production data, contact paid services, or relax source/privacy/retention guards.

Main advanced from a1b2aa61aa92c596d424c95dba29be66135f3441 to 26878e84af3525dce7eef9209e456e83c4f64162 during wrap-up, merging #426 native table context. Recheck current main and test candidate combinations against it. Old test evidence remains tied to its old exact head.

## Current canonical candidates

| Area | Candidate and exact head | Evidence / next action |
|---|---|---|
| Work orders, all eleven assigned repairs | #602 f9c822f9920dea76bdc14182133940a2e30bf55e | 172 focused passed, independent six new cross-parent cases passed. Tests40739615503, Adaptive40739615538; native review journey still being checkpointed. Replaces parent work-order candidates. |
| Training review | #597 bc90d4fc43c9971e87ba3316c0fbfa4103a19b67 | Stacks #573; 22 review tests independently passed. Tests40738797160, Adaptive40738797070, native Training40738797287. Mapping child and native journey still being checkpointed. |
| Import guidance/accessibility/source instruction review | #601 e307388e82e0127952a4c5a2f7037e97eb5fbd71 | Cumulative #566/#575/#578/#587, 193 passed, two preexisting skips. Independent five new cases passed. |
| Upload route limits + bounded saved-source read | #603 2cf1e3fd2e38704562c529b8f67b4a1934a309b7 | Canonical #584 + external #595; corrected four invalid fixtures, immutable write guard unchanged. 80 focused passed, 15 independent passed. Tests40739867602, Adaptive40739867599. Queue worker integrating #582 + #583 on top. |
| Word generation preflight | #612 cdb7b867d5c14f378c15f405a696ba805147f172 | Cumulative #606, replaces duplicate #564/#586/#590 product hunks. #606:128 passed, independent37 passed; additional privacy/design19 passed. #612:57 passed, including14 classified control probes; baseline seven failures/seven clean controls. Tests40742451452, Adaptive40742451113, simplicity40742451258 queued at checkpoint. |
| Native text input first focus | #594 a1d43bb26a8154d01cf464e644fcd6bba8d9824c | Exact pinned initializer repair. All four local native Chromium/WebKit normal/held-recovery journeys passed with actual Word/PDF. 50 contact tests plus targeted publisher checks passed. Full local compatibility process became unresumable after environment reset: NO full-suite pass claimed. Hosted Tests40737216259, Adaptive40737216112, simplicity40737216326 queued at checkpoint. |
| Workflow upgrade proof | #607 8402784ce2d69ccaa87e4064fff190e05086e5d5 | Real compatible-version three-process test. Upgrade40740434948, Tests40740434015, Adaptive40740433899. |
| Withdrawn workflow source-page approval | #609 a8768bad02ae1ed31699ee886a2383c0428a154b | Repairs actual unresolved #533 review gap; stacks #607. Three rejection gaps reproduced,45 tests passed; independent review underway. Do not release old #533 simply because old CI was green. |
| Equipment-page gallery | #604 375c30d2f12460af91c74ab7b7c82a99d818eafa | Real native upload/save/reopen. Tests40740040394, native gallery40740040600, Adaptive40740040374. Preserve initial Chromium narrow select failure; stock local runtime lacked repository overlay patch. Rerun isolated correctly patched runtime before declaring new product bug. |
| Contact Undo | #608 f5c394252d2ce2941ce309a538138c1c5fddf992 | Fresh external candidate: scope Undo to applied table, preserve later edits. Audit independently and reconcile with #594/#597. |
| Contact provenance | #610 11c215edd8d43ceae31c847fc321af50b8d3efae | Fresh external single-sheet repeated-correction candidate. Audit independently. |

PR URLs follow https://github.com/evanroden/msapo-generator/pull/NUMBER. Workflow URLs follow https://github.com/evanroden/msapo-generator/actions/runs/ID.

## Important overlap choices

- Select external #571 over duplicate #567 (same staging fix, broader independently checked tests).
- Select #603 rather than separately merging #528/#584/#595. Await queue worker final intake integration including #582 and #583.
- #602 already includes its work-order parents; do not double-merge #553/#558/#580/#585.
- #601 already includes #566/#575/#578/#587.
- #612 includes #606 and consolidated caption/row/headerless-table preflight. Earlier #564/#586 duplicated an existing layout-check hook; use consolidated version.
- #577 stacks updated #557; generated TOC is partial for #460, not a claim arbitrary native TOCs work.
- Preview #546/#548 are competing alternatives; #560 cleanup tested with both. Choose/reconcile once.
- Vendor #562/#563 compete; fresh same-day work is not abandoned by default.
- #545 integration contains source/directory/workflow changes; #533 has a newly repaired approval gap in #609. Reconcile before release.

## Unfinished lanes and checkpoint locations

Workspace root: /workspace/scratch/cc85261fea7b. Shared Python: /workspace/scratch/3180f12c2b4a/venv/bin/python. Git push lacks credentials; workers publish exact git trees through connected GitHub APIs. Never assume an unpushed local commit is durable across workspace loss.

- contents_repair: #440 exact-photo correction and stable Return-to-review anchor, four actual Chromium/WebKit wide/narrow cases passed. Publish/check final worker checkpoint. `/outputs-audit` integrates older candidates; initial15 failures mean six previously suggested completion counts were withdrawn. #465 history getter/read-only history now23 focused passed, broader92 passed; changes in three files owned by child and handed back to contents. Real LibreOffice24.2.7.2 acquired; AR raster parity still checking. Do not count #451/#482/#486/#487/#466/#498 complete until combined regressions resolved.
- training_import_repair: `/training-mapping` child of #597, unknown-header mapping, real native output fixture and concurrency journey. Preserve first native fixture/readiness failures. #279 and old RFI266 still require completion; #434/#492 confirmed implementations.
- workorder_metrics_repair: `/reviewed-workorder-browser`, new native CSV upload → correction → inclusion → save/reopen → output journey. Native first click failure preserved; rerun isolated candidate-patched Streamlit runtime, not shared stock frontend.
- queue_audit: final intake branch from #603 incorporating #582 native budget/cleanup and #583 safe parser retries. Child source_durability owns #609 guard, gallery diagnostics and #607. Child import_readiness completed three-file #465 handoff and reviews #609/#612.
- root: `/preflight-integration` clean local70ad069, remote #612 cdb7b867; `/contact-first-focus` #594; `/msapo-coordinator` durable ledger branch.

## Environment and evidence limits

Use isolated copied Streamlit package for frontend experiments. Do not mutate shared venv/static. Set STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false and install current repository frontend patch into the copied static directory. Stock local frontend lacks overlay compatibility and can cause misleading select-close failures. WebKit wrapper: `/workspace/scratch/cc85261fea7b/browser-runtime/webkit-local.sh`. Allocate unique local ports; retain port-collision attempts as invalid, never passes.

Root's real local renderer was LibreOfficeDev26.8, not production24.2 parity. Put actual `libreoffice/program` first in PATH to avoid false test skips from wrapper filter paths. Contents worker has acquired actual24.2.7.2 and must report its results separately.

Full local text-input compatibility run lost its session after runtime reset; log has only partial output. Do not call it passed or still running without verifying. Exact-head hosted workflow remains authoritative.

Financial #458/#494 policy decisions and genuine-report/served acceptance #219/#304 remain open. Maintain existing monetary exclusion; #555 is invoice schema discovery only. Capacity #286/#287 already have established report-vs-standing semantics and are NOT blocked on a new policy decision. #470 proposal is not approved policy.

## Next agent

1. Fetch latest main, all candidate heads, open reviews and exact-head workflow status; queued is not passed.
2. Read worker checkpoint additions below/new handoff files and preserve unpublished work before further edits.
3. Resolve failed tests and remaining implementation items from the full84 ledger, including stale claims.
4. Build one nonduplicate integration set, validate interactions, then perform the user's separate release review. Leave unresolved acceptance issues open.

## Final worker updates

- Workflow guard #609: 45 tests plus actual three-stage upgrade passed. Exact-head runs queued: Tests40741073909, Adaptive40741073850, Upgrade40741073959, Simplicity40741073830. A separate #533 review finding about obsolete picture-only source references blocking replacement is identified but **not started**; retain it as remaining repair work.
- Gallery #604: rerun of original exact code with an isolated runtime containing the repository overlay/date patch passed the full Chromium journey. WebKit continuation pending at this checkpoint. Earlier stock-runtime failure is retained as environment-specific evidence; no new product fix claimed.
- Final intake integration committed locally42d4c2f99e6b12692895413c74ab976c6845e3cd (tree3cffd424b6afd1e31bdbc0f5565e75759a9fe684), publishing from #603. 57 focused and216 broader tests passed. Final integrated large-intake process result was lost: **not a pass**; older #582 probe passed and capped hosted job remains a gate.

- **Durable final intake #615:** https://github.com/evanroden/msapo-generator/pull/615, head `cb8dc0f58a50b04c757e0e3679671a8da9e9a85c`, tree `3cffd424b6afd1e31bdbc0f5565e75759a9fe684`. Stacks584→603→615 and incorporates582+583; avoid separately merging528/595/582/583. Final-tree57+216 tests passed. Pending independent review, capped hosted probe, served acceptance, and compatibility with new main26878e84. PR body contains resume instructions.
- #609 independent review finished clean: ten tests passed in2.12s at publisheda8768bad/treeb2233940.

- #615 exact-head workflows QUEUED: Tests40743256565 (512MiB large-intake job), Adaptive40743255303, Simplicity40743257334, Cover40743257025, Retention40743258101.
- **Durable native work-order WIP #616:** https://github.com/evanroden/msapo-generator/pull/616, head `770aa53e75ba12742f7db4a7cab90d2f4fe1c3de`, tree `5a8eced41a11441cd6cad7b77993d8958b6f0486`, stacks602. Six tracked files include full resume handoff and two synthetic first-failure JSONs. Latest Chromium reached both review destinations, inclusion, manager reentry, snapshot save and narrow reload before dropdown-opening failure. No WebKit/download pass claimed. Rerun isolated patched runtime as documented. #602 product remains172 tests passed.

- **Source durability final checkpoint:** branch `wip/source-durability-cutoff-20261028`, commit `86d4341ec0f5471618b3d35b16701bf7adeed1db`. Read [source lane handoff](https://github.com/evanroden/msapo-generator/blob/wip/source-durability-cutoff-20261028/handoffs/source-durability-cutoff-20261028.md) for all issue dispositions, exact six PR heads, workflow IDs, and synthetic failure/pass receipts. #604 original product tree now passed BOTH Chromium and WebKit with an isolated copy of the existing repository frontend/date patch. No new runtime repair and no retry; earlier stock-runtime failure remains preserved. This supersedes the pending WebKit note above. #533 second review `discussion_r4396300145` (obsolete picture-only references in use_standard) remains not started. New main26878e84 composition remains untested.
- #616 native browser40743266251, Tests40743265058, Adaptive40743265913, simplicity40743267456 queued.
