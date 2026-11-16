---
document_type: owner_acceptance_sessions
base_commit: 1459ad96a336ed7b62d75e591a256ecf1a73afe6
date: 2026-11-15
status: proposed_manual_acceptance_not_executed
workflow: monthly_report_and_related_process_control
---

# Owner acceptance in six synthetic sessions — November 2026

**Scope:** 87 open `needs-owner-check` issues as queried on 2026-11-15, using each issue's latest substantive close-out checklist (later progress comments are not substituted for close-out). These are **instructions, not test results or closure authorization**. Every issue is assigned to exactly one numbered step; other sessions may exercise the same underlying behavior without claiming that issue again. Do not close or relabel anything from this plan. If only part of a step is run, record that issue as **partial**, not settled.

**Acceptance boundaries:** Check the deployed **current** About SHA and successful relevant CI before doing served acceptance; a historical pinned SHA in a close-out comment is evidence context, not a claim that today serves it. Keep screenshots and files synthetic. Do not introduce any customer, contractor or contact data, prices or client-branded files. **No client-facing report may contain monetary columns or pixels.** Do not launch paid AI/reader calls, send email, mutate production masters or directory data, change hosting/auth/API mode, or use genuine private reports. Visual Word/PDF checks require opening the *downloaded* files (not just the draft preview); record tested renderer, browser and device. Phone-width emulation is not a physical touch or screen-reader check.

## One-time fixture preparation (repository checkout, no production changes)

Use Python 3.12, requirements in `requirements-dev.lock`, LibreOffice for the renderer and a newly made disposable local QA folder. The source fixtures are owned by this repository; `tests/fixtures/monthly_report/imperfect_vendor_chemical/MANIFEST.json` records their expected names, SHA-256 and intended review/exclusion.

```bash
python -m pip install -r requirements-dev.lock
mkdir -p /tmp/msapo-owner-202611/pack /tmp/msapo-owner-202611/directory
unzip -q runtime/qa_fixtures/ENFRA_Synthetic_Imperfect_Vendor_Chemical_QA_Pack.zip -d /tmp/msapo-owner-202611/pack
python -m scripts.qa_monthly_report_outputs
cp test-artifacts/monthly-synthetic/SYNTHETIC-Word-report.docx /tmp/msapo-owner-202611/starting.docx
python - <<'PY'
from pathlib import Path
from scripts.qa_reviewed_work_orders import CSV
from scripts.directory_retention_fixture import write_fixture
root = Path('/tmp/msapo-owner-202611')
(root / 'synthetic-reviewed-wo.csv').write_bytes(CSV)
write_fixture(root / 'directory')
PY
```

To make the one reusable **mixed-size page-and-picture set** used in S3/S4, create only invented marks. All files stay outside the repository; derived copies must not be substituted for originals when checking immutable SHA-256.

```bash
python - <<'PY'
from pathlib import Path
import pymupdf
from PIL import Image, ImageDraw
root = Path('/tmp/msapo-owner-202611')
doc = pymupdf.open()
for i,(w,h) in enumerate(((612,792),(792,612),(612,792)), 1):
    p = doc.new_page(width=w, height=h)
    p.insert_text((45,70), f'SYNTHETIC TEST ONLY — page {i}', fontsize=16)
    for x,y,mark in ((20,20,'TL'),(w-100,20,'TR'),(20,h-40,'BL'),(w-100,h-40,'BR')):
        p.insert_text((x,y+12), f'{mark}-{i}', fontsize=10)
doc.save(root / 'synthetic-mixed-3-pages.pdf')
for name,color in (('north',(35,85,155)),('south',(170,85,45))):
    im = Image.new('RGB',(640,320),'white')
    ImageDraw.Draw(im).rectangle((24,24,616,296),outline=color,width=16)
    ImageDraw.Draw(im).text((45,145),'SYNTHETIC '+name.upper(),fill=color)
    im.save(root / f'synthetic-{name}-chart.png')
PY
```

Files are also discoverable at [`runtime/qa_fixtures/`](../runtime/qa_fixtures/) (fixture pack), [`tests/fixtures/monthly_report/imperfect_vendor_chemical/`](../tests/fixtures/monthly_report/imperfect_vendor_chemical/) (manifest/regenerator), [`scripts/qa_monthly_report_outputs.py`](../scripts/qa_monthly_report_outputs.py) (synthetic Word/PDF), [`scripts/qa_reviewed_work_orders.py`](../scripts/qa_reviewed_work_orders.py) (CSV bytes), [`scripts/directory_retention_fixture.py`](../scripts/directory_retention_fixture.py) (workbook) and [`scripts/qa_expense_adaptive.py`](../scripts/qa_expense_adaptive.py) (invented Expense journey). Modify only *disposable copies* to construct negative cases. Where a step needs synthetic manifest corruption, 205 rows, API failure or near-limit resource conditions, use an isolated local server and data directory; **do not attempt that variant on the deployed shared app**. No manual test is marked passed by this document.

## S1 — Starting Report, import and editing

**One setup:** A fresh Demo North / September 2026 Monthly report, with `test-artifacts/monthly-synthetic/SYNTHETIC-Word-report.docx` as an optional Starting Report and the ZIP's `QA_Vendor_Service_MixedPages.docx` for source-region review. Work only in a disposable synthetic contract.

1. Start one fresh synthetic report at 390px and desktop widths. Record the actual number of controls/clicks to first useful source action, choose site/period, upload a file with ambiguous date/site and an unsupported object, then correct its native warning with keyboard and pointer. Confirm scoped error, focus, loaded-file destination/privacy wording and all edits after reload; compare any previous baseline only if measured with the **same** state. **Issues checked after this step:** [#303](https://github.com/evanroden/msapo-generator/issues/303), [#298](https://github.com/evanroden/msapo-generator/issues/298).

2. Import a synthetic DOCX containing a genuine table, source instructions, bracketed example, a floating 2×2 frame and a separate chart/photo (derive an edited copy of the synthetic Starting DOCX; never use an authentic report). Distinguish editable text/table from raster-only/unsupported content, keep source-region references, exclude example content, replace only the selected artwork and preserve adjacent text. Reimport, save/reopen and visually inspect Word/PDF without claiming floating text became editable. **Issues checked after this step:** [#464](https://github.com/evanroden/msapo-generator/issues/464), [#463](https://github.com/evanroden/msapo-generator/issues/463), [#467](https://github.com/evanroden/msapo-generator/issues/467), [#271](https://github.com/evanroden/msapo-generator/issues/271).

3. Import an invented primary and alternate DOCX with two plausible cover photos, a transparent logo and another photo in the body. Confirm the unresolved-photo decision blocks Continue until one picture is selected; verify explicit no-photo behavior, saved/reopened/next-month selection, proportional crop, logo alpha/white details and unchanged body photo in actual DOCX/PDF. **Issues checked after this step:** [#283](https://github.com/evanroden/msapo-generator/issues/283).

4. Use a disposable image-heavy DOCX and controlled just-below/at/above-bound variants through the **ordinary Starting Report picker**, not template shelf. Compare displayed byte/page/parse limits to first refusal and distinct template-shelf policy; reject oversized/faulty source atomically, replace/retry same filename with new bytes, reopen and confirm original hash, other edits, no duplicate, truthful error and full Word/PDF. Keep source/output memory observations for the supported case; do not consume production storage for load tests. **Issues checked after this step:** [#471](https://github.com/evanroden/msapo-generator/issues/471), [#472](https://github.com/evanroden/msapo-generator/issues/472), [#473](https://github.com/evanroden/msapo-generator/issues/473), [#462](https://github.com/evanroden/msapo-generator/issues/462).

5. In compact native row cards, enter literal synthetic Markdown-like headings, a bare URL and date/number values; verify non-clickable literal rendering, raw edit values, keyboard focus and close/reopen. Navigate to Review directly **without first visiting sections**; inspect pending/late/current preview ordering, narrow-screen zoom/scroll and Back/Next reading position. Do **not** expect a jump selector: ordered-page navigation is the decided design. **Issues checked after this step:** [#725](https://github.com/evanroden/msapo-generator/issues/725), [#299](https://github.com/evanroden/msapo-generator/issues/299), [#497](https://github.com/evanroden/msapo-generator/issues/497).

6. Generate a 12-section synthetic report with AR content and a deliberately misleading imported 'Section 1 Accounts Receivables' source heading. Verify Section **10** in TOC, divider and body, the true AR destination, every heading once, links/page destinations in native Word and PDF; then omit Water and recheck recalculated numbering, page fields and unchanged source. **Issues checked after this step:** [#493](https://github.com/evanroden/msapo-generator/issues/493), [#460](https://github.com/evanroden/msapo-generator/issues/460).

7. On identical empty, populated, repeat-month, Word-ready/PDF-failed and save-failed synthetic states, count actual visible Review/Create/success text and actions. Confirm one clearly labeled Create, independent Word/PDF outcomes, direct next actions and accessible retry wording. Record before/after only against an identical historical state, otherwise label the comparison unavailable. **Issues checked after this step:** [#438](https://github.com/evanroden/msapo-generator/issues/438).

## S2 — Activity, work orders, vendor tables and source rows

**One setup:** Reuse Demo North / September 2026. Create `synthetic-reviewed-wo.csv` from `scripts/qa_reviewed_work_orders.py`'s `CSV` constant, and extract `QA_Vendor_Service_MixedPages.docx`, `.pdf`, `QA_Vendor_AmbiguousDate.pdf` from the shipped synthetic ZIP. Prepare modified copies for second site/period, duplicated identifiers and ambiguous rows; leave the originals untouched.

1. Upload UTF-8/BOM and quoted/semicolon synthetic CSV variants with 000-prefix IDs, two sites, two months, PM/non-PM/unknown trade, a manual aggregate, conflict and `WO-A`/`wo-a` at the same and different sites. Review explicit column/date/site mapping and provenance; confirm same-site conflicts do not inflate totals, cross-site identities remain separate, manual totals remain labeled, corrections recalculate, and identical reimport/reopen/output preserves source receipts and changes. **Issues checked after this step:** [#476](https://github.com/evanroden/msapo-generator/issues/476), [#478](https://github.com/evanroden/msapo-generator/issues/478), [#481](https://github.com/evanroden/msapo-generator/issues/481), [#717](https://github.com/evanroden/msapo-generator/issues/717).

2. Import invented two-page text work-order PDF (repeated/rotated header, wrapped row, missing status plus scanned page) and native work-order DOCX with merged headers/multiline task. Verify every source-page/row receipt, raw first/last cells, unresolved/scanned/OCR-not-run fallback and no auto-approved duplicate. Correct one row, save/reimport/reopen, compare SHA-256 of originals and Section 2 Word/PDF. **Issues checked after this step:** [#479](https://github.com/evanroden/msapo-generator/issues/479), [#480](https://github.com/evanroden/msapo-generator/issues/480).

3. Use a two-site 12-month work-order grid (blank versus zero) and separate invented CMMS CSV/DOCX with alternate maintenance headings, incomplete completion/date and multiline task. Edit only October site B and one eligible service call; keep other site, unknown column, annual aggregates and pending work intact. Reopen/roll, then inspect Section 2/5 native Word/PDF row identity, performer provenance, widths/repeated headings and no pricing. **Issues checked after this step:** [#454](https://github.com/evanroden/msapo-generator/issues/454), [#483](https://github.com/evanroden/msapo-generator/issues/483).

4. Through the visible Activity source-oriented intake (no Table 1/2/3 selection), upload synthetic vendor report and safe sibling with a negative continuation, image evidence and impossible service/report date; separately test valid leap/day-first date. Verify page-level evidence selection and review hold for impossible dates, vendor work **not** mislabeled as onsite/vendor contacts, no unintended paid reader, persistent narrative after edit/replacement/reopen and one authorized Section 2 occurrence in Word/PDF. Record actual clicks and keyboard path at narrow width. **Issues checked after this step:** [#477](https://github.com/evanroden/msapo-generator/issues/477), [#277](https://github.com/evanroden/msapo-generator/issues/277), [#791](https://github.com/evanroden/msapo-generator/issues/791).

5. Import an invented Word merged trade-band table with two headings, three named contacts, repeated header, blank spacer and an *unnamed phone/comment-only row*. Confirm that ambiguous row retains the complete raw table for manual mapping rather than a fictional person; valid names group in source-column order. Move/edit a named contact, cancel a blank row, reopen, then check Section 6 Word/PDF for exact contacts/groups and **no monetary columns**. **Issues checked after this step:** [#789](https://github.com/evanroden/msapo-generator/issues/789), [#455](https://github.com/evanroden/msapo-generator/issues/455).

6. In one synthetic DOCX add a Pending and Declined proposal and an issue register (Open, Closed, equal-text distinct rows, owner/date/action/custom column). After **one** reviewed upload, check both editable destinations without re-upload, unresolved status stays literal, independent manual issue survives, and changed-source/identical reimport does not revive omitted rows or overwrite a note. Carry two months and inspect Section 11 plus the issue register in actual Word/PDF, exact row counts and no prices. **Issues checked after this step:** [#495](https://github.com/evanroden/msapo-generator/issues/495), [#457](https://github.com/evanroden/msapo-generator/issues/457).

## S3 — Source pages, Water, Scorecards, photos and delivered PDFs

**One setup:** Reuse a clean Demo North synthetic report. Use `QA_Water_Treatment_MixedPages.pdf` and `QA_Water_Treatment_ImageOnlyScan.pdf` from the ZIP. Generate `synthetic-mixed-3-pages.pdf` (portrait/landscape/portrait, numbered edges) with the small PyMuPDF command below; use temporary invented PNG captions and no client artwork.

1. From Add source files / Manage source files, inspect clean/accepted/unread/failed/changed states, Upload new/Already uploaded and visible Add destination. Try an invalid file and a cancel, then change destination and add one valid invented DOCX/PDF/XLSX/photo in turn; no implicit paid interpretation or duplicate insertion. Save/reopen with a retained exclusion and source-specific retry; other accepted files/edits remain unchanged. **Issues checked after this step:** [#437](https://github.com/evanroden/msapo-generator/issues/437), [#300](https://github.com/evanroden/msapo-generator/issues/300).

2. In Section 3 Scorecards and Section 4 MBCx, Include all one time for uniquely numbered mixed-size portrait/landscape pages; omit one section only when explicitly intended. Verify first/middle/last and all corners once in direct Review, downloaded DOCX (open with Word) and independently rendered PDF; inspect captions, following section, retained original SHA and save/reopen/replacement. Record the template/Section 10 discrepancies against **synthetic** approved design checks; leave any private reference comparison as a separately marked owner-only decision, never publish reference bytes. **Issues checked after this step:** [#482](https://github.com/evanroden/msapo-generator/issues/482), [#451](https://github.com/evanroden/msapo-generator/issues/451), [#466](https://github.com/evanroden/msapo-generator/issues/466), [#450](https://github.com/evanroden/msapo-generator/issues/450).

3. In Section 7 use the primary Water PDF upload once with synthetic mixed vendor/water pages. Verify report-only, short optional monthly update-only, and combined update-plus-pages paths; one highlight/action precedes approved pages exactly once, with no invented measurements or current-month carry of historical observations. Try unsupported upload, replace/retry and save/reopen, retaining original SHA, specific refusal and no paid drafting without explicit authorization. **Issues checked after this step:** [#489](https://github.com/evanroden/msapo-generator/issues/489), [#456](https://github.com/evanroden/msapo-generator/issues/456).

4. With disposable copies, approach the displayed whole-PDF page/image-size budgets from below/at/above in an isolated instance; confirm remaining-page/byte notice appears *before* review and over-budget batches refuse completely. In fitting retry, include page 1, omit page 2, reorder/retire/re-add exactly one owned occurrence; keep an excluded section omitted through save/reopen/rollover, and confirm no foreign-site, legal, signature or money-marked page is implicitly approved. Check preview and Word/PDF. **Issues checked after this step:** [#468](https://github.com/evanroden/msapo-generator/issues/468), [#297](https://github.com/evanroden/msapo-generator/issues/297).

5. Add six numbered synthetic progress photos plus the same-byte photo/source-page pair, select page captions, clear one intentionally and resolve a conflict, then move and remove an occurrence. At touch/phone width tap empty photo intake and pending Photo 3; confirm correct editor auto-opens, caption text survives rerender, deliberate collapse and refresh. Save removal/re-add, test output density 1–6/page; verify no old caption/recalled page/duplicate and no adjacent picture loss in Word/PDF. **Issues checked after this step:** [#282](https://github.com/evanroden/msapo-generator/issues/282), [#435](https://github.com/evanroden/msapo-generator/issues/435).

6. On a technical synthetic source with a monetary-marked column and a pressure reading, prove the monetary column/page is held while the technical value remains editable; inspect **all** DOCX package parts, text and raster PDF pages for leakage. Without blurring an Activity editor, immediately click Upload/Add/Remove/Done and check each action plus exact text survives. Repeat with competing browser edit and source-page reread: other accepted fact/page, earlier version and source SHA stay intact. **Issues checked after this step:** [#276](https://github.com/evanroden/msapo-generator/issues/276), [#278](https://github.com/evanroden/msapo-generator/issues/278).

7. Generate synthetic PDF A; display in the in-site completed-output viewer, compare displayed page raster/identity to the downloaded PDF, then edit to B and check A becomes stale and missing/historical bytes are not silently rebuilt. Retry after reset, keyboard/narrow-screen/page-position/accessible-name check. Record explicit **owner scope decision**: same-session-only viewer accepted or persistent/historical access still outstanding; do not infer authenticated history access. **Issues checked after this step:** [#439](https://github.com/evanroden/msapo-generator/issues/439).

## S4 — Reusable directories, diagrams, capacity, Training and rollover

**One setup:** Use two entirely invented contracts A/B, A's North/South sites, B's East site, and September→October→November 2026. Start with `synthetic-retention.xlsx` from `scripts/directory_retention_fixture.py` and a clearly labeled invented chart PNG (see fixture commands). Clone the isolated namespace for mutation/conflict checks; never modify actual directory, master or company-default stores.

1. In *isolated* directory/catalog storage, stage healthy and malformed logo/record plus two site names that collide after punctuation/slug normalization. Verify a scoped pre-selection collision warning, retained healthy site, safe metadata recovery and no changed shared records. Import the synthetic multi-tab workbook (Region/incomplete/alias/copy), map/confirm only intended identities, repeat unchanged import, then deliberate contact correction. Confirm exact text-only literal Markdown-like labels, keyboard access, version retention and no other-contract leak. **Issues checked after this step:** [#289](https://github.com/evanroden/msapo-generator/issues/289), [#288](https://github.com/evanroden/msapo-generator/issues/288), [#709](https://github.com/evanroden/msapo-generator/issues/709).

2. Publish a valid invented PNG/JPEG organization chart and a separate node-only chart for contract/site North; reopen and Use each. From South and Contract B prove North's site-only chart unavailable; contract default is available only at its approved scope. Replace North's picture after saving an older report; ensure unchanged old version, other sites and revision. Inspect Word/PDF image placement. Corrupt hash-valid bytes/malformed site manifest remain automated/isolated-fault cases, not production edits. **Issues checked after this step:** [#787](https://github.com/evanroden/msapo-generator/issues/787), [#748](https://github.com/evanroden/msapo-generator/issues/748), [#744](https://github.com/evanroden/msapo-generator/issues/744), [#474](https://github.com/evanroden/msapo-generator/issues/474).

3. Approve synthetic outage procedure with PNG and JPEG, publish, Replace with identical content and explicitly Use in a new report. Reopen, edit unrelated Activity text and inspect images in Word/PDF, with prior revision unchanged. Only in disposable isolated storage inject a malformed workflow manifest or invalid picture to verify refusal and successful later retry; do not corrupt any shared deployment defaults. **Issues checked after this step:** [#785](https://github.com/evanroden/msapo-generator/issues/785), [#753](https://github.com/evanroden/msapo-generator/issues/753), [#737](https://github.com/evanroden/msapo-generator/issues/737).

4. Use an isolated synthetic master A/B: inspect/download exact original A bytes and SHA-256, install B only in test namespace, keep a saved report pinned to A, and check both version downloads. In a cloned disposable instance damage *only synthetic latest-master metadata*, reopen/edit/export the pinned old report and confirm fresh Apply refuses until repaired; missing own pinned source must still block output. No production master install, readback or corruption. **Issues checked after this step:** [#731](https://github.com/evanroden/msapo-generator/issues/731), [#465](https://github.com/evanroden/msapo-generator/issues/465).

5. Save a distinct diagram/standing text/table for both contracts and A's two sites; make a report-only correction and Leave out in North, close, reopen in a fresh browser and roll two months. Check shared/default approval is deliberate, no cross-site/contract fact transfer, saved originals and old versions survive. From two tabs provoke stale save and recover. Separately record decisions (approve/defer) in the ownership matrix for thermal sharing, vendor effective dates/status and standing/Capital promotion—no silent policy migration. **Issues checked after this step:** [#475](https://github.com/evanroden/msapo-generator/issues/475), [#470](https://github.com/evanroden/msapo-generator/issues/470).

6. In Section 6 approve invented grouped vendor status/When to Contact table for A's two sites; check contract-wide reuse versus B isolation and report-only edit versus shared publication. Edit a selected contact directly with one click, keyboard and mouse/narrow widths; Cancel/Done and conflict recovery must preserve pending text and other rows. Reopen/roll and inspect native Word/PDF with correct bands/status and no monetary data. **Issues checked after this step:** [#488](https://github.com/evanroden/msapo-generator/issues/488), [#436](https://github.com/evanroden/msapo-generator/issues/436).

7. Import two-site synthetic thermal-capacity DOCX (separate systems, multiline headers, blank/zero/NR) plus spreadsheet percentage/date/unit cells; edit one measurement, change Include off/on and save/reopen, preserving original/source mapping. Use two isolated editors to check stale shared row refusal/retry, renamed site identity and report-only override without cross-site changes. Verify clear Thermal capacity file entry separate from MBCx, keyboard access, optional exclusion in preview and Word/PDF, unknowns intact. **Issues checked after this step:** [#486](https://github.com/evanroden/msapo-generator/issues/486), [#487](https://github.com/evanroden/msapo-generator/issues/487), [#287](https://github.com/evanroden/msapo-generator/issues/287), [#286](https://github.com/evanroden/msapo-generator/issues/286).

8. In Section 9 import synthetic ordered Capital priorities for two sites with a custom nonfinancial column. Edit/add/omit one report-only row, explicitly approve a reusable version, switch site and Contract B, then carry two months. Verify old pin, scope and order; inspect preview/Word/PDF each approved row once, and reject a separately monetary-marked source before it can publish. **Issues checked after this step:** [#492](https://github.com/evanroden/msapo-generator/issues/492).

9. Import an invented annual Training matrix plus prior-month/current-month/unknown completed events. Confirm current-month editing appears **before** standing requirements at phone width, unknown rows stay unconfirmed and blank/0 values stay distinct. Edit/add/cancel events, reimport identical bytes, reopen and roll two months/new year; old completions remain historical, standing year rows once. In two tabs induce same-row/other-cell stale conflicts, preserve pending text, and inspect Section 12 Word/PDF and keyboard focus. **Issues checked after this step:** [#459](https://github.com/evanroden/msapo-generator/issues/459), [#496](https://github.com/evanroden/msapo-generator/issues/496), [#434](https://github.com/evanroden/msapo-generator/issues/434), [#279](https://github.com/evanroden/msapo-generator/issues/279).

10. From September synthetic issue/training/source cover with future October metadata, create October and November drafts. Confirm visible September cover period outranks speculative future metadata until an explicit period decision, old issue does not count as newly resolved, no prior Training completion is current, exclusion does not imply resolution and prior-month records remain intact. Inspect dated output labels in downloaded Word/PDF. **Issues checked after this step:** [#281](https://github.com/evanroden/msapo-generator/issues/281).

## S5 — Browser recovery, failure gates and final regeneration

**One setup:** Use the same clean invented Demo North report with a PNG/Activity edit plus the fixture-generated Word/PDF, in two separate synthetic browser profiles. Fault injection, 205-row stress, master failures and staging-budget exercises belong to **disposable isolated copies only**, never the public production namespace.

1. Save unfinished Activity plus invented PNG in browser A; refresh/reopen, save identically, edit one field, save/reopen again and compare exact picture and text. Open browser B to prove unfinished work isolation, then explicitly Discard a separate unfinished copy without removing shared snapshot/history. Missing/hash-bad, oversized, symlink or changed journal files require isolated pytest-style fault cases, never live disk modification. **Issues checked after this step:** [#781](https://github.com/evanroden/msapo-generator/issues/781), [#770](https://github.com/evanroden/msapo-generator/issues/770), [#769](https://github.com/evanroden/msapo-generator/issues/769).

2. In two tabs make divergent unsaved edits and inspect history, explicit stale-write recovery and no version added by mere viewing; page through old versions then Start over and ensure durable history remains. During a two-page preview use radio/disabled/file input, keyboard Tab/Shift+Tab/Ctrl+Enter on Prepared by, delayed/canceled edit, hidden/restored tab and source switch. Verify current preview never overtakes a real edit, focus/page position and no false no-op acknowledgment. In a disposable conversion-failure run, verify separate Word-ready/PDF-failed and shared-save retries without new revision. **Issues checked after this step:** [#302](https://github.com/evanroden/msapo-generator/issues/302), [#293](https://github.com/evanroden/msapo-generator/issues/293).

3. In an isolated synthetic report test Generate preflight with overlong caption, tall chart and overwide row; confirm each refusal links to the correct editor. After safe correction, pin a design and source, generate twice, compare canonical row/section/page/image manifests and downloaded DOCX/PDF while normalizing only volatile packaging. Repeat with manually corrected accepted fact and failed interpretation to prove no silent promotion; inspect a disposable synthetic master canary in raster and package XML for private/nonapproved content. Record the architectural approval boundary, not a claim covering every client layout. **Issues checked after this step:** [#296](https://github.com/evanroden/msapo-generator/issues/296), [#498](https://github.com/evanroden/msapo-generator/issues/498).

4. On the served build, record the actual About SHA and the time of one small *synthetic* PDF preview. Inspect only logs after that request for deprecated `fitz`-import warnings; historical lines or CI AST checks do not count as a live absence proof. Read-only observation only: no hosting or dependency changes. **Issues checked after this step:** [#428](https://github.com/evanroden/msapo-generator/issues/428).

5. In an isolated Shared report fixture-testing namespace, stage invented original A, choose B without Start, reload, Start B and Reset. Verify active versus selected labels and byte-identical original downloads. With **disposable copies** near the shown budget, inspect active-copy protection, 24-hour idle expiration rule, capacity refusal/recovery and no purge of originals. No production service resets or cleanup. **Issues checked after this step:** [#292](https://github.com/evanroden/msapo-generator/issues/292).

6. In a disposable synthetic report create two equal-description distinct proposal rows, carry and edit the second, close/reopen and check each appears once in Word/PDF. Separately use a 205-row invented issue/proposal table: edit first/last across pages and Activity, save/reopen, verify every row survives while Create refuses >200. Explicitly exclude five, then export 200 with original row identity and Activity edit intact. **Issues checked after this step:** [#280](https://github.com/evanroden/msapo-generator/issues/280).

7. In a local mocked/isolated reader fixture, propose a contradictory quantity/date/year against a two-page technical citation, then a matching fact; confirm citation, review warning, saved original/corrected fact and no contact/omitted-roster bytes in the prompt. Exercise native edit/reopen/Word/PDF. Inspect a real external reader request **only if already separately authorized**; otherwise mark that transmission/accuracy check pending, not passed and do not invoke paid processing. **Issues checked after this step:** [#285](https://github.com/evanroden/msapo-generator/issues/285).

## S6 — Purchase Order and Expense recovery (not Monthly)

**One setup:** Use the same app with the Purchase Order and Expense tabs, with two invented local PDF/image receipts and an unreadable invented quote. The existing synthetic harnesses are `scripts/qa_po_adaptive.py` and `scripts/qa_expense_adaptive.py`; do not submit, send emails or enable any API.

1. In Purchase Order upload an intentionally unreadable synthetic source and inspect bounded extraction failure, Retry and Paste text choices. Switch to an invented text quote and verify the prior error/response disappears, no stale interpretation or new paid request is silently accepted. Model-JSON malformed-output and retry timing are already covered by mocked tests, not intentionally induced live failures. **Issues checked after this step:** [#22](https://github.com/evanroden/msapo-generator/issues/22).

2. In Expense at phone/touch width use two invented receipts including a failed reader and non-USD source; find Remove/Retry and USD correction without first opening a preview. Confirm scope, alter only descriptive vendor/job (approval retained), then change actual source/date/site (review invalidated). Split one receipt into two manually reviewed USD lines, reload and verify both lines in XLSX/PDF with one original and no submission/email. **Issues checked after this step:** [#294](https://github.com/evanroden/msapo-generator/issues/294).

3. In the same isolated Expense draft request previews of two invented receipts, split the second and remove the first during its preview load. Refresh to verify the first remains removed, second edit/original survives; re-add unchanged first and inspect a **new** preview and downloaded XLSX/PDF with only intended allocations. Do not induce actual production process timeout/unlink failure; controlled tests cover those faults. **Issues checked after this step:** [#295](https://github.com/evanroden/msapo-generator/issues/295).

## Complete issue → step index

| Issue | Session | Step |
|---|---|---:|
| [#22](https://github.com/evanroden/msapo-generator/issues/22) — Validate Claude output and bound OCR/model failure modes | S6 | 1 |
| [#271](https://github.com/evanroden/msapo-generator/issues/271) — Unblock authentic Starting Reports with precise artwork preservation | S1 | 2 |
| [#276](https://github.com/evanroden/msapo-generator/issues/276) — Verify monetary exclusion without blocking technical Monthly content | S3 | 6 |
| [#277](https://github.com/evanroden/msapo-generator/issues/277) — Verify grounded Activity extraction and safe mixed-source routing | S2 | 4 |
| [#278](https://github.com/evanroden/msapo-generator/issues/278) — Verify delivered edits and accumulated facts survive source mutations | S3 | 6 |
| [#279](https://github.com/evanroden/msapo-generator/issues/279) — Verify Training row edits remain recoverable across concurrent changes | S4 | 9 |
| [#280](https://github.com/evanroden/msapo-generator/issues/280) — Keep carried and over-limit reports editable without row loss | S5 | 6 |
| [#281](https://github.com/evanroden/msapo-generator/issues/281) — Preserve truthful period provenance through Monthly rollover | S4 | 10 |
| [#282](https://github.com/evanroden/msapo-generator/issues/282) — Synchronize source captions and retire only owned report pages | S3 | 5 |
| [#283](https://github.com/evanroden/msapo-generator/issues/283) — Separate cover photographs from logos and verify branded geometry | S1 | 3 |
| [#285](https://github.com/evanroden/msapo-generator/issues/285) — Validate supported facts and minimize reader prompt data | S5 | 7 |
| [#286](https://github.com/evanroden/msapo-generator/issues/286) — Preserve native capacity schemas and formatted values during import | S4 | 7 |
| [#287](https://github.com/evanroden/msapo-generator/issues/287) — Make shared capacity updates conflict-aware and explicitly reusable | S4 | 7 |
| [#288](https://github.com/evanroden/msapo-generator/issues/288) — Make directory imports idempotent with reviewable identity conflicts | S4 | 1 |
| [#289](https://github.com/evanroden/msapo-generator/issues/289) — Keep directory selection usable when one record or logo is corrupt | S4 | 1 |
| [#292](https://github.com/evanroden/msapo-generator/issues/292) — Bound abandoned fixture runs while preserving shared originals | S5 | 5 |
| [#293](https://github.com/evanroden/msapo-generator/issues/293) — Release no-op preview holds without overtaking real edits | S5 | 2 |
| [#294](https://github.com/evanroden/msapo-generator/issues/294) — Keep Expense receipt corrections reachable and scope confirmations stable | S6 | 2 |
| [#295](https://github.com/evanroden/msapo-generator/issues/295) — Clean up owned conversion processes and removed receipt previews | S6 | 3 |
| [#296](https://github.com/evanroden/msapo-generator/issues/296) — Align generation preflight with renderer limits and package privacy | S5 | 3 |
| [#297](https://github.com/evanroden/msapo-generator/issues/297) — Preserve deliberate exclusions and source decisions across carry and re-entry | S3 | 4 |
| [#298](https://github.com/evanroden/msapo-generator/issues/298) — Make import readiness and recovery actions truthful and compact | S1 | 1 |
| [#299](https://github.com/evanroden/msapo-generator/issues/299) — Finish useful preview positioning and persistent section navigation | S1 | 5 |
| [#300](https://github.com/evanroden/msapo-generator/issues/300) — Finish one source workspace with one clear page and photo task | S3 | 1 |
| [#302](https://github.com/evanroden/msapo-generator/issues/302) — Verify recovery choices, history and partial generation outcomes | S5 | 2 |
| [#303](https://github.com/evanroden/msapo-generator/issues/303) — Close the remaining novice workflow and copy acceptance gaps | S1 | 1 |
| [#428](https://github.com/evanroden/msapo-generator/issues/428) — Remove deprecated fitz imports from PDF runtime and QA | S5 | 4 |
| [#434](https://github.com/evanroden/msapo-generator/issues/434) — Put current-month Training ahead of standing requirements | S4 | 9 |
| [#435](https://github.com/evanroden/msapo-generator/issues/435) — Open empty photo intake and pending caption editors automatically | S3 | 5 |
| [#436](https://github.com/evanroden/msapo-generator/issues/436) — Make per-contact editing reachable without nested Edit contacts disclosure | S4 | 6 |
| [#437](https://github.com/evanroden/msapo-generator/issues/437) — Expose uploaded-file reuse and the current Add destination directly | S3 | 1 |
| [#438](https://github.com/evanroden/msapo-generator/issues/438) — Shorten final review and report creation copy without hiding outcomes | S1 | 7 |
| [#439](https://github.com/evanroden/msapo-generator/issues/439) — Integrate a private in-site final PDF viewer with exact artifact identity | S3 | 7 |
| [#450](https://github.com/evanroden/msapo-generator/issues/450) — Track focused template compatibility and faster monthly section entry | S3 | 2 |
| [#451](https://github.com/evanroden/msapo-generator/issues/451) — Make MBCx PDF upload include the complete document in one action | S3 | 2 |
| [#454](https://github.com/evanroden/msapo-generator/issues/454) — Add an explicit schema adapter for annual multi-site work-order grids | S2 | 3 |
| [#455](https://github.com/evanroden/msapo-generator/issues/455) — Preserve vendor category bands as groups rather than contact rows | S2 | 5 |
| [#456](https://github.com/evanroden/msapo-generator/issues/456) — Offer one optional monthly Water update alongside attached reports | S3 | 3 |
| [#457](https://github.com/evanroden/msapo-generator/issues/457) — Map imported issue-register columns without losing existing issue cards | S2 | 6 |
| [#459](https://github.com/evanroden/msapo-generator/issues/459) — Keep an annual Training matrix reusable without repeating monthly entry | S4 | 9 |
| [#460](https://github.com/evanroden/msapo-generator/issues/460) — Generate a truthful contents page after section and attachment changes | S1 | 6 |
| [#462](https://github.com/evanroden/msapo-generator/issues/462) — Bound large artwork imports without rewriting original DOCX packages | S1 | 4 |
| [#463](https://github.com/evanroden/msapo-generator/issues/463) — Expose rasterized versus editable content in imported section review | S1 | 2 |
| [#464](https://github.com/evanroden/msapo-generator/issues/464) — Separate source instructions and example placeholders from report content | S1 | 2 |
| [#465](https://github.com/evanroden/msapo-generator/issues/465) — Provide read-only inspection and verified download of the installed master | S4 | 4 |
| [#466](https://github.com/evanroden/msapo-generator/issues/466) — Validate whole-page attachment geometry for mixed PDF page sizes | S3 | 2 |
| [#467](https://github.com/evanroden/msapo-generator/issues/467) — Detect floating text and unsupported drawings before lossy table extraction | S1 | 2 |
| [#468](https://github.com/evanroden/msapo-generator/issues/468) — Keep PDF batch limits visible before users invest in page review | S3 | 4 |
| [#470](https://github.com/evanroden/msapo-generator/issues/470) — [MR-008A] Define ownership and carryover rules for contract, site and monthly data | S4 | 5 |
| [#471](https://github.com/evanroden/msapo-generator/issues/471) — [MR-001] Verify and repair realistic-size Starting Report imports across all ingestion limits | S1 | 4 |
| [#472](https://github.com/evanroden/msapo-generator/issues/472) — [MR-002] Show the actual effective upload and parsing limits for each file route | S1 | 4 |
| [#473](https://github.com/evanroden/msapo-generator/issues/473) — [MR-005] Offer a consistent source replacement or retry path after import failure | S1 | 4 |
| [#474](https://github.com/evanroden/msapo-generator/issues/474) — [MR-007] Make organizational and workflow uploads contract-specific instead of universal | S4 | 2 |
| [#475](https://github.com/evanroden/msapo-generator/issues/475) — [MR-008B] Verify reusable contract content and source files survive reopen and monthly rollover | S4 | 5 |
| [#476](https://github.com/evanroden/msapo-generator/issues/476) — [MR-010A] Define a reviewable normalized work-order table with source provenance | S2 | 1 |
| [#477](https://github.com/evanroden/msapo-generator/issues/477) — [MR-009] Replace Activity table-number dropdowns with source-oriented entry | S2 | 4 |
| [#478](https://github.com/evanroden/msapo-generator/issues/478) — [MR-010B] Extend existing CSV work-order intake with editable column mapping | S2 | 1 |
| [#479](https://github.com/evanroden/msapo-generator/issues/479) — [MR-010C] Normalize work-order tables from PDF with visible uncertainty and provenance | S2 | 2 |
| [#480](https://github.com/evanroden/msapo-generator/issues/480) — [MR-010D] Normalize work-order tables from DOCX without losing native source structure | S2 | 2 |
| [#481](https://github.com/evanroden/msapo-generator/issues/481) — [MR-011] Calculate reviewable PM, non-PM and optional trade work-order counts | S2 | 1 |
| [#482](https://github.com/evanroden/msapo-generator/issues/482) — [MR-013] Make Monthly Scorecards a direct PDF upload with complete page inclusion | S3 | 2 |
| [#483](https://github.com/evanroden/msapo-generator/issues/483) — [MR-017] Map heterogeneous CMMS maintenance exports to editable service-call fields | S2 | 3 |
| [#486](https://github.com/evanroden/msapo-generator/issues/486) — [MR-014] Make thermal-capacity entry plainly labeled and separate from MBCx uploads | S4 | 7 |
| [#487](https://github.com/evanroden/msapo-generator/issues/487) — [MR-015] Make thermal capacity explicitly optional with persistent include/exclude behavior | S4 | 7 |
| [#488](https://github.com/evanroden/msapo-generator/issues/488) — [MR-018] Reuse subcontractor contact and status tables at contract scope | S4 | 6 |
| [#489](https://github.com/evanroden/msapo-generator/issues/489) — [MR-019A] Make Water Treatment report upload the primary Section 7 action | S3 | 3 |
| [#492](https://github.com/evanroden/msapo-generator/issues/492) — [MR-022] Import and reuse the Priority Capital Renewal list with explicit contract scope | S4 | 8 |
| [#493](https://github.com/evanroden/msapo-generator/issues/493) — [MR-023] Keep Section 10 Accounts Receivables identity consistent in contents, divider and body | S1 | 6 |
| [#495](https://github.com/evanroden/msapo-generator/issues/495) — [MR-025] Populate Pending and Declined Proposals from the already-supplied table | S2 | 6 |
| [#496](https://github.com/evanroden/msapo-generator/issues/496) — [MR-026] Import editable Training content from prior reports without false monthly completion | S4 | 9 |
| [#497](https://github.com/evanroden/msapo-generator/issues/497) — [MR-027] Populate Review preview without visiting or scrolling through every section | S1 | 5 |
| [#498](https://github.com/evanroden/msapo-generator/issues/498) — [MR-030] Separate optional source interpretation from deterministic report assembly | S5 | 3 |
| [#709](https://github.com/evanroden/msapo-generator/issues/709) — Reject colliding non-RRH catalog site identities before report selection | S4 | 1 |
| [#717](https://github.com/evanroden/msapo-generator/issues/717) — Prevent case-variant work-order IDs from inflating site-scoped CSV totals | S2 | 1 |
| [#725](https://github.com/evanroden/msapo-generator/issues/725) — Render imported native row summaries and custom editor headings literally | S1 | 5 |
| [#731](https://github.com/evanroden/msapo-generator/issues/731) — Keep pinned reports editable when company-master metadata is unavailable | S4 | 4 |
| [#737](https://github.com/evanroden/msapo-generator/issues/737) — Keep damaged outage-procedure metadata within the report recovery boundary | S4 | 3 |
| [#744](https://github.com/evanroden/msapo-generator/issues/744) — Bound existing chart-picture reads during default publication | S4 | 2 |
| [#748](https://github.com/evanroden/msapo-generator/issues/748) — Reject malformed chart site scopes before cross-site default selection | S4 | 2 |
| [#753](https://github.com/evanroden/msapo-generator/issues/753) — Make repeated procedure publication restore usable saved picture links | S4 | 3 |
| [#769](https://github.com/evanroden/msapo-generator/issues/769) — Bound unfinished-browser picture restoration at the existing size limit | S5 | 1 |
| [#770](https://github.com/evanroden/msapo-generator/issues/770) — Verify retained browser-recovery pictures before acknowledging unchanged saves | S5 | 1 |
| [#781](https://github.com/evanroden/msapo-generator/issues/781) — Bind browser recovery journal contents to the saved draft fingerprint | S5 | 1 |
| [#785](https://github.com/evanroden/msapo-generator/issues/785) — Reject malformed workflow picture bytes before contract-default publication | S4 | 3 |
| [#787](https://github.com/evanroden/msapo-generator/issues/787) — Reject hash-valid malformed organization-chart picture defaults | S4 | 2 |
| [#789](https://github.com/evanroden/msapo-generator/issues/789) — Do not invent vendor contacts from unnamed detail rows in merged trade bands | S2 | 5 |
| [#791](https://github.com/evanroden/msapo-generator/issues/791) — Keep impossible vendor report dates in source review instead of dropping them as metadata | S2 | 4 |

**Evidence to capture per step:** timestamp and exact About SHA; device/browser and whether physical or simulated; synthetic fixture filename and SHA-256; screenshots only of invented inputs; actual downloaded DOCX/PDF identity, selected page/row counts and observed pass/fail; any unrun or blocked subcheck. Record owner policy decisions separately on their issue (#470, #439, #450); do not imply acceptance from another issue's check.

**Not covered by these synthetic sessions:** authentic-file parity, unapproved reader/network inspection, private approved-reference equality, physical accessibility unless actually observed, and real production fault injection. Such requirements must remain explicitly pending.
