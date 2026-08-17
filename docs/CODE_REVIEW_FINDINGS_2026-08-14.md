---
document_type: code_review_findings
repository: evanroden/msapo-generator
branch: claude/unspecified-issue-wcx90t
base_commit: bc9e92d05e0f0a6a7c3fb26b76927b00478609e1
date: 2026-08-14
change_type: review_and_annotation
status: partial_review_complete_findings_unactioned
coverage: 17 of 29 app modules reviewed; 12 not reviewed (session limit)
---

# Code review findings: annotation pass, 2026-08-14

## 1. LLM quick context

A line-by-line review of the application, with LLM-ready comments written into
the code in place. This document is the part that could not go in the code: the
defects, the dead-code candidates, and the duplication.

**Nothing in sections 4-6 has been acted on.** The annotation commit changed no
executable code and deleted nothing, by design -- see §3.

### 1.1 The one thing to read if you read nothing else

The review found a **regression in the change immediately preceding it on this
branch** (`scope_region`, PR #48). An in-proposal warranty line truncated the
quoted scope, which killed the labour signal and routed a labour quote to
`5302-EQUIPMENT / OR - EQUIPMENT PO`. Fixed in `458bfd9`.

That is the second time in two days that a fix to the routing rules introduced a
new over-broad match. The pattern is worth naming: **each of these rules keys on
words that appear in more than one register** -- "service" as a verb and as a
product, "limited warranty" as a section heading and as prose. A change that
narrows one register tends to catch another. Test the new register explicitly.

## 2. Coverage -- read before assuming this review is complete

| Reviewed and annotated | Not reviewed |
|---|---|
| `web_ui.py` | `document_generator.py` |
| `expense_ui.py` | `pdf_converter.py` |
| `smartsheet.py` | `scope_pdf.py` |
| `smartsheet_store.py` | `ocr.py` |
| `smartsheet_ui.py` | `assets.py` |
| `smartsheet_inline.py` | `asset_guess.py` |
| `expense_report.py` | `equipment_policy.py` |
| `eml_builder.py` | `job_numbers.py` |
| `receipt_analyzer.py` | `quote_analyzer.py` |
| `po_context.py` | `analysis_schema.py` |
| `po_rules.py` | `config.py` |
| `workflow_review.py` | `run_web.py` |
| `workflow_state.py` | `pages/2_Smartsheet_PO.py` |
| `ui_highlight.py` | `scripts/patch_streamlit_metadata.py` |
| `memory.py` * | |
| `device_identity.py` * | |
| `contracts.py` * | |

The unreviewed files are **untouched**, not partially done.

\* `memory.py`, `device_identity.py` and `contracts.py` were annotated, but the
reviewer terminated before returning its findings. **Their comments exist; their
bug list does not.** Those three files should be re-reviewed. Treat their absence
from §4-6 as missing data, not as a clean bill of health.

## 3. Why the annotation commit is safe

A comment pass over 12,000 lines is only defensible if it provably changed
nothing. Two independent checks, because neither alone is sufficient:

1. **AST equivalence.** Every file parsed before and after, docstrings stripped
   from both sides (comments vanish at parse time; docstrings do not, being real
   string expressions), and the dumps compared. All 17: identical.
2. **Full suite.** 378 passed, 1 skipped -- identical to the pre-annotation
   baseline.

Check 2 is not redundant. This repository has tests that assert on raw **source
text** (`"Outlook" not in source`, `source.count("build_scope_pdf(") == 0`), so a
comment that merely *mentions* a forbidden string breaks the suite with no logic
change at all. The per-file forbidden list, the three pinned substring counts in
`web_ui.py`, and the secret-scanner patterns were each re-checked over the diff.

**If you add comments to this codebase, get that list first.** It is in
`tests/test_smartsheet_handoff_entrypoint.py`, `tests/test_dead_code_cleanup.py`,
`tests/test_device_identity.py`, `tests/test_expense_draft_state.py` and
`tests/test_public_repository_hygiene.py`.

## 4. Bugs found (23) -- none fixed here

Each was reported rather than fixed, so that a behaviour change never rides
along inside a comment commit. `failure_scenario` is the reproduction.

### 4.2 HIGH (2)

**`app/web_ui.py:2639`** — The corrected facility address returned by _routing_for_generation is discarded and the analyzer's raw address is written onto the generated MSAPO form, so a site correction produces a document with the right facility NAME above the wrong street address.

> Line 2641 unpacks `selected_contract, selected_site, facility_name, _ = _routing_for_generation(...)`; the fourth element (the address resolved from FACILITIES for the site the operator actually chose) is thrown away. Line 2639 then passes `facility_address_display=analysis.facility_address`. Concretely: the analyzer reads a quote as Clifton Springs Hospital & Clinic (2 Coulter Rd, Clifton Springs, NY 14432); the operator corrects Site to UMMC. `_routing_for_generation` returns ('Rochester Regional Health', 'UMMC', 'United Memorial Medical Center', '127 North St, Batavia, NY 14020'). The rendered MSAPO PDF -- the document contract administration signs -- prints "Facility: United Memorial Medical Center" followed by "2 Coulter Rd, Clifton Springs, NY 14432". Meanwhile po_context._routing_fields computes the CORRECT Batavia address for the Smartsheet facility_address field, so the form and its own attachment disagree with no warning anywhere. The docstring on document_generator's helper states the override exists precisely so "a user's corrected routing choice is reflected in the attachment".

**`app/expense_report.py:1252`** — _compact_receipt_image's alpha-flatten branch does not cover palette images, so a GIF or PNG-8 receipt with transparency is silently rendered fully black in the RECEIPTS worksheet, in the approver's PDF, and in the vision payload sent to the model.

> Reproduced directly. A PNG-8 (mode "P", info["transparency"] set) receipt with black text on a transparent background enters the branch because "transparency" in image.info is True, but "A" is not among a P-mode image's bands (("P",)), so alpha is None and background.paste(image.convert("RGB"), mask=None) is a plain overwrite -- the flatten never happens and image.convert("RGB") maps the transparent pixels to their palette colour. Verified: receipt_attachment_pages(png8_bytes, "r.png") returns a JPEG whose luminance extrema are (0, 0), i.e. every pixel black; the receipt text is gone. Mode "PA" misses the branch entirely and falls to the same bare convert("RGB"). No exception, no warning: the workbook, the emailed PDF packet, and receipt_preview_bytes (which is what analyze_receipt sends to the model for images) all carry a black rectangle. app/ocr.py:123-129 already carries the correct form of this fix from the 2026-08-12 hardening pass ("Transparency was dropped onto black"); this call site was not updated with it.

### 4.3 MEDIUM (8)

**`app/web_ui.py:2214`** — needs.any can never return to False (retain_review_needs is monotonic), so the "Needed from you" banner and the yellow needs-a-value highlight stay on permanently once anything was ever unresolved -- including on fields that are now filled and while the generate button is enabled.

> Paste a quote whose vendor name the analyzer misses. `review_needs` sets vendor=True; `retain_review_needs` ORs it into session key review_needs_{token} and every later rerun ORs again, so needs.vendor stays True forever. Fill vendor, total, description, contact name, contact email, requester -- draft_problems is now empty and the generate button is enabled -- yet line 2214 still renders "The tool could not safely determine one or more values below" and line 2433 still emits the st-key-po_needs_you highlight over a container of fully-completed fields. The operator is told values are missing while nothing is. This contradicts both the CSS comment in this file ("The highlight disappears on the rerun after the field is filled") and ui_highlight.highlight_needed_fields' docstring ("a field stops being highlighted on the run after it is filled"). It is invisible in tests because test_needs_value_highlight uses the synthetic sample, where the requester is the only thing ever needed and needs.any is False throughout.

**`app/web_ui.py:820`** — _routing_snapshot does not recognise CONTRACT_PLACEHOLDER/SITE_PLACEHOLDER as an explicit deselection, so deselecting the contract or site leaves the routing controls hidden inside the collapsed corrections panel while the pre-generation warning demands them.

> `contract_options = set(contracts.contract_names())` (line 820) and `SITE_LABELS` (line 833) contain no placeholder, so a stored placeholder reads as "nothing stored" and the function falls through to the analyzer's detected contract/site. `_render_routing_controls` (line 1090+) instead treats a placeholder as an explicit "not chosen" and returns empty strings. Repro: load the synthetic sample (contract and site detected, so needs.routing is False from the first render and the routing block lives in the collapsed panel). Open the corrections panel and set Site to "— Select a site —". On the rerun, `_routing_snapshot` reports site=UMMC/CSHC by default, category and cost code resolve, `routing_ready` is True, needs.routing stays False -- so the Site selectbox is rendered inside the collapsed panel and no "Needed from you" banner appears -- while draft_problems shows "Before generating: choose the site" and the button is disabled. The tool demands a value and hides the only control that supplies it. Same shape for the contract, where the snapshot additionally re-adopts a contract the operator just backed out of.

**`app/expense_ui.py:1653`** — _recall_approver_email wipes the configured RRH approver email whenever the operator re-selects the seeded approver name, because it consults only expense_approvers() (confirmed history) and never the RRH_APPROVER_NAME/RRH_APPROVER_EMAIL pair that _seed_profile used to fill both fields.

> Fresh browser (or fresh data_store), account = Rochester Regional Health. _seed_profile fills expense_approver_name_<tok> = RRH_APPROVER_NAME and expense_approver_email_<tok> = RRH_APPROVER_EMAIL from app.config. expense_approvers('Rochester Regional Health') returns [] because no report has ever been generated on this deployment (the query requires use_count>=1). The operator opens the approver dropdown to check the name and re-picks the same entry. on_change fires _recall_approver_email; the loop over `remembered` finds no match, so line 1653 sets the email field to "". The correct, configured approver address is gone and the operator must retype it before Generate re-enables. Same path for any approver the operator typed earlier in the session but has not yet generated a report with.

**`app/smartsheet.py:1020`** — handoff_rows emits raw values while build_prefilled_form_url emits _mapped_value-translated ones, so the manual copy fallback and the prefill URL disagree whenever SMARTSHEET_FORM_VALUE_MAP_JSON is configured.

> Configure SMARTSHEET_FORM_VALUE_MAP_JSON={"object_account":{"5301-MATERIALS":"5301 - Materials"}} (the FM-D04 control, currently unset in render.yaml). build_prefilled_form_url correctly encodes OBJECT ACCOUNT=5301 - Materials. handoff_rows returns str(value).strip() with no map applied, so the troubleshooting copy list shows '5301-MATERIALS'. An operator whose prefill did not take -- an expired Smartsheet session, which is exactly the case that fallback exists for -- copies '5301-MATERIALS' into a dropdown that has no such option. The dropdown stays on its placeholder and the PO is submitted with no object account. Nothing raises at any layer: validate_submission_fields validates the canonical (unmapped) value, so it passes too.

**`app/smartsheet_inline.py:217`** — Prefill skip reasons for non-required fields are reported only inside a collapsed expander, so a populated value silently vanishes from the form link.

> A PO carries a long ADDITIONAL INFORMATION IF NEEDED note whose percent-encoded form pushes the candidate URL past SMARTSHEET_PREFILL_MAX_URL_LENGTH (7000). build_prefilled_form_url drops it and records skipped=['instructions: URL length limit reached']. 'instructions' is not in DEFAULT_FORM_REQUIRED_FIELDS, so prefilled.missing_required is empty, the link renders normally at line 202, and the only mention of the dropped value is the st.warning at line 218 -- inside st.expander(..., expanded=False). The operator opens the form, sees every field they expect, and submits the PO with the vendor note gone. Same shape for asset_id whenever its label mapping is absent ('no exact label mapping' skip). Additionally the expander's warning text says the values 'did not fit in the custom URL', which is wrong for the mapping-missing case.

**`app/expense_report.py:425`** — mileage_reimbursement quantizes with Decimal's default ROUND_HALF_EVEN while the workbook cell it accompanies is =ROUND(G*rate,2), which is half-up, so the total quoted in the approval email can trail the form's own Q60 by one cent.

> A mileage row of 1.15 miles at the 2025 rate of $0.70 gives Decimal("0.8050"); .quantize(Decimal("0.01")) with the default rounding yields 0.80, while Excel/LibreOffice evaluating =ROUND(G10*0.70,2) in the same row yields 0.81. total_reimbursement therefore reports a figure one cent below the form's =H18+H39+H59, and that Python figure is what ExpensePackage.total carries into the approval email body ("Total reimbursement: $X"). The approver receives an email and an attached form that disagree, with nothing indicating which is authoritative. Any miles x rate product landing exactly on a half-cent reproduces it; app/expense_ui._selected_receipt_item_amount already uses ROUND_HALF_UP explicitly, so the codebase is internally inconsistent about this.

**`app/po_rules.py:420`** — _is_parts_purchase vetoes the Group A match for the WHOLE scope, so a quote that buys a complete unit AND mentions any spare part is routed to Materials -- discarding the mixed-quote handling equipment_policy deliberately implements.

> infer_purchase_route('Purchase one new 500-ton chiller. Freight and spare filters included.') returns materials_purchase; classify_po(route, '48000.00') then yields 5301-MATERIALS / 'OR - STANDARD PO OVER $25K'. Dropping the four words 'and spare filters included' returns equipment_purchase -> 5302-EQUIPMENT / 'OR - EQUIPMENT PO'. equipment_policy._has_explicit_whole_unit exists precisely to keep recognising the complete unit in a mixed quote (test_po_rules.py:128 pins group_a_equipment_match('Provide chiller parts and purchase one new boiler') == 'Chiller'), but the crude veto at this line overrides it. No test exercises infer_purchase_route on a mixed quote. The wrong Object Account is invisible downstream -- it simply appears in Smartsheet as a confident answer.

**`app/po_rules.py:239`** — scope_region cuts at the first boilerplate heading anywhere past 200 chars, and 'limited warranty' is one of them -- so an ordinary in-proposal warranty line truncates the rest of the real scope, silently.

> A 518-character proposal reading 'Supply and deliver replacement air filters, gaskets and belts... Limited Warranty: twelve months on all supplied materials from date of shipment. Additional scope: our service technician will be onsite for two days to install the replacement components and commission the unit...' keeps only 267 characters. The onsite-labour sentence is discarded, so infer_purchase_route returns materials_purchase (5301-MATERIALS / 'ON - STANDARD PO UNDER $25K') even though _labor_signal on the full text is True (onsite_labor -> 5511-SUBCONTRACTOR / '03 - MSAPO (SERVICE)'). Nothing errors and nothing is displayed differently. It also feeds route_uncertain, so the disagreement heuristic degrades on exactly these documents. Note this is the inverse of the defect the function was added to fix, so any narrowing must be re-measured against tests/test_scope_region.py rather than applied blind.

### 4.4 LOW (13)

**`app/web_ui.py:2367`** — Typing the optional Smartsheet note makes both the note and the toggle that revealed it disappear from the visible page on the very next rerun.

> `instructions_value` is read from session state at line 2005, before any widget renders. While it is empty the field lives behind the toggle at line 2440; once it holds text the branch at line 2367 renders it inside the collapsed `corrections` expander instead, and the `not instructions_value` short-circuit removes the toggle entirely. So: turn on "Add Additional Information", type "Vendor requires PO by Friday", tab out. On the resulting rerun the toggle is gone and the note is inside a collapsed panel titled as though it held values the tool had filled. The text is retained and does reach Smartsheet, but the operator sees it vanish with no confirmation and has no visible control to re-enter it.

**`app/expense_ui.py:694`** — The signature-preview guard catches only ExpenseReportError, so any other exception from employee_signature_png (Pillow OSError on an unreadable/corrupt font file) escapes render_expense_workflow and blanks the whole page after the operator has entered the entire report.

> The image is rebased and fonts-urw-base35 ships a font file that exists (Path.is_file() is True, so the ExpenseReportError 'font unavailable' branch is not taken) but cannot be parsed -- ImageFont.truetype raises OSError('cannot open resource'). st.error is never reached; the exception propagates out of render_expense_workflow, Streamlit renders its traceback box, and every receipt line, allocation and mileage row entered so far is unreachable. This is the same class of loss that docs/COMMIT_NOTES_2026-08-12_CORRECTNESS_AND_FAILURE_MODE_HARDENING.md section 4.1 widened to `except Exception` on the generation path; this call site was not widened with it.

**`app/expense_ui.py:1693`** — The report date seeds from date.today() in the container's timezone (UTC -- nothing sets TZ in Dockerfile, render.yaml or docker-compose.yml), so a US operator filing in the evening gets tomorrow's date, and mileage travel dates inherit it through the track-the-default protocol.

> Operator in US Eastern opens the expense workflow at 20:30 on 2026-12-31. date.today() on the container is already 2027-01-01, so expense_report_date_<tok> seeds to 2027-01-01 and every mileage row's travel date follows it. irs_business_mileage_rate() has no band past 2026-12-31, returns None, and _render_mileage_entries emits 'The IRS business-mileage rate for 2027-01-01 has not been configured yet' plus a blocking 'configured IRS mileage rate' problem on every row -- for a trip that actually happened in December. On an ordinary evening the milder version is a report dated one day in the future, which expense_report_warnings then flags as 'Receipt N is dated after the report date'.

**`app/expense_ui.py:2334`** — Operator-precedence slip in _clear_removed_receipts: `receipt_id in key or token in key and key.startswith("expense_")` parses as `receipt_id in key or (token in key and key.startswith(...))`, so the full-hash branch pops session keys with no expense_ prefix guard at all.

> Any non-expense session key embedding a receipt's 64-hex content hash is silently deleted when that receipt is removed. No such key exists today (only expense_receipt_analysis_* and expense_preview_* carry the full hash), so this is latent rather than live -- but the expression reads as if both branches are prefix-guarded, and a future feature storing a receipt hash under a non-expense_ key (a shared OCR cache, a cross-workflow attachment index) would have its entry removed by the expense workflow with no error. The identical expression is repeated at line 2338 for the draft snapshot.

**`app/expense_ui.py:277`** — Re-selecting a file already held in the receipt mirror is dropped silently: the duplicate warning is computed from the current upload batch alone, while _merge_receipt_sources de-duplicates against the mirror without reporting anything.

> Operator uploads receipt A, switches to the Purchase Order workflow and back (so the uploader widget is empty and A lives only in expense_receipt_files), then re-selects A in the file dialog because the uploader looks empty. _unique_receipts(current_uploads) sees one file and reports no duplicates; _merge_receipt_sources drops A as an existing hash. The upload appears to do nothing at all -- no new card, no warning, no explanation. The only feedback is that A's existing card is already on screen.

**`app/smartsheet.py:1096`** — preflight_attachments continues past an empty file before registering its name, so that name never participates in duplicate detection.

> preflight_attachments([("quote.pdf", b""), ("quote.pdf", b"%PDF-1.4")]) returns only ('quote.pdf is empty or unreadable.',) and never 'Attachment filename is duplicated: quote.pdf.'. Impact is contained today because the empty-file problem alone blocks the submission, but the duplicate-name check is the FM-B03 control and it is inert for any pair where one member is empty -- if the empty-file check is ever softened to a warning, two indistinguishable attachments reach the row with no report.

**`app/smartsheet_store.py:91`** — SubmissionStore.from_environment has no /test1 fallback, diverging from app/memory.py::_data_dir, so losing EPC_DATA_DIR silently moves idempotency state to ephemeral storage while other memory keeps working.

> render.yaml sets EPC_DATA_DIR=/test1 (the mounted persistent disk). docs/SMARTSHEET_PO_IMPLEMENTATION_HANDOFF_2026-08-04.md explicitly warns that Render dashboard values shadow the blueprint. If that variable is removed or overridden to empty, app/memory.py::_data_dir still finds the disk via its own Path('/test1').is_dir() fallback and requester/vendor memory keeps working, while SubmissionStore falls back to './data_store' relative to the container CWD. Duplicate-prevention history is then wiped on every deploy, a re-submitted identical PO is claimed as 'new' (reason='new', not 'complete'), and a second row is created. Not currently reachable because SMARTSHEET_API_MODE=disabled in production, which is why this is low rather than critical.

**`app/smartsheet_inline.py:89`** — st.success(summary) renders a green readiness banner before the blocker check, so a package that cannot be submitted still shows a success confirmation.

> A context with warnings (e.g. 'Confirm the job cost code before submission.') or a field problem (contact_email fails _EMAIL_RE) reaches render_inline_smartsheet_handoff. Lines 74 and 89-93 print '#### Your files and Smartsheet link are ready' and a green st.success banner with the PO summary; only at line 99 does the st.warning listing the blockers appear below it. On a phone the green banner is what is visible without scrolling, which is the opposite of the intended fail-closed signal.

**`app/expense_report.py:534`** — "Receipt N" in validate_expense_report counts reimbursement LINES, while the UI cards and the RECEIPTS worksheet headers count unique SOURCE receipts, so on a split receipt the blocking message points at a card number that does not exist.

> Upload two receipts and split the first into two lines. items is then [line1a, line1b, line2]. validate_expense_report enumerates items and emits "Receipt 3: enter the transaction date" for the second upload. app/expense_ui.py renders cards with enumerate(unique_uploads, 1), so only "Receipt 1" and "Receipt 2" exist on screen; expense_report_warnings numbers by source and also says "Receipt 2"; _build_receipt_sheet labels it "Receipt 2 of 2". The operator is told to fix a receipt that is not on the page. Purely a labelling defect -- the gate itself is correct -- but it fires on exactly the reports that are hardest to reconcile.

**`app/receipt_analyzer.py:424`** — _call_with_retry sleeps after the FINAL attempt, so a persistently rate-limited receipt burns an extra nine seconds inside the user-facing spinner before raising, and non-status transport errors are not retried at all despite the documented retry policy.

> With max_retries=3 and a steady 429, attempt 2 (the last) sleeps (2+1)*3 = 9 seconds, continues, the for loop ends, and the function immediately raises last_error. The sleep buys nothing. Because analyze_receipt wraps this in a two-iteration shape loop, the worst case adds 18 seconds of pure dead wait to a failure the employee is watching a spinner for. Separately, the except clause names only anthropic.APIStatusError, so anthropic.APIConnectionError / APITimeoutError (a dropped connection, a DNS blip) propagate on the first occurrence with no retry -- docs/EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md states that transient errors use bounded retries, which is true for HTTP status codes only.

**`app/receipt_analyzer.py:508`** — _line_items applies the _MAX_LINE_ITEMS slice to the RAW list, so rejected rows consume the budget and the accompanying note can claim 60 items are shown when far fewer survived.

> A model response with 70 line_items entries of which 20 are summary/tender rows: value[:60] keeps the first 60 raw entries, ~17 of which are dropped by _looks_like_receipt_summary, leaving ~43 checkboxes. len(value) > 60 is true, so the note reads "Only the first 60 detected receipt items are shown." The employee is told 60 items are present, sees 43, and the 10 genuine purchased items in positions 61-70 are absent with only the generic "one or more unreadable rows were omitted" note to hint at it. Because every surviving checkbox starts ticked and expense_ui allocates the charged total proportionally across the selection, the calculated amount is derived from an item list the employee has been told is complete.

**`app/eml_builder.py:150`** — build_eml accepts an empty attachments list and silently produces a single-part text/html draft whose body still describes an attached report, with no error anywhere.

> email_attachments_for_package returns [] whenever package.pdf_bytes is falsy. If any future caller passes that straight into build_eml (the current one, app/expense_ui._build_expense_eml, raises first -- that guard is the only thing preventing it), the loop body never executes, msg stays a single-part text/html message, and the employee downloads a draft whose greeting reads "please review and approve the attached expense report" carrying nothing. Outlook opens it normally; nothing in the browser, the .eml, or the mail client reports a problem. The failure surfaces only when the approver asks where the report is.

**`app/po_context.py:435`** — _document_signature hashes the operator's CORRECTED vendor, but document_generator prints analysis.vendor_name -- so correcting the vendor forces a regeneration that does not actually change the vendor on the attached form.

> Operator corrects the vendor field from the analyzer's 'Trane Co' to 'Trane U.S. Inc.'. The signature changes, build_po_context blocks with 'Regenerate it' (pinned by test_vendor_change_invalidates_the_vendor_bearing_scope_pdf), the operator regenerates -- and document_generator.py:166 renders `f"Vendor: {analysis.vendor_name}"` from the un-replaced analysis. The Smartsheet VENDOR cell reads 'Trane U.S. Inc.' while the attached MSAPO form the administrator signs still reads 'Trane Co'. build_msapo_pdf already takes `scope` explicitly for exactly this class of problem (COMMIT_NOTES_2026-08-12_MSAPO_FORM_RESTORED §2.2) but takes no vendor override. Fix belongs in build_msapo_pdf/web_ui, not by removing vendor from this payload -- that would only hide the divergence.

## 5. Dead-code candidates (21) -- nothing removed

Grouped by confidence. Entries marked NOT DEAD are recorded deliberately:
they look unused and are not, so the next reader does not delete them.

### 5.1 high confidence (8)

| Location | Symbol | Kind | Evidence |
|---|---|---|---|
| `app/web_ui.py` | `CUSTOM_CSS rule .epc-needs-value` | constant | `grep -rn "epc-needs-value" app/ pages/ tests/ branding/` returns exactly one hit -- the rule definition at app/web_ui.py:337. No element anywhere is given the class. `git log -S "epc-needs-value"` shows it entered in c7e772e ("Highlight fields that still need a value"), the same commit that created app/ui_highlight.py, which emits the identical five declarations (background #FCFCF3, 4px yellow left border, 4px radius, same padding/margin) inline per rerun. Per COMMIT_NOTES_2026-08-13_EXPENSE_DISCLOSURE §3.2, emitting from the caller rather than baking it into CUSTOM_CSS is exactly what makes the highlight transient, so this baked copy is the superseded half. NOTE: its comment block is the only surviving record of WHY the mark is a left bar rather than an outline -- preserve that text if the rule is ever removed. |
| `app/web_ui.py` | `CUSTOM_CSS rules .scope-section and .scope-text` | constant | `grep -rn "scope-section\\|scope-text" app/ pages/ tests/` returns only the two rule definitions (app/web_ui.py:372 and :390). The sibling `.scope-label` in the same block IS emitted, at lines 2185 and 2197. `git log -S "scope-section"` last touched it in c466322; the read-only scope preview it styled was replaced by the editable Scope of Work text area plus the inclusion/exclusion checkbox columns. |
| `app/web_ui.py` | `"navy" class token on the step-1 header` | constant | `grep -rn "navy" --include=*.py --include=*.toml --include=*.md .` over the whole repository returns exactly one hit: the markup at app/web_ui.py:1589. There is no `.navy` or `.step-num.navy` rule in CUSTOM_CSS, in .streamlit/config.toml, or anywhere else. It matches nothing and is invisible only because the base `.step-num` already paints the ocean colour -- the same silent selector-matches-nothing shape this codebase has been bitten by before. The sibling modifier `.step-num.yellow` (line 262) is real and is used on step 3. |
| `app/expense_report.py` | `ALLOCATION_KINDS` | constant | `rg -w ALLOCATION_KINDS` across the whole repo (excluding __pycache__) returns exactly one hit: the definition at app/expense_report.py:96. No app/ module, no test, no page, no getattr/importlib access. The actual job-only gate is the `!= ALLOCATION_JOB` comparison in allocation_problems and again in _fill_allocation, so this tuple enforces nothing. It is a comment-with-a-value rather than a switch -- note that WIDENING it would not re-enable work orders, which is a trap for a later reader. |
| `app/expense_report.py` | `EXPENSE_SECTIONS` | constant | `rg -w 'EXPENSE_SECTIONS'` returns only the definition at app/expense_report.py:77. EXPENSE_SECTION_MISC and EXPENSE_SECTION_ENTERTAINMENT are heavily used individually (app/expense_ui.py, app/receipt_analyzer.py, tests), but the pairing tuple has no reader. Its only value today is documenting that the two are the complete set. |
| `app/po_context.py` | `_existing_path` | function | `rg -n "existing_path" .` across the whole repo (excluding *.pyc) returns exactly one hit: its own definition at app/po_context.py:181. No tests, no pages/, no scripts/. `rg -n "importlib\|getattr\\(po_context" .` returns nothing, so no dynamic reach. It is underscore-private, so no external import is possible. It is a leftover from the era when the generated document travelled as a filesystem path; the 2026-08-12 MSAPO reversal made build_msapo_pdf return bytes and nothing has needed a Path since. |
| `app/po_rules.py` | `asset_id_is_numeric` | function | `rg -n "asset_id_is_numeric\|is_numeric" .` (excluding *.pyc) returns only the definition at app/po_rules.py:458. It is not in tests/test_po_rules.py's import list, not imported by web_ui.py (which imports normalize_asset_id and parse_amount only), and not referenced in docs/ or pages/. Its name is also now inaccurate -- it returns True for 'EEA-CWP-07' and for '' -- because the five-digit JDE assumption it was written for was reversed. Its 160-character limit is re-implemented independently at app/po_context.py:911. |
| `app/po_context.py` | `PREPARED_PO_CONTEXT_STATE_KEY` | constant | `rg -n "PREPARED_PO_CONTEXT_STATE_KEY" .` and `rg -n "_prepared_smartsheet_po_context" .` (excluding *.pyc) each return the definition plus one prose mention in docs/SMARTSHEET_PO_IMPLEMENTATION_HANDOFF_2026-08-04.md:708. No code reads or writes the key; web_ui passes the POContext object straight to smartsheet_inline.render_inline_smartsheet_handoff instead of parking it in session state. The doc describes an architecture that was not built. |

### 5.2 medium confidence (5)

| Location | Symbol | Kind | Evidence |
|---|---|---|---|
| `app/web_ui.py` | `uploaded = None` | constant | Line 1615 pre-initialises `uploaded`, but the name is read only at lines 1634, 1635, 1637 and 1655, all inside the `if input_mode == UPLOAD_MODE:` block that reassigns it at line 1618. In the PASTE_MODE branch the None is never read. The two sibling pre-initialisations on the same lines (`uploaded_text`, `pasted_text`) ARE read afterwards at the choose_quote_text call, so only this one is inert. Trivial, and it does document the symmetry of the three-way branch; listed for completeness, not as a recommendation. |
| `app/expense_ui.py` | `_seed_profile return value` | function | `grep -rn "_seed_profile" --include=*.py .` returns only the definition (app/expense_ui.py:1673) and the single call site at app/expense_ui.py:387, which is a bare statement discarding the result. No test, Streamlit page, getattr or importlib reference exists. The FUNCTION is very much alive (it seeds every step-2 widget); only its `-> dict[str, str]` return is unused. |
| `app/smartsheet.py` | `SmartsheetConfig.column_map` | function | rg -n "\bcolumn_map\b" --iglob '!*.pyc' across the whole repo returns only the definition at app/smartsheet.py:280. No test, no Streamlit page, no docs reference, and no getattr/importlib indirection. Every write path uses config.column_specs directly (ColumnSpec carries the title/type verification that this property discards). |
| `app/expense_report.py` | `receipt_attachment_pages(max_pages=...)` | parameter | `rg -n max_pages` shows the keyword is never supplied by any caller: receipt_preview_bytes passes only render_limit=1, _build_receipt_sheet passes neither, and no test overrides it. It is always _MAX_RECEIPT_PAGES_PER_FILE. Genuinely useful as a named seam for a future per-caller limit, and the docstring distinguishes it from render_limit, so this is reported for completeness rather than as a removal recommendation. |
| `app/po_context.py` | `_LOCKED_FIELDS / POContext.locked_fields` | constant | `rg -n "locked_fields\|_LOCKED_FIELDS" .` (excluding *.pyc) returns only app/po_context.py:82 (definition) and :157 (the dataclass default). app/smartsheet_inline.py -- the only consumer of POContext -- reads fields, warnings, attachments, attachment_base and context_id (verified by `rg -n "context\\." app/smartsheet_inline.py`) and never locked_fields; it builds its own read-only display. Lower confidence than the others because it is a PUBLIC attribute of a public dataclass, so an external or future caller could legitimately depend on it, and the 22-name tuple is a useful record of intent even unenforced. |

### 5.3 low confidence (8)

| Location | Symbol | Kind | Evidence |
|---|---|---|---|
| `app/web_ui.py` | `_pricing_difference` | function | `grep -rn "_pricing_difference" --include=*.py .` returns the definition (app/web_ui.py:552) and three assertions in tests/test_web_ui_helpers.py:29-31. No production call site remains: the live subtotal+tax vs total reconciliation is po_context.build_po_context lines 540-545, which raises the same comparison as a submission warning with a Decimal("0.01") tolerance this helper does not have. EXPLICITLY NOT DEAD by this project's rule -- it is imported and exercised by the test suite, so removing it breaks tests. Flagged only so the next author knows the money rules have a second, tolerance-free copy here. |
| `app/expense_ui.py` | `_unique_receipts non-tuple branch (line 2236)` | branch | Both call sites pass lists of 3-tuples: line 277 passes `current_uploads`, built as `(upload.name, upload.getvalue(), upload.type or ...)`, and line 297 passes `upload_sources`, which is either `_merge_receipt_sources(...)` output or `st.session_state["expense_receipt_files"]` -- and the only writers of that key write tuples. `grep -rn "_unique_receipts"` finds no caller outside this module and no test. So `filename, payload = upload.name, upload.getvalue()` is unreachable today. RETAIN: one line of shape tolerance on a path where the tuple/object shapes have been swapped before; removing it turns a future regression into a crash instead of a no-op. |
| `app/expense_ui.py` | `_merge_receipt_sources non-tuple branch (lines 2264-2266)` | branch | Same evidence: the single call site (line 282) passes `mirrored_uploads` (from expense_receipt_files, always tuples) and `current_uploads` (built as tuples at line 271). `grep -rn "_merge_receipt_sources"` finds no external caller and no test. Unreachable today; same reason to keep. |
| `app/smartsheet.py` | `validate_column_mapping` | function | rg -n "validate_column_mapping" --iglob '!*.pyc' across the repo returns only the definition at app/smartsheet.py:1239. NOT dead: it is the operator-facing read-only twin of the schema check submit_po performs inline (both share _column_problems), and it serves the API route that ships deliberately disabled (SMARTSHEET_API_MODE=disabled in render.yaml). Absence of callers is the designed state per docs/FAILURE_MODES_AND_CONTROLS.md FM-E01, not evidence of obsolescence. Do not remove. |
| `app/smartsheet.py` | `reconcile_submission` | function | rg -n "reconcile_submission" --iglob '!*.pyc' returns only the definition at app/smartsheet.py:1601 plus the module-docstring reference in app/smartsheet_store.py. NOT dead: docs/FAILURE_MODES_AND_CONTROLS.md names it as the recovery step for FM-F04 and FM-F06, and SubmissionStore.reconcile_row exists solely to serve it (and is exercised by tests/test_smartsheet_store.py:75,83). Removing it would strip the only exit from the 'uncertain' state. Do not remove. |
| `app/smartsheet_store.py` | `SubmissionStore.get` | function | Defined at app/smartsheet_store.py:476 and referenced only by tests/test_smartsheet_store.py:87,130,144. Per the stated rule, test-only usage is not dead. It is the read-only inspection accessor; submit_po deliberately uses claim() instead because claim is atomic. |
| `app/smartsheet.py` | `RRH_JOB_NUMBERS` | import | Imported at app/smartsheet.py:46 from app.job_numbers but never referenced in this module's body (only JOB_NUMBER_OPTIONS is, at line 133 in _EXACT_OPTIONS). It is a live RE-EXPORT: tests/test_smartsheet_config.py:13 does `from app.smartsheet import ... RRH_JOB_NUMBERS` and asserts its exact contents at line 92. Deleting the import breaks that test. NOT dead. |
| `app/expense_report.py` | `image_buffers / buffers (parameter threaded through _fill_report_header and _build_receipt_sheet)` | parameter | The list at app/expense_report.py:822 is created, passed to both helpers, appended to, and never READ -- no len(), no iteration, no close(). Its apparent purpose is keeping each BytesIO referenced until workbook.save(). Inspecting the pinned openpyxl 3.1.5, drawing.image.Image.__init__ does `self.ref = img` and Worksheet.add_image appends the Image to ws._images, so each buffer is already reachable from the workbook and cannot be collected early. LOW confidence deliberately: this is a lifetime guard pinned to a library internal, requirements.txt allows openpyxl>=3.1.5,<4.0.0, and Image._data() closes the caller's BytesIO during save. Removal needs a verified render against the pinned range, not a reading of the current source. Do not remove in a comment pass. |

## 6. Redundancy (16)

1. _strip_ai_wrapper is duplicated verbatim in app/web_ui.py:588 and app/po_context.py:166, and _build_unified_lists (web_ui:602) reimplements the same ordering and de-duplication as po_context._unified_review_items (po_context:171). The duplication is load-bearing rather than accidental: the inclusion/exclusion checkbox keys are POSITIONAL (inc_<token>_<index>, exc_<token>_<index>) and po_context rebuilds the lists to map each index back to an item. The two currently agree exactly. If they ever diverge -- one sorts, one filters an empty entry, one changes the de-dup rule -- the lists shift by an entry and po_context attributes the operator's ticks to the WRONG inclusions on both the generated PDF and the Smartsheet scope text, with no exception anywhere.
   - Files: `app/web_ui.py`, `app/po_context.py`
   - Suggestion: Do not merely delete one copy; the module import direction has to be checked first (po_context must not import the Streamlit page). Extract the unwrapping and list-building into a third pure module that both import, so the positional contract has a single definition. Until then, treat the two as a matched pair and change both or neither.

2. The routing defaults are implemented twice: _routing_snapshot (read-only, decides placement before render) and _render_routing_controls (renders and returns the same six values). They already disagree on the placeholder sentinels -- see the reported bug -- and each additionally re-derives the cost code and category from FACILITIES/lookup_cost_code. A third partial copy of the same selection rules lives in po_context._selected_contract/_selected_site/_routing_fields.
   - Files: `app/web_ui.py`, `app/po_context.py`
   - Suggestion: Do not collapse the render and snapshot functions -- the snapshot must not instantiate widgets, and a shared function that sometimes renders would be worse. Instead pull the pure default-resolution (given session state, contract, site, return category/cost code/site key) into one helper the renderer, the snapshot and po_context all call, so a placeholder is defined as 'not chosen' in exactly one place.

3. CONTRACT_PLACEHOLDER, SITE_PLACEHOLDER and ASSET_NONE are defined in app/web_ui.py:110-114 and independently redefined as _CONTRACT_PLACEHOLDER, _SITE_PLACEHOLDER and an inline "None Applicable" literal in app/po_context.py:35-36 and :162-163, with a third case-folded copy of the asset literal in po_rules.normalize_asset_id.
   - Files: `app/web_ui.py`, `app/po_context.py`, `app/po_rules.py`
   - Suggestion: Have po_context import the literals rather than restate them (the dependency already runs that way for other names). Until then, note that a change on one side raises nothing -- po_context simply stops recognising the sentinel and exports the em-dash prompt text into the Smartsheet SITE field as if the operator had typed it.

4. The job-number default is seeded twice per rerun with subtly different option sets: main() lines 2007-2031 (pre-render, using routing_snapshot.contract, validating against {JOB_NUMBER_PLACEHOLDER, *job_options} -- which admits the placeholder even for RRH) and again at lines 2270-2291 (post-render, using the rendered contract, validating against selectable_job_options -- which omits the placeholder for RRH). The seeding expression itself is copied verbatim.
   - Files: `app/web_ui.py`
   - Suggestion: Factor the default into one helper taking (contract, rrh, options, suggestion). The mismatch is currently self-healing -- the second block repairs anything the first admits -- but it means needs.job_number can be computed from a value the selectbox will immediately reject, which is exactly the kind of one-rerun placement flicker retain_review_needs exists to hide.

5. _asset_control_data runs the full guessing chain (guess_asset_id/contracts.guess_uid, guess_asset_uid, and sometimes lowest_numbered_of_type over the whole quote text) twice on every rerun -- once from main() at line 2033 for placement and once inside _render_asset_control at line 1387 for the options. Separately, build_po_context is called twice on the run where the generate button is pressed (lines 2615 and 2638), and account_manager_memory_context_id/vendor_contact_memory_context_id each re-hash the full attachment set again, so a 30MB quote is SHA-256'd four or more times in that one run.
   - Files: `app/web_ui.py`
   - Suggestion: Both duplicates are currently correct and the second build_po_context call is genuinely required (the click branch does not exist on other reruns). If this ever needs optimising, cache per-rerun rather than restructuring the call sites -- and note that _asset_control_data is deliberately pure so that the duplicate call cannot diverge.

6. The email subject line and the greeting sentence are byte-identical duplicates in _build_expense_eml (lines 1878, 1880-1885) and _expense_email_subject_and_body (lines 2145, 2147-2152). The Outlook .eml route uses the first; the iOS share sheet and the mailto fallback use the second. docs/COMMIT_NOTES_2026-08-11_EXPENSE_EMAIL_ATTACHMENT_HANDOFF.md section 5.2 makes it an invariant that destination selection must not alter business content, so editing one and not the other silently gives the approver different wording depending on which device the employee filed from -- with no test covering the pairing. The bullet lists deliberately differ (6 bullets in the .eml, 3 in the share/mailto body), so any consolidation must preserve that asymmetry.
   - Files: `app/expense_ui.py`
   - Suggestion: Extract only the subject and greeting into one helper used by both, keeping the two bullet lists at their call sites, and add a test asserting both routes produce the same subject and greeting for the same details.

7. `hashlib.sha256(account.encode("utf-8")).hexdigest()[:10]` is computed independently in render_expense_workflow (line 388) and _seed_profile (line 1678). If they ever diverge, _seed_profile writes defaults onto keys no widget reads, so every step-2 field renders blank with no error and the progressive-disclosure panel never collapses. tests/test_expense_disclosure.py and tests/test_needs_value_highlight.py hardcode the same derivation a third and fourth time.
   - Files: `app/expense_ui.py`, `tests/test_expense_disclosure.py`, `tests/test_needs_value_highlight.py`
   - Suggestion: One `_account_token(account)` helper used by both call sites and imported by the two tests, so the derivation exists once.

8. `_preferred_email_destination` has two branches returning the same value: `if "windows" in identity: return _EMAIL_OUTLOOK_APP` (line 2185) and the unconditional fallback below it. The Windows branch is functionally a no-op today.
   - Files: `app/expense_ui.py`
   - Suggestion: Keep it. It documents the Windows intent separately from 'unknown browser, choose the safest attachment-bearing route', and collapsing them would let a future change to the unknown-browser default silently change the Windows default too. Annotated in place rather than removed.

9. The receipt-matching predicate `receipt_id in key or token in key and key.startswith("expense_")` appears twice in _clear_removed_receipts (lines 2334 and 2338), once for the live session and once for the draft snapshot. The two must stay identical or per-receipt state is cleared from one store and resurrected from the other by restore_expense_draft_state.
   - Files: `app/expense_ui.py`
   - Suggestion: Extract a single `_belongs_to_receipt(key, receipt_id, token)` predicate -- also the natural place to fix the precedence issue reported above.

10. build_prefilled_form_url and handoff_rows open with an identical eight-line field-iteration preamble: iterate (*config.form_order, *fields.keys()), dedupe via a `seen` set, skip fields outside KNOWN_FIELDS, skip _must_remain_blank, skip non-_nonempty. The two then diverge only in what they do with the surviving field. Because the preamble is copied rather than shared, a policy change (a new ALWAYS_BLANK field, a new conditional-blank rule) has to be made in two places, and applying it to only one produces the exact prefill/copy-list disagreement described in the first bug above.
   - Files: `app/smartsheet.py`
   - Suggestion: Extract a private generator, e.g. `_emitted_fields(fields, config)` yielding (field, value) after all four filters, and have both functions consume it. Deliberately do NOT unify the tail: the value-mapping difference is currently a bug, but which of the two behaviours is correct is a business decision, not a refactor.

11. render_prefilled_link passes a `help=` tooltip explaining that the button opens a new tab and that iOS may hand the link to the signed-in Smartsheet app. smartsheet_inline prints a st.caption immediately above the same button saying the same two things in almost the same words. The caption is what the entrypoint test pins; the tooltip is invisible on touch devices, which are the platform both sentences are about.
   - Files: `app/smartsheet_ui.py`, `app/smartsheet_inline.py`
   - Suggestion: Keep the caption (it is asserted and it is the one an iPad operator can actually read) and let the tooltip carry only what the caption does not -- or drop the tooltip. Either way the two strings should not be maintained independently.

12. The transparency-flattening logic exists twice and the two copies have DIVERGED. app/ocr.py:123-129 tests `mode in {"RGBA", "LA", "PA"} or (mode == "P" and "transparency" in info)`, converts to RGBA, and uses rgba.split()[-1] as the paste mask -- correct for palette images. app/expense_report.py:1252-1257 tests only `mode in {"RGBA", "LA"} or "transparency" in info` and derives the mask with getchannel("A") guarded by `"A" in getbands()`, which is None for mode "P". The 2026-08-12 hardening pass fixed one site and not the other, which is the bug reported above. The same 40-megapixel ceiling is also declared twice, as _MAX_RECEIPT_PIXELS and app/ocr._MAX_PIXELS_PER_FRAME, and the dimension check itself is written once as a function and once inline.
   - Files: `app/expense_report.py`, `app/ocr.py`
   - Suggestion: In a later, verified change (not a comment pass): extract one `flatten_to_white(image)` helper and one pixel-ceiling constant/guard shared by both modules, adopting app/ocr.py's version as the correct one, and add a regression test that pushes a mode-"P"-with-transparency receipt through receipt_attachment_pages and asserts the result is not uniformly black. Until then a comment at app/expense_report.py:1252 names the gap explicitly so nobody tidies the branch without closing it.

13. Rounding policy for money is decided in three places with two different modes: app/expense_report.parse_expense_amount and mileage_reimbursement use Decimal's implicit default (ROUND_HALF_EVEN), app/expense_ui._selected_receipt_item_amount passes ROUND_HALF_UP explicitly, and the workbook's own =ROUND(...) cells are half-up. Nothing states which is intended.
   - Files: `app/expense_report.py`, `app/expense_ui.py`
   - Suggestion: Decide the policy once (half-up matches both Excel and ordinary money handling), state it at the single quantize helper, and make every call site pass it explicitly so an omitted `rounding=` argument can no longer silently mean 'banker's rounding'. Reported, not applied -- this changes emitted amounts and needs its own verified change with the cent-level regression test the divergence above describes.

14. po_context._strip_ai_wrapper and po_context._unified_review_items are byte-identical logic twins of web_ui._strip_ai_wrapper and web_ui._build_unified_lists. This duplication is DELIBERATE and must not be merged: web_ui imports po_context, so the dependency runs one way only, and the checkbox keys are positional (inc_<token>_<index>), so the two lists must produce the same order. If they ever diverge, the list shifts by an entry and the operator's ticks are attributed to the wrong inclusions in both the PDF and the Smartsheet scope text, with no error anywhere.
   - Files: `app/po_context.py`, `app/web_ui.py`
   - Suggestion: Do NOT merge into one shared helper by importing web_ui from po_context -- that is an import cycle. If the duplication is ever removed, the shared function must move to a third leaf module (the same pattern as app/ui_highlight.py). I have annotated both risk points in po_context; web_ui already carries the matching warning.

15. The '160' Smartsheet cell limit for Asset ID is hard-coded independently in two places -- po_rules.asset_id_is_numeric (line 458) and the warning branch in po_context.build_po_context (line 911) -- with no shared constant. The po_rules copy is in a function nothing calls, so today only the po_context copy has any effect.
   - Files: `app/po_rules.py`, `app/po_context.py`
   - Suggestion: If asset_id_is_numeric survives the dead-code phase, hoist the limit to a module constant in po_rules and have po_context import it. Noted in comments at both sites so a change to one cannot silently miss the other.

16. Four sentinel string literals are duplicated across module boundaries with no link: '— Select a contract —' and '— Select a site —' (web_ui.CONTRACT_PLACEHOLDER/SITE_PLACEHOLDER vs po_context._CONTRACT_PLACEHOLDER/_SITE_PLACEHOLDER), 'None Applicable' (web_ui.ASSET_NONE, po_context._asset_value, po_rules.normalize_asset_id's casefolded set) and the '— Choose an asset' prefix (web_ui.ASSET_PLACEHOLDER vs po_rules.normalize_asset_id). Editing one copy alone raises nothing -- the comparison stops matching and the prompt text itself is exported into the Smartsheet cell.
   - Files: `app/po_context.py`, `app/po_rules.py`, `app/web_ui.py`
   - Suggestion: Not fixable by importing web_ui (cycle). The correct home is a small shared constants leaf module, the same shape as app/ui_highlight.py. Until then the coupling is documented at every copy; web_ui already documented its side, and I have now documented po_context's and po_rules'.

## 7. How to act on §5 without breaking anything

Do not delete from the §5 table directly. Every entry there was found by
searching, and searching cannot see three things this codebase actually uses:

1. **Streamlit reaches code by page discovery**, not import. Anything referenced
   from `pages/` is live even with no import edge.
2. **Source-text tests.** Removing a symbol can break a test that asserts on the
   file's text rather than its behaviour, and the failure names neither.
3. **Re-exports.** `RRH_JOB_NUMBERS` in `smartsheet.py` is imported and never
   used *in that module* -- it is a live re-export that tests import from there.

The verification each candidate needs, before removal:

- `rg -w <symbol>` across the repo including `tests/`, `pages/`, `scripts/`,
  `docs/`, and `.github/`;
- `git log -S <symbol>` to see whether it was ever called, and what removed the
  caller -- a symbol whose caller was deleted in a reversal may be wanted again;
- delete it, then run the **full** suite, not a subset;
- for CSS: confirm no element is given the class, remembering that Streamlit
  rewrites `st-key-` class names, so the string in the rule may legitimately
  differ from the key in the code.

The three CSS entries in §5.1 are the strongest candidates: a rule that matches
nothing is the exact shape of failure this project has hit repeatedly, and it is
invisible in a passing test run.

## 8. What was NOT verified

- **12 modules were never read** (§2). No claim is made about them.
- **Three annotated modules have no findings list** (§2 footnote).
- **No bug in §4 was reproduced end-to-end in a browser.** They were derived by
  reading, with `failure_scenario` stating the path. The two HIGH entries deserve
  a live check before anyone relies on the descriptions.
- **No dead code was removed**, so no removal was tested.
- **`tests/` was not reviewed** for redundancy or obsolescence, only read as
  evidence of intent.
