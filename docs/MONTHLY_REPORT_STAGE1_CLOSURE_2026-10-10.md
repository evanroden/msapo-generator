# ENFRA Monthly Report Builder — Stage-one closure ledger

**Status:** IN PROGRESS — **NOT RELEASE-ACCEPTED**. Engineering reconciliation updated October 11, 2026 UTC after PRs #131–#134 merged. Current main: `2dcb8560a4f6653bbeb05bd1a90324b3ca391a45`; PR #136 is a separate unmerged draft. Historical audits are test leads, not newly reproduced production defects.

**Source of truth for reproduction:** [`MONTHLY_REPORT_USABILITY_AUDIT_2026-10-09.md`](MONTHLY_REPORT_USABILITY_AUDIT_2026-10-09.md), [`HANDOFF_MONTHLY_REPORT_2026-10-09.md`](HANDOFF_MONTHLY_REPORT_2026-10-09.md), [issue #101](https://github.com/evanroden/msapo-generator/issues/101), and the private original 66-page October 10 review and 10-page prompt. Distinct F, P and U identifiers are preserved; overlapping changes are credited only once.

**Evidence boundaries:** GitHub's passing check is a PR-head code test, not evidence that the production app serves the commit or that exported DOCX/PDF matches an authentic authored Word/PDF. No browser, saved-report mutation, image-heavy export or owner acceptance was completed by this ledger. The source audits describe three prior app-generated synthetic Word/PDF pairs and an authentic 40-page Unity/USH August reference; none is silently treated as a new-run output.

## Engineering change / release columns

| Gate | Current evidence | State |
| --- | --- | --- |
| Code in main | #113, #114–#119, #121–#122 and #123–#134 (except closed/unmerged #120 and #135); exact integration through `2dcb8560a4f6653bbeb05bd1a90324b3ca391a45` | **merged; release not accepted** |
| Focused PR CI | [#131](https://github.com/evanroden/msapo-generator/actions/runs/38094931418), [#132](https://github.com/evanroden/msapo-generator/actions/runs/38095379225), [#133](https://github.com/evanroden/msapo-generator/actions/runs/38095379139), [#134](https://github.com/evanroden/msapo-generator/actions/runs/38097581938) | **Three required jobs passed on each exact reviewed PR head** |
| Remaining change PRs | [#136](https://github.com/evanroden/msapo-generator/pull/136) synthetic QA namespace, known-value prefill and original-source replay; draft implementation, not deployed; further coverage remains | **draft; CI and integration pending** |
| Final aggregate CI | [Main after #131–#133](https://github.com/evanroden/msapo-generator/actions/runs/38097568396) green at `103c3c4`; [main after #134](https://github.com/evanroden/msapo-generator/actions/runs/38098010057) in progress when updated; new full CI still required after any #136 merge | **Final-head CI pending** |
| Served production commit | Footer from #116 can identify validated `RENDER_GIT_COMMIT`; no public-browser served hash or matched native design pin confirmed | **unverified; merge ≠ deployment** |
| Isolated live browser | PR #136 supplies a proposed isolated entry, per-browser physical namespace and two distinct fixtures; no live browser acceptance has been performed | **not verified** |
| Real release exports | #132 generated and examined synthetic DOCX and LibreOffice PDF in CI; full-package/image/privacy/authentic Microsoft Word/PDF geometry acceptance remains open | **synthetic content verified on PR head only; release outputs not accepted** |
| Owner acceptance | Source paths, actual build/pin and generated files needed | **pending** |

## Original F01–F16

| ID | Expected user result | Audit baseline | Implementation | Focused evidence versus missing acceptance | Related #101 | Current state |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | Edits and Prepared by retained without routine Save | Oct 9 unsaved blurred Activity lost; reconnect loss reported | Merged #109/#111/#114; U01/U02 | Revisions and OS-write regressions passed PR CI; full browser replays pending | P1/P2 | **Needs browser and refresh/reconnect acceptance** |
| F02 | Vendor/Trane file appears in Activity; onsite calls only ENFRA work | Vendor technical page printed under Maintenance | Merged #117 | Synthetic routing and price-page CI passed; real export pending | P10 | **Real DOCX/PDF page routing and blank Unity/USH calls** |
| F03 | Review identifies actionable omissions and sizes safely | Sparse skeleton and misleading at-least-page counts/size estimate | Merged #107/#108/#121; actionable navigation, unique warning and size improvements | Focused CI exists; generated real-file sizes and live guidance not accepted | P3/P4/P7/P8 | **Needs live readiness/output checks** |
| F04 | Long scrolling report has easy section jumps and identity | 12 sections, no persistent navigator observed | Merged #121; section-jump navigation | Synthetic tests only; focus/keyboard/touch/browser unverified | P11/P12 | **Live navigation/accessibility acceptance pending** |
| F05 | Optional Copilot beside Activity editor, primary upload-first | Manual prompt handoff dominated page | Merged #104/#122; optional AI is only partially covered | CSV metrics accepted into Activity in CI; Copilot proposal acceptance browser path unverified | P10 | **Copilot source/edit/review acceptance pending** |
| F06 | Contacts show person, role and site; current/future scoped updates | Collapsed contact names repeated without site | Merged #94/#127/#131 verified updates and safe site-mapped additions | Test CI green; deletes/reorder, same-site concurrency and future reuse still need coverage | P5 | **Durability and deletion semantics remain** |
| F07 | Clear empty states and intact native table schemas | None placeholders; historical UMMC table mismatch | Merged #128 selected native capital/proposal columns and Status | Synthetic acceptance #132; fresh-master/other grids/Word renderer not accepted | P4 | **Native all-design tables and PDF pages pending** |
| F08 | Global design installation separated from ordinary monthly work | Global update exposed in monthly editor | Merged #123 master admin separation and design pin protections | Synthetic code coverage; real operator path not exercised | P11 | **Live routine/administrator separation pending** |
| F09 | Preview status and last-good preview, honest retention feedback | Blank draft page vs rendering confusion | Merged #114/#134 preview retention, revised semantics and regression | Full #134 head CI passed; stale/identity/late-job owner browser still pending | P1/P2 | **Visible stale/scroll/zoom/live race pending** |
| F10 | Site picker works with pointer, label, touch and keyboard | Cloud click lost selection, Space worked | Merged #112 | AppTest checkbox success; real DOM/touch pending | P2/P12 | **Human device input replay** |
| F11 | Valid Activity source creates cited editable draft; failures explain recovery | Original activity.txt twice returned raw JSON parser error | Merged #104/#118/#122/#125/#132/#133 | Exact original invented TXT and synthetic work-order CSV verified in PR CI; reader/service/live paths open | P10 | **Live ingestion and failure/retry/output placement pending** |
| F12 | Section 10 visibly shows both digits in Word and PDF | Export showed 1 though Word source contained 10 | Merged #105 | Geometry CI only; authentic/source output pending | P8 | **Rendered divider all multi-digit cases** |
| F13 | Branding and photos correctly fitted without squashing | Contents logo flattened; image aspect ratio distorted | Merged #103/#106; #112 logo cards | Image-fit CI, actual exports pending | P5 | **Wide/tall/square/artwork Word/PDF ratio checks** |
| F14 | Training notes survive invalid submit and add-column | Notes disappeared in combined validation/column sequence | Merged #99 | Targeted regression CI; original browser sequence pending | P9 | **Invalid/add-column and deliberate deletion replay** |
| F15 | Contact heading with first row and repeated later | Heading stranded below outage diagrams | Merged #100 | CI pagination scope only | P12 | **0/1/4/40 rows Word/PDF after diagrams** |
| F16 | Imported text wraps without heading collision; design furniture intact | Metrics overlapped utility title, blank bullets and lost footer | Merged #102 | Narrative-flow CI; authentic import output pending | P4 | **All 12 sections, empty bullets, footer before/after** |

## Supplemental issue #101 P1–P12

| ID | Expected user result | Audit baseline | Implementation | Evidence | Original overlap | Outstanding |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | Reconnect, refresh and memory pressure without lost work | 502 and lost entry; separate memory alert | #109/#111/#114 merged | Recovery CI yes; live interrupt and memory correlation no | F01/F09 | Live same-browser outage test; no cause assigned |
| P2 | Clicks give feedback, workflow retained | Repeated site/Start clicks and switch to PO | #109/#112/#114 merged | Widget tests; pointer/touch not confirmed | F01/F10 | DOM, latency, exact identity after Start |
| P3 | Disabled Generate looks disabled and names reason | Bright enabled appearance despite warning gate | #107 merged | UI tests; live visual not checked | F03 | Assistive announcement and stale acknowledgment |
| P4 | Thin report gets actionable soft completeness review | 12 empty sections still generated a skeleton | #108 partial | Soft zero-content test only | F03/F07 | Section links and optional Generate anyway; safety gates |
| P5 | Full names, logo fallback and truthful site help | Six cards no logos; code BRATH unclear | Merged #112/#124; full approved labels and neutral fallback | PR CI; live discovery/navigation not verified | F06/F10 | Actual correct contract/site card check |
| P6 | MBCx/ENFRA Connect/RFI explained inline | Terms unexplained when onboarding collapsed | Merged #113 terminology in section help | PR-head CI; with help collapsed, operator browser unverified | F04 | Live inline explanation |
| P7 | Defensible DOCX/PDF size estimate or none until measured | 1.9 MB estimate vs 6.0 DOCX/4.6 PDF | Merged #121 actual post-generation file sizes | Synthetic tests; live real export unverified | F03 | 15 MB target and actual download sizes |
| P8 | Unique warnings and authentic appendix numbering | Duplicate Cover warning; G. RFI ambiguity | Merged #121 warning dedup / period semantics | Focused CI; actual wrong-month and appendix PDF still open | F03/F12 | Real exports and soft warning revision check |
| P9 | Training event date is single-date value and label | Picker asked for a second date | Open | Current date_input uses scalar date; browser DOM unverified | F14 | Rendered accessibility and period validation |
| P10 | Activity first, optional Copilot, protected edits | External handoff friction | Merged #104/#117/#122/#133 activity and source routing | Synthetic TXT/CSV parser/output; Copilot and live unavailable-reader not accepted | F05/F11 | Actual multi-source/editor/output placement |
| P11 | Identity/jumps/title/footer, no false dirty indication | Generic title and purchase-order footer | Merged #116/#121/#123 report navigation and identity | Code and CI verified; live keyboard/browser state not yet checked | F04/F08 | Sticky focus, false dirty and title |
| P12 | Named controls, focus, pointer/touch and status announcements | Reviewer indicated labels/expander semantics ineffective | #112 partial | No current accessibility-tree proof | F09/F10 | Real DOM, screen reader, touch, zoom |

## October 10 regression targets U01–U06 (do not count as extra original findings)

| ID | Requirement | Implementation | Evidence boundary |
| --- | --- | --- | --- |
| U01 | Old tab cannot overwrite discarded/recreated journal | #114 merged; generation tombstone and revision guards | PR CI passed; live two-tab not checked |
| U02 | OSError cannot terminate remaining editor or claim saved | #114 merged; boundary catches storage errors | PR CI passed; force-failure live not checked |
| U03 | Price headers never map to description/scope | Merged #115/#128/#132 | Synthetic Word/PDF text-path acceptance only; pictures/embedded parts and authentic output remain |
| U04 | Older report cannot erase newer shared training | #116 merged; stale-matrix comparison and explicit reload | PR CI passed; historical two-site owner test pending |
| U05 | Another client's old PNG/EMF/footer/watermark never survives new master | Merged #126/#129/#130 canary slices | Other-client text/image/watermark regressions passed focused CI; full EMF/hidden artifacts and live output not cleared |
| U06 | One missing/broken source does not disable rest of report | Merged #118/#125/#133 | Damaged mixed batch and original Activity TXT passed focused CI; live reader/cache/recovery and final export pending |

## All 113 original proposed acceptance checks — coverage decision

Each row corresponds to a proposed test in original audit section 7. **Not run for final release** means it is **not a proven defect or a pass**. The related implementation may have focused synthetic CI, but that is tracked separately above. The exact contract, site set, month, pinned design, source hashes and output links are required to change one row to *verified live*. Owner/Word-specific items remain pending until that renderer/browser is available. These 113 rows are not to be summed with targeted synthetic CI tests.

| Audit test | Scenario / expected behavior | Related closure work | Release-coverage decision | Actual final-release result |
| --- | --- | --- | --- | --- |
| S01 | New monthly report with no draft | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S02 | Choose multiple sites | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S03 | Start fresh from master | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S04 | Use prior-month report | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S05 | Use different site's report | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S06 | Use incomplete report | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S07 | Change month before Start | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S08 | Return during active work | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S09 | Open older pinned design | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S10 | Unsupported starting file | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S11 | Checkbox square and label pointer | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| S12 | Keyboard and touch site selection | F01/F10 · P1/P2/P5 | Isolated owner browser + CI helper | **Not run** |
| P01 | Read start/retention copy | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P02 | Edit and change sections | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P03 | Auto-retain then refresh | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P04 | Force recovery disk failure | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P05 | Brief reconnect while editing | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P06 | Close/reopen in active period | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P07 | Delayed write then later edit | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P08 | Edit two sections around failed retry | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P09 | Standing contact correction | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| P10 | Start fresh after abandonment | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Not run** |
| N01 | Find Activity, Training and downloads | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N02 | Use section jump navigation | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N03 | Unexplained language review | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N04 | Collapse and reopen help | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N05 | Keyboard-only operation | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N06 | Zoom 200% | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N07 | Narrow viewport | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N08 | Heading structure/screen reader | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N09 | Validation announcement | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| N10 | No None/null in empty tables | F04/F07/F08/F09/F10 · P11/P12 | Browser DOM/keyboard/touch with help closed | **Not run** |
| A01 | Valid activity source becomes grounded draft | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A02 | Multiple sources combine once | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A03 | Manual correction then new file | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A04 | Deliberate deletion not restored | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A05 | Copilot shorten with review | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A06 | Work-order option effect | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A07 | Several photos and captions | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A08 | Corrupt image next to valid | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A09 | Uncertain date/status | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A10 | Remove source with derived edit | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A11 | Active-work return for Activity | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A12 | Export Activity once correctly | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| V01 | Find Trane upload in Activity | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V02 | Find ENFRA onsite calls | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V03 | Redirect vendor uploaded in call area | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V04 | Unity/USH empty call neutrality | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V05 | Separate vendor and onsite rows | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V06 | Compare section preview and exports | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| C01 | Capital source document/table maps native columns | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| C02 | Scanned proposal image | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| C03 | Mixed price in body/native table | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| C04 | Price in pictures/alternate metadata | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| C05 | Blank retained price column safe | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| C06 | Manual proposal edit survives source rerun | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| C07 | DOCX/PDF package/image scan | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| C08 | Ambiguous source table prompts focused choice | U03 · pricing safety | Synthetic price tables + DOCX/PDF package inspection | **Not run** |
| D01 | Hospital staff Training framing | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D02 | Add monthly training event | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D03 | Reject vendor staff enrollment | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D04 | Thermal first-fill contract storage | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D05 | Explicit NR unchanged | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D06 | Ambiguous similar site labels | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D07 | Show capacity provenance | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D08 | Changed thermal source/historical snapshots | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D09 | Collapsed contact name/role/site | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D10 | Contact current and future update | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D11 | Old completed report unchanged | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D12 | Reuse outage diagram | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D13 | Failed thermal write/retry | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D14 | Ambiguous thermal site prompt | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D15 | Future month thermal reuse | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D16 | Empty event preserves notes | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D17 | Add first/subsequent requirement | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D18 | Missing-site correction | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| D19 | Combined invalid/add-column preserves note | F06/F07/F14 · U04 · standing data | Isolated two-site standing stores + future/old reports | **Not run** |
| R01 | Preview updates after edit | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R02 | Rapid edit rejects older preview | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R03 | Preview/export contention | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R04 | Multi-page preview legibility | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R05 | Preview failure retains prior image | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R06 | Export fresh pinned master | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R07 | Continue saved report | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R08 | Every included section | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R09 | Download real DOCX/PDF | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R10 | File identity in names | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R11 | Authentic authored PDF comparison | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R12 | Production design pin verified | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R13 | Contact table after diagrams 0/1/4/40 | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R14 | Imported narratives all sections | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| R15 | Footers/blank bullets before/after import | F03/F09/F12/F13/F15/F16 | Native DOCX, app PDF, independent Word render | **Not run** |
| Q01 | Display name is attribution only | Privacy/output safety | Code/package/privacy review | **Not run** |
| Q02 | Private evidence minimized | Privacy/output safety | Code/package/privacy review | **Not run** |
| Q03 | No private artifacts in public repo | Privacy/output safety | Code/package/privacy review | **Not run** |
| Q04 | Malformed/unsafe inputs bounded | Privacy/output safety | Code/package/privacy review | **Not run** |
| Q05 | Only current passive links remain | Privacy/output safety | Code/package/privacy review | **Not run** |
| Q06 | Removed hidden assets do not survive | Privacy/output safety | Code/package/privacy review | **Not run** |
| T01 | Tracked deletion/reviewer removed | Merged #99 import integrity | Synthetic tracked-change DOCX import | **Not run** |
| T02 | Supported tracked text/comments | Merged #99 import integrity | Synthetic tracked-change DOCX import | **Not run** |
| T03 | Unsupported structural edit rejected locally | Merged #99 import integrity | Synthetic tracked-change DOCX import | **Not run** |
| T04 | Corrected-copy import retry | Merged #99 import integrity | Synthetic tracked-change DOCX import | **Not run** |
| T05 | Prior import remap after fix | Merged #99 import integrity | Synthetic tracked-change DOCX import | **Not run** |
| X01 | Isolated testing mode enabled | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X02 | Contact/thermal/logo/report data separation | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X03 | Prefill completed fixture | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X04 | Reset only test data | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X05 | Render known-value prefill | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X06 | Replay original sources separately | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X07 | Compare authentic Word/PDF elements | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X08 | Failed test write never falls back to live | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X09 | Repeat fixture deterministic | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |
| X10 | Test access/side effects prove isolation | Proposed QA controls in draft #136 (not yet release accepted) | Must pass exact merged CI, isolated live and independence/side-effect checks | **Not run for final release** |

## Additional selected regression cases (not extra audit check passes)

- `CR-inputs-2/-9/-21`, `K1`, `G1-data-2/-4/-6`: price-first Project Budget / Proposal Amount / Proposal Total and native Status/description mapping. Merged #115 fixes identified mapping; full visible/native/hidden/PDF/bitmap output needs acceptance.
- `CR-inputs-5/-6/-7/-15/-16`: two synthetic site profiles, old report A versus newer shared training report B, duplicate course/person identities, month rollover, events and source images. Merged #116 guard; exact historic reload and follow-on edit remain to be demonstrated live.
- `CR-render-2/-5/-13`: other-client PNG metadata, EMF, watermark, footer mixed with `enfrasolutions.com`, hidden package parts; **not reproduced on current main**, requires canary and source-safe cleanup.
- `CR-inputs-4`, `G3-ingest-1/-2`, `K5/K6/K10/K11`: one corrupted stored source, mixed valid/invalid uploads, malformed ZIP, unknown charset, no false source success; #118 merged for isolated restoration; full acceptance pending.
- U01/U02: discard/recreate generation and real `OSError` write injection from #114 CI; browser refresh and reconnect outstanding.
- Work-order fixture: `WO-TEST-1001` September 3 completed, `WO-TEST-1002` September 20 completed, `WO-TEST-1003` September 24 open. Expected 3 total, 2 completed, 1 open, 66.7% closure from **CSV itself**, not imported DOCX prose.
- Proposal safety tokens: `$12,345.67`, `$987.65`, `$13,333.32`, `$456.78`, `$222.22` must be absent; `Q-TEST-731` identifier must remain. Neither a passing native-text search nor a single excluded page is a full safety pass.
- Source output cases: synthetic 12-section starting DOCX, first/second/third app outputs `rrh_synthetic_v1/v2/v3_imported` with associated input receipts, and unchanged private authentic Unity/USH August DOCX+PDF. Source hashes and renderer names from the full audit are required before comparison.

## October 11 integration evidence (distinguish implementation from acceptance)

- Merged [#131](https://github.com/evanroden/msapo-generator/pull/131) at `6c04d37c`, [#132](https://github.com/evanroden/msapo-generator/pull/132) at `1a94a238`, [#133](https://github.com/evanroden/msapo-generator/pull/133) at `103c3c4c`, and [#134](https://github.com/evanroden/msapo-generator/pull/134) at `2dcb8560`. These are **implemented** slices. The integrated main after #131–#133 passed all three required jobs in [run 38097568396](https://github.com/evanroden/msapo-generator/actions/runs/38097568396). #134 also passed all three jobs on its corrected head in [run 38097581938](https://github.com/evanroden/msapo-generator/actions/runs/38097581938); main integration still requires exact-merge CI.
- [#136 isolated QA draft](https://github.com/evanroden/msapo-generator/pull/136) contains a proposed server-side separated namespace, known-value prefill and independently ingested synthetic CSV/TXT replay. As a **draft**, it is not evidence of production separation, live compatibility, cross-tab reset or complete X01–X10 acceptance. Do not use it with customer records.
- **Authentic reference recovered privately by SHA-256:** The exact Unity/USH August authored PDF (`2b204491f9bd9b21452f2300b9844e8993b97e9cf69d1deb4b94c3a1a09c789b`) is a 40-page Adobe PDFMaker reference. An earlier-uploaded DOCX under a different filename has the **exact audited original `(4).docx` bytes** (`d8705610e4da6f335c95159b42966deffb6e8369861a2c5a6e873c3267cea1ea`); it has 115 package entries including 47 Word media entries. Both remain private and were not placed in GitHub. Authentic source identification is **verified**. Comparable new application DOCX/PDF export, all 40-page geometry comparison and independently supported Microsoft Word rendering remain **not verified**; synthetic #132 outputs are not substitutes.
- Public served SHA and native design pin remain **unverified**. No owner browser acceptance or complete page-by-page exported-artifact inspection is recorded here. The existing 113 original proposed final-release checks below intentionally remain not run, even where focused synthetic regression tests have passed. They are not 113 proven defects.
- The old competing draft #110, superseded #120 and closed unmerged #135 were not used for publication. Later iPhone Duo/foldable responsive redesign is out of stage-one scope.

## Next evidence gates and owner check (minimal)

1. Finish #118/#119, reconcile #113, fix the rest of the in-scope F/P issues. Recheck all source and PR heads before merging; do not use competing draft #110 or the obsolete transport patch bundle.
2. Pass one full GitHub CI on **the exact integrated main candidate**. Preserve revision/comment scrubbing, native design pins, content-safety gates and bounded preview/conversion work.
3. Verify the actual live footer `Running code: <40-character hash>` and selected master design pin. A green GitHub check is not deployment proof.
4. Using *server-isolated test data*, test choose contract/site/month, edit actor and Activity, refresh, add vendor/CSV/photos, correct wording, check Training and thermal NR, Generate and download. Never write QA records into real standing data.
5. Inspect every generated page of actual application PDF, native DOCX parts and an independently identified Word renderer against authentic design. Record visible geometry and omitted/duplicate/hidden content, each filename, SHA256, size, page count and sign-off.

**Live verification blocker:** A non-Work web fetch of the public Render Streamlit app is not a functioning browser replay; private Render-log/hosting-plan access and production data changes were not authorized. Inability to fetch through one tool does not establish the site is unavailable. Actual served commit, touch/screen-reader behavior and authentic output remain unverified until a suitable approved browser/owner check.
