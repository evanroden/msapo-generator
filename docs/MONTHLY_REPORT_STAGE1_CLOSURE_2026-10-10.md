# ENFRA Monthly Report Builder — Phase 1 release-acceptance ledger

**Status: IN PROGRESS — NOT RELEASE-ACCEPTED.** Updated October 11, 2026. This is an evidence ledger, not a declaration that all original audit tests were executed. Preserve F01–F16, #101 P1–P12, U01–U06 and all 113 original proposed checks below. Green CI, a served commit, actual Word/PDF exports, authentic document fidelity and owner acceptance are separate gates.

**Sources:** [Issue #101](https://github.com/evanroden/msapo-generator/issues/101), [October 9 usability audit](MONTHLY_REPORT_USABILITY_AUDIT_2026-10-09.md), [October 9 handoff](HANDOFF_MONTHLY_REPORT_2026-10-09.md), and the private original paired Word/Adobe PDF/October 10 review. Historical baseline rows below preserve original scope; the dated proof here supersedes their older shorthand.

## Exact production, synthetic and authentic gates

| Gate | Evidence and status |
| --- | --- |
| Merged implementation | Main at **`7702256df10ca9b86d23c11f478879fdbd01cd91`** after merged [#152](https://github.com/evanroden/msapo-generator/pull/152) (QA Compare/Generate bound to the editor's final draft) and [#151](https://github.com/evanroden/msapo-generator/pull/151) (real Word/PDF header-free RFI continuation test). Earlier #147 (ten independently keyed native tables), #148 (bounded source-verified JPEGs in PDF-only copy), #149 ledger and #150 RFI parsing are also merged. All #131–#152 related repairs merged; superseded #110/#120/#135 not used. |
| Exact branch CI | [#152 run 38178822734](https://github.com/evanroden/msapo-generator/actions/runs/38178822734) and [#151 run 38178285048](https://github.com/evanroden/msapo-generator/actions/runs/38178285048): **pytest, production container and 512 MiB / 0.5 CPU resource checks passed independently on both exact reviewed heads**. Previous [#148 run 38172610338](https://github.com/evanroden/msapo-generator/actions/runs/38172610338) established native ten-table/eight-photo capped synthetic output with preserved tables and price canaries. |
| Synthetic native report artifact | [Ten-table output artifact 11715035903](https://github.com/evanroden/msapo-generator/actions/runs/38172610338/artifacts/11715035903): editable 13.6 MB DOCX with ten separate 3/4-column physical tables, 9-page actual PDF with all ten current table markers. All nine pages visually inspected; no obvious clipped table-page content. Artifact uses invented fixtures only and is retained seven days. |
| Integrated main CI | Latest exact merged-main SHA **`7702256df10ca9b86d23c11f478879fdbd01cd91`** [Tests 38181570776](https://github.com/evanroden/msapo-generator/actions/runs/38181570776), with an earlier intermediate [Tests 38181538771](https://github.com/evanroden/msapo-generator/actions/runs/38181538771). Await and record the final three required job conclusions; the older [38177931153](https://github.com/evanroden/msapo-generator/actions/runs/38177931153) was green on `47bb8454` but had a separate failed live QA. **Current exact-main CI pending.** |
| Exact served main | [Public Chromium run 38178305727](https://github.com/evanroden/msapo-generator/actions/runs/38178305727) verified **exact `47bb8454d4dbcbb8d63c5b8aa54591c3de3ae6e3`** but failed during source replay / export staleness. The older [38177047869](https://github.com/evanroden/msapo-generator/actions/runs/38177047869) passed all isolated steps on `c19b5194`. Current `7702256...` must pass new exact served-SHA browser tests. **Latest served SHA pending.** |
| Full isolated live browser | [Run 38177047869](https://github.com/evanroden/msapo-generator/actions/runs/38177047869) passed **18/18 prefill, independent 18/18 original CSV/TXT replay, all four real DOCX/PDF downloads, exact edited Activity SHA before/after refresh, and isolation reset** on older `c19b5194`. [Run 38178305727](https://github.com/evanroden/msapo-generator/actions/runs/38178305727) on `47bb8454` failed because the isolated QA wrapper compared/generated against an *earlier* draft in the same rerun, then the guided editor changed that draft. Merged #152 corrects ordering and adds a neutral rerun export-retention test. **No live pass yet on final merged 7702256; recheck all scenarios on the exact SHA.** |
| Genuine authored Word/PDF | The exact SHA-verified private Unity/USH August Word has **10 native tables, 27 Word section definitions and 47 media entries**. Its original Adobe PDFMaker PDF has **40 pages**, 36 portrait/4 landscape (landscape source PDF pages **4, 5, 12, 33**). An independent local LibreOffice conversion of the **unchanged same authored Word** rendered **43 pages**, including landscape pages **4, 5, 13, 36**: one extra page appears in Monthly Activity, one in the water-treatment attachment portion, and one in Capital Renewal. This verifies a real rendering-engine difference unrelated to app-generated content. The separate private fresh-master diagnostic produced 21 pages with synthetic current rows; direct page-count equality is not a valid Word/Adobe parity metric. Authentic artwork, captions/footer/section 10, 0/1/4/40 contacts, hidden-image/EMF price checks and independent Microsoft Word rendering remain open. Neither private input nor renders are in public GitHub. |
| Intermittent real-browser downloads | On latest exact build [run 38173548632](https://github.com/evanroden/msapo-generator/actions/runs/38173548632), first Chromium attempt received `Download.save_as: canceled` after 18/18 known-value checks; rerunning only the failed job on the same SHA then transferred **all 4 actual files** and passed all other steps. This is an intermittent reliability observation; do not reclassify attempt 1 as success or assume a root cause without evidence. |
| Owner | Manual novice start, site/month, vendor versus ENFRA calls, source corrections/deletions, standing contacts/training/capacity, touch/keyboard usability and genuine Word/PDF comparison remain. No owner acceptance/signoff has occurred. **Do not mark Phase 1 release-accepted or formally begin Phase 2.** |

## Evidence boundaries and standing report rules

Isolated testing uses a separate per-browser server namespace and reset; synthetic known-value prefill is not original-source replay. Trane/vendor work belongs to Monthly Activity Summary, while Client Service Calls includes only onsite ENFRA technicians. Do not state that Unity/USH has no technicians or that its call section is not applicable. Proposal values must retain ID/Status/engineering facts but omit all pricing in visible, hidden, raster and package parts. No real client data, private Render account/secrets or source copyrighted pages are ever published as test artifacts; selected native design pins and prior completed business records must remain immutable. Passing text-only canary tests cannot substitute for image/embedded-part privacy audits.

## Original F01–F16

| ID | Expected user result | Audit baseline | Implementation | Focused evidence versus missing acceptance | Related #101 | Current state |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | Edits and Prepared by retained without routine Save | Oct 9 unsaved blurred Activity lost; reconnect loss reported | Merged #109/#111/#114; U01/U02 | Real isolated-browser exact Activity SHA persisted and restored on refresh, [live run 38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274); owner two-tab interruption still open | P1/P2 | **Bounded live refresh passed; owner outage pending** |
| F02 | Vendor/Trane file appears in Activity; onsite calls only ENFRA work | Vendor technical page printed under Maintenance | Merged #117 | Synthetic routing and price-page CI passed; real export pending | P10 | **Real DOCX/PDF page routing and blank Unity/USH calls** |
| F03 | Review identifies actionable omissions and sizes safely | Sparse skeleton and misleading at-least-page counts/size estimate | Merged #107/#108/#121; actionable navigation, unique warning and size improvements | Focused CI exists; generated real-file sizes and live guidance not accepted | P3/P4/P7/P8 | **Needs live readiness/output checks** |
| F04 | Long scrolling report has easy section jumps and identity | 12 sections, no persistent navigator observed | Merged #121; section-jump navigation | Synthetic tests only; focus/keyboard/touch/browser unverified | P11/P12 | **Live navigation/accessibility acceptance pending** |
| F05 | Optional Copilot beside Activity editor, primary upload-first | Manual prompt handoff dominated page | Merged #104/#122; optional AI is only partially covered | CSV metrics accepted into Activity in CI; Copilot proposal acceptance browser path unverified | P10 | **Copilot source/edit/review acceptance pending** |
| F06 | Contacts show person, role and site; current/future scoped updates | Collapsed contact names repeated without site | Merged #94/#127/#131 verified updates and safe site-mapped additions | Test CI green; deletes/reorder, same-site concurrency and future reuse still need coverage | P5 | **Durability and deletion semantics remain** |
| F07 | Clear empty states and intact native table schemas | None placeholders; historical UMMC table mismatch | Merged #128 selected native capital/proposal columns and Status | Merged #147 exact region references; ten independently shaped native Word and real PDF tables verified under capped resources [38172610338](https://github.com/evanroden/msapo-generator/actions/runs/38172610338); authentic Word parity open | P4 | **Synthetic native tables passed; authored parity pending** |
| F08 | Global design installation separated from ordinary monthly work | Global update exposed in monthly editor | Merged #123 master admin separation and design pin protections | Synthetic code coverage; real operator path not exercised | P11 | **Live routine/administrator separation pending** |
| F09 | Preview status and last-good preview, honest retention feedback | Blank draft page vs rendering confusion | Merged #114/#134 preview retention, revised semantics and regression | Full #134 head CI passed; stale/identity/late-job owner browser still pending | P1/P2 | **Visible stale/scroll/zoom/live race pending** |
| F10 | Site picker works with pointer, label, touch and keyboard | Cloud click lost selection, Space worked | Merged #112 | AppTest checkbox success; real DOM/touch pending | P2/P12 | **Human device input replay** |
| F11 | Valid Activity source creates cited editable draft; failures explain recovery | Original activity.txt twice returned raw JSON parser error | Merged #104/#118/#122/#125/#132/#133 | Actual browser native CSV/TXT source replay passed 18/18 independently and downloaded real DOCX/PDF [38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274); damaged-source and original vendor-file owner paths remain | P10 | **Synthetic source replay passed; broader vendor/retry pending** |
| F12 | Section 10 visibly shows both digits in Word and PDF | Export showed 1 though Word source contained 10 | Merged #105 | Geometry CI only; authentic/source output pending | P8 | **Rendered divider all multi-digit cases** |
| F13 | Branding and photos correctly fitted without squashing | Contents logo flattened; image aspect ratio distorted | Merged #103/#106; #112 logo cards | Merged #148 disposable PDF-only source-JPEG reduction; eight inherited synthetic photos and ten tables generated successfully under 512 MiB [38172610338](https://github.com/evanroden/msapo-generator/actions/runs/38172610338); original branding parity unverified | P5 | **Wide/tall/square/artwork Word/PDF ratio checks** |
| F14 | Training notes survive invalid submit and add-column | Notes disappeared in combined validation/column sequence | Merged #99 | Targeted regression CI; original browser sequence pending | P9 | **Invalid/add-column and deliberate deletion replay** |
| F15 | Contact heading with first row and repeated later | Heading stranded below outage diagrams | Merged #100 | CI pagination scope only | P12 | **0/1/4/40 rows Word/PDF after diagrams** |
| F16 | Imported text wraps without heading collision; design furniture intact | Metrics overlapped utility title, blank bullets and lost footer | Merged #102 | Narrative-flow CI; authentic import output pending | P4 | **All 12 sections, empty bullets, footer before/after** |

## Supplemental issue #101 P1–P12

| ID | Expected user result | Audit baseline | Implementation | Evidence | Original overlap | Outstanding |
| --- | --- | --- | --- | --- | --- | --- |
| P1 | Reconnect, refresh and memory pressure without lost work | 502 and lost entry; separate memory alert | #109/#111/#114 merged | Synthetic editor refresh/live durable journal accepted [38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274); genuine outage and concurrent tabs remain | F01/F09 | Live same-browser outage test; no cause assigned |
| P2 | Clicks give feedback, workflow retained | Repeated site/Start clicks and switch to PO | #109/#112/#114 merged | Widget tests; pointer/touch not confirmed | F01/F10 | DOM, latency, exact identity after Start |
| P3 | Disabled Generate looks disabled and names reason | Bright enabled appearance despite warning gate | #107 merged | UI tests; live visual not checked | F03 | Assistive announcement and stale acknowledgment |
| P4 | Thin report gets actionable soft completeness review | 12 empty sections still generated a skeleton | #108 partial | Soft zero-content test only | F03/F07 | Section links and optional Generate anyway; safety gates |
| P5 | Full names, logo fallback and truthful site help | Six cards no logos; code BRATH unclear | Merged #112/#124; full approved labels and neutral fallback | PR CI; live discovery/navigation not verified | F06/F10 | Actual correct contract/site card check |
| P6 | MBCx/ENFRA Connect/RFI explained inline | Terms unexplained when onboarding collapsed | Merged #113 terminology in section help | PR-head CI; with help collapsed, operator browser unverified | F04 | Live inline explanation |
| P7 | Defensible DOCX/PDF size estimate or none until measured | 1.9 MB estimate vs 6.0 DOCX/4.6 PDF | Merged #121 actual post-generation file sizes | Four actual synthetic Word/PDF browser downloads passed [38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274); authentic report sizing remains | F03 | 15 MB target and actual download sizes |
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
| U03 | Price headers never map to description/scope | Merged #115/#128/#132 | Ten distinct price-free native Word tables, full zipped XML and PDF text source-price canaries passed [38172610338](https://github.com/evanroden/msapo-generator/actions/runs/38172610338); scanned price/artwork privacy still unaccepted |
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
| P03 | Auto-retain then refresh | F01/F09 · P1/P2 | Isolated browser interruption + storage fault | **Synthetic live `38160972703` passed its bounded equivalent; broader owner/edge acceptance pending** |
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
| A01 | Valid activity source becomes grounded draft | F05/F11 · P10 | Source upload/editor/export fixture | **Synthetic live `38160972703` passed its bounded equivalent; broader owner/edge acceptance pending** |
| A02 | Multiple sources combine once | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A03 | Manual correction then new file | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A04 | Deliberate deletion not restored | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A05 | Copilot shorten with review | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A06 | Work-order option effect | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A07 | Several photos and captions | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A08 | Corrupt image next to valid | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A09 | Uncertain date/status | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A10 | Remove source with derived edit | F05/F11 · P10 | Source upload/editor/export fixture | **Not run** |
| A11 | Active-work return for Activity | F05/F11 · P10 | Source upload/editor/export fixture | **Synthetic live `38160972703` passed its bounded equivalent; broader owner/edge acceptance pending** |
| A12 | Export Activity once correctly | F05/F11 · P10 | Source upload/editor/export fixture | **Synthetic live `38160972703` passed its bounded equivalent; broader owner/edge acceptance pending** |
| V01 | Find Trane upload in Activity | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V02 | Find ENFRA onsite calls | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V03 | Redirect vendor uploaded in call area | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V04 | Unity/USH empty call neutrality | F02 | Separate vendor/onsite input plus DOCX/PDF | **Not run** |
| V05 | Separate vendor and onsite rows | F02 | Separate vendor/onsite input plus DOCX/PDF | **Synthetic live `38160972703` passed its bounded equivalent; broader owner/edge acceptance pending** |
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
| X01 | Isolated testing mode enabled | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Isolated public browser entered synthetic-only QA ([live 38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274)); broader owner testing pending** |
| X02 | Contact/thermal/logo/report data separation | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Not run for final release** |
| X03 | Prefill completed fixture | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Real browser prefill 18/18 facts ([live 38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274)); broader owner testing pending** |
| X04 | Reset only test data | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Real browser reset returned empty isolated namespace ([live 38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274)); broader owner testing pending** |
| X05 | Render known-value prefill | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Real prefill DOCX/PDF files downloaded ([live 38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274)); broader owner testing pending** |
| X06 | Replay original sources separately | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Native CSV/TXT replay 18/18 and real DOCX/PDF downloaded ([live 38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274)); broader owner testing pending** |
| X07 | Compare authentic Word/PDF elements | Native comparison controls only; authored-app Word/PDF geometry still pending | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Not run for final release** |
| X08 | Failed test write never falls back to live | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Not run for final release** |
| X09 | Repeat fixture deterministic | Implemented in merged #136; synthetic exact-head and integrated CI green | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Fixture values/provenance deterministic in passing real browser ([live 38163049274](https://github.com/evanroden/msapo-generator/actions/runs/38163049274)); broader owner testing pending** |
| X10 | Test access/side effects prove isolation | Merged #136 fail-closed QA, external-reader block; #137 merged late-preview lease | Exact-head CI passed; isolated public browser, actual production output and owner acceptance remain pending | **Not run for final release** |

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

- Merged [#131](https://github.com/evanroden/msapo-generator/pull/131) at `6c04d37c`, [#132](https://github.com/evanroden/msapo-generator/pull/132) at `1a94a238`, [#133](https://github.com/evanroden/msapo-generator/pull/133) at `103c3c4c`, and [#134](https://github.com/evanroden/msapo-generator/pull/134) at `2dcb8560`. These are **implemented** slices. The integrated main after #131–#133 passed all three required jobs in [run 38097568396](https://github.com/evanroden/msapo-generator/actions/runs/38097568396). #134 passed its corrected PR-head run [38097581938](https://github.com/evanroden/msapo-generator/actions/runs/38097581938) and its merged-main run [38098010057](https://github.com/evanroden/msapo-generator/actions/runs/38098010057).
- [#136 isolated QA merged](https://github.com/evanroden/msapo-generator/pull/136): server-side per-browser separated persistent storage, generation guards, separate live/test preview pool, known-value prefill, real synthetic CSV/TXT source replay, no paid reader side effects, plus test-only reset. Exact-head [38101672436](https://github.com/evanroden/msapo-generator/actions/runs/38101672436) passed 2055 tests, container and 512 MB/0.5 CPU budget. Integrated main [38102068297](https://github.com/evanroden/msapo-generator/actions/runs/38102068297) also passed exactly 2055 tests and all 3 required jobs at `cc441e4`. This is implementation/CI evidence, **not** proof of live isolated browser behavior or complete X01–X10 owner acceptance. Do not use with customer data.

- [#137 draft](https://github.com/evanroden/msapo-generator/pull/137) separately addresses report-only remove-all contact intent, reorder identity safety and rejects late preview workers after QA reset. This branch must pass exact-head required CI and later integrated-main CI before its changes can be marked merged. No live/shared-directory mutation or browser verification has been performed.
- **Authentic reference recovered privately by SHA-256:** The exact Unity/USH August authored PDF (`2b204491f9bd9b21452f2300b9844e8993b97e9cf69d1deb4b94c3a1a09c789b`) is a 40-page Adobe PDFMaker reference. An earlier-uploaded DOCX under a different filename has the **exact audited original `(4).docx` bytes** (`d8705610e4da6f335c95159b42966deffb6e8369861a2c5a6e873c3267cea1ea`); it has 115 package entries including 47 Word media entries. Both remain private and were not placed in GitHub. Authentic source identification is **verified**. Comparable new application DOCX/PDF export, all 40-page geometry comparison and independently supported Microsoft Word rendering remain **not verified**; synthetic #132 outputs are not substitutes.
- Public served SHA and native design pin remain **unverified**. No owner browser acceptance or complete page-by-page exported-artifact inspection is recorded here. The existing 113 original proposed final-release checks below intentionally remain not run, even where focused synthetic regression tests have passed. They are not 113 proven defects.
- The old competing draft #110, superseded #120 and closed unmerged #135 were not used for publication. Later iPhone Duo/foldable responsive redesign is out of stage-one scope. Current CI source-replay and known-value fixture checks must not be mistaken for an authentic source-file browser run, client output privacy clearance or independent Word-rendering acceptance.

## Next proof gates and short owner testing batches

1. **Engineering integration:** the latest code after #148 at `df312fd...` passed all three [main CI jobs 38173086244](https://github.com/evanroden/msapo-generator/actions/runs/38173086244), and its latest exact-SHA [public Chromium run 38173548632](https://github.com/evanroden/msapo-generator/actions/runs/38173548632) passed prefill, independent native source replay, all four real Word/PDF transfers, Activity durable/recovered SHA and isolation reset on **attempt 2**. **Attempt 1 had a canceled Word transfer**; intermittent browser downloads remain a reliability issue. Require new exact-main CI and served-SHA browser acceptance after subsequent changes.
2. **Genuine format and privacy:** #147/148 implemented distinct pinned native table regions and price-free outputs in a ten-table synthetic capped test, but authentic Word/Adobe design parity is still outstanding. Check source-heading sanitation, preserved company artwork and divider 10. Run real editable DOCX+PDF through independent Word and PDF renderers, inspect every page for images, 0/1/4/40 contacts, labels, hidden content, grid spans, footer, and identity, against the exact authentic authored private paired reference. Keep those files out of GitHub.
3. **Owner batch A (about 5 actions):** choose contract, exact site group and month; start a fresh report from saved design; edit Activity, change sections and reload; verify no work is lost and previous design remains pinned.
4. **Owner batch B (about 5 actions):** upload the original Activity TXT plus 3-row work-order CSV; separately upload a Trane vendor report; verify 3/2/1/66.7, vendor in Activity only, onsite calls separated, manual corrections kept and deliberate deletes respected.
5. **Owner batch C (about 5 actions):** check standing contacts by exact site, thermal `NR`, client-staff training and one monthly event; review proposal ID/Status without price; preview sections, download both actual files, inspect covers/10th divider/photos/tables and report any confusing controls or wrong geometry.

**Closure rule:** no date, green test count, PR merge, deployment SHA or generated synthetic PDF alone constitutes Phase 1 release acceptance. Record owner checks and authentic output-page comparison before changing this status to RELEASE-ACCEPTED.
