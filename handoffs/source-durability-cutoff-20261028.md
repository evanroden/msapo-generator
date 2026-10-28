# Source, contracts and persistence lane cutoff — 28 October 2026

No merge, deployment, production restart/write or authentic-source mutation was performed. None of the broad issues below is claimed fully accepted/closed. These are exact candidate/test checkpoints. Main advanced to 26878e84 after these candidates; release must integrate and regate exact heads. Diagnostic branch is WIP evidence, not a runtime repair/release candidate.

| Draft PR | Exact published head | Test / review evidence | Hosted runs at cutoff |
| --- | --- | --- | --- |
| #570 actual separate-process source reclaim | 69f1049f58aab82916e8735e465953be61b0d16e | 38 passed; root independently reran 3 passed, clean review | Tests 40729044223 queued; Simplicity 40729044062 success |
| #574 real isolated directory retention journey | 3f26ee98d32263a91a1d32afb6db5e136d804a79 | 34 passed; 153 additional existing source/recovery tests passed | Tests 40730004235, Simplicity 40730004291 queued |
| #581 ownership matrix docs-index fix, stacked #547 | ded60632843f95d1544966a787f711d9518fdc61 | Reproduced 1 failed / 82 passed; fixed 83 passed | Tests 40731255989, Simplicity 40731256096 queued |
| #604 gallery + current-main continuation of #517 | 375c30d2f12460af91c74ab7b7c82a99d818eafa | 22 passed; final original journey Chromium + WebKit PASS with repository-installed frontend | Tests 40740040394, gallery 40740040600, Adaptive 40740040374, Simplicity 40740040420 queued |
| #607 real compatible-version workflow upgrade, includes #533 + main | 8402784ce2d69ccaa87e4064fff190e05086e5d5 | Baseline write / candidate upgrade / baseline retained-history readback all passed; 39 workflow tests | Tests 40740434015, upgrade 40740434948, Adaptive 40740433899, Simplicity 40740434636 queued |
| #609 current source-page publication approval, stacked #607 | a8768bad02ae1ed31699ee886a2383c0428a154b | 3 reproduced failures before; 45 passed after; upgrade still passes; independent review clean, 10 tests passed 2.12s | Tests 40741073909, upgrade 40741073959, Adaptive 40741073850, Simplicity 40741073830 queued |

Exact reviewed #609 tree b2233940ba0799cc04895f389ef797222562b351 matches local 9ec728630d71cf3a70028daec301fad903157263. Source-page guard validates current original identity, page bounds, selected pages and page_allowed before provenance is stripped by publication. Manual independent diagrams and unrelated sibling-page edits remain supported. Historical already-pinned migration records retain their existing explicit origin-scoped adoption policy.

## Remaining concrete blocker — next bounded repair, not started

#533 review discussion_r4396300145 remains unresolved: use_standard replaces imported procedure pictures but retains their obsolete picture-only source references. used_missing_sources can then block generation when the old source is unavailable despite no retained content depending on it. Reproduce using actual replacement and missing-source generation checks; drop only replaced-picture-exclusive references, preserving provenance for retained notes/tables. The companion source-page approval finding discussion_r4396300148 is repaired by #609. Do not call #533/#607 complete merely because old CI was green.

## Gallery environment evidence

The stock shared-venv Streamlit frontend lacked the repository overlay patch. The first narrow source-select click was delivered to the same connected native input with script state notRunning; pointer/focus opened the popup, then it closed. Passive observations are retained in 490-stock-frontend-first-click.json and diagnostic-only script commit c8b1300. No forced/repeated gesture or runtime fix was introduced.

The ORIGINAL published #604 script was then run with a private copied Streamlit package and the existing frontend/date installers. Both Chromium and WebKit passed the complete journey in attempt e9d0b5add722. Full synthetic receipts and installed entry/hash/generation are in 490-installed-frontend-native-pass.json. The local package path required STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false; WebKit used the local extracted-dependency wrapper. CI independently installs normal browser dependencies and repository patches. These local passes are not hosted or physical-device passes, and do not erase earlier stock-runtime failures.

## Distinct issue disposition

| Issue | Status and remaining gate |
| --- | --- |
| #219 | Original durability witnessed across two served builds; authentic full-content/output owner acceptance remains. Originals already exist; do not request reupload or expose receipts. |
| #292 | Merged runtime reclaim + #570 true process/SIGKILL/lock proof in CI; served isolated acceptance remains. |
| #291 | Owner approved 30-day policy; merged runtime + #574 real admin control/history proof in CI; served acceptance remains. Not policy-blocked. |
| #282 | Caption ownership runtime merged; focused lifecycle tests pass. Full native/Word/PDF output acceptance not complete here. |
| #297 | Omission policy/runtime merged; focused omission/reselect tests pass. Served native omit/reinclude and full outputs remain. |
| #470 | #547 matrix + #581 failing index repair; thermal-sharing numeric scope still requires explicit owner decision. |
| #474 | #533 + #607/#609 candidate; second obsolete-source review blocker above remains. Fresh external #550 org-chart owner preserved. |
| #475 | #552 same-code restart + #607 actual upgrade + #609 approval guard in testing; broader separate-browser/served scope/standing-data acceptance remains. |
| #488 | Fresh active competing #562/#563 vendor candidates; reconcile candidate behavior, do not merge both blindly. |
| #287 / #286 | Fresh active #572 duplicate identity/first-fill/save guard plus earlier candidates; combined served/output acceptance remains. |
| #288 | Merged directory idempotency/phone/site logic and focused tests; multi-contract served import acceptance remains. |
| #289 | Merged logo recovery, keyboard native receipt proven; pointer/assistive/physical Safari acceptance remains under #303. |
| #278 | Original WebKit Add totals failure retained; diagnostic #529/#523 are not release candidates; root owns investigation. |
| #281 | Fresh external #565 period/stale-cover candidate testing; prior #392/#406 fixes retained. |
| #302 | #383/#534 merged; #534 is not still blocked by stale issue comment. Focused recovery/history tests pass; retained-browser/two-session/partial-output acceptance remains. |
| #455 | #531 exact head ef698ff7acabf83ac80e5ded93968330be5fb442 all three CI success; vendor/integration choices remain. |
| #490 / #300 | #604 full local installed-frontend gallery journey passes; exact hosted runs, served/physical input and DOCX/PDF evidence approval remain. |

An earlier qa_source_page_outputs run on #574 completed only its corrected-caption 26-page Word/PDF case before OfficeCleanupPending on the next conversion. It is PARTIAL, not a full output/visual pass. No unknown converter was killed, no production service was restarted, and no original source was changed.
