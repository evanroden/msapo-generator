---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: main
merge_commit: 392239a3f94a5d8659f47ea85e72da3679e9112b
merge_commit_subject: "Correctness and failure-mode hardening across the expense, PO, and vision paths (#40)"
pull_request: 40
base_commit: a51446c2b439502a31db241eea7e82a672fe3540
implementation_tree: daf0ee4aebb8d806d32798cbbd36f5c5123db0e5
date: 2026-08-12
workflow: cross_cutting
change_type: correctness_and_failure_mode_hardening
status: shipped
merge_method: merge_commit_not_squash
ci_run: https://github.com/evanroden/msapo-generator/actions/runs/31549321404
implementation_commits:
  - sha: a55a2cda5c72a943a629d838a743faae37368866
    subject: Stop the schema inverting assumption sections, and degrade the last two guesses
  - sha: 53cdcbc189b7932796a5b24c1d4b1f6bd924e5a8
    subject: Bound the real vision payload, and stop transparency turning receipts black
  - sha: 675779b923fbcd9eb56a58411be92d7c2b3aa034
    subject: Make the workflow selector unable to represent "no workflow"
  - sha: a624cc03474516176ddea88c57854020991158a4
    subject: Never discard a completed expense report, and never sign a truncated name
  - sha: 5a7c02928d41b454933fefba84ec2339b15b1be9
    subject: Stop the expense draft mirror resurrecting dismissed errors, forever
  - sha: 3d5d524b3335d8e85942706303d7df57641d88f8
    subject: Make attachment de-duplication able to match, so resumes stop duplicating files
  - sha: 1656b58702ef1fdb697036e20d6edf0a2340b7c2
    subject: Install both signature fonts, and make the image prove it ships them
---

# Commit notes: correctness and failure-mode hardening

## 1. LLM quick context

This document is the detailed engineering record for merge commit
`392239a3f94a5d8659f47ea85e72da3679e9112b` (PR #40), which landed seven
independent fixes on top of `a51446c`.

Nothing here added a feature. Every change closed a defect that produced a
**wrong artifact**, **destroyed operator work**, or **could not fail visibly**.
Three of the defects had no error path at all: they produced a plausible-looking
document that was wrong.

This branch was **merged, not squashed**, deliberately. Each commit message
carries its own measurements and rejected alternatives, and `git blame` on any
touched line should land on the reasoning for that specific defect. Do not
squash follow-up work that has the same property.

### 1.1 Invariants established by this commit

These are product/correctness invariants, not implementation suggestions. A
later agent must preserve them unless the product owner explicitly changes the
workflow.

1. **An unrecognized enum value from the model must never be coerced into a
   value with the opposite meaning.** Degrade to a neutral/None state or to a
   documented conservative bucket, never to a semantic inverse.
2. **A model deviation must never discard an otherwise usable extraction** when
   the affected field has a deterministic fallback downstream.
3. **A renderer or transport failure must never destroy validated operator
   input.** Degrade to the partial artifact; keep everything already entered.
4. **The signature image must be complete or refused.** Never emit a clipped
   rendering of an employee's name onto the JDE form they attest to.
5. **The workflow selector must always resolve to a real workflow.** No state
   may render a page belonging to neither workflow.
6. **The expense draft mirror holds only operator-entered values.** Anything
   handler code pops is by definition not operator input and must be excluded.
7. **Vision payload limits are measured on the base64 form**, which is what the
   request carries, not on raw encoded bytes.

## 2. Why this work was required

An independent review of the 2026-08-11 expense-report and Smartsheet work found
defects that the existing suite could not have caught, because in every case the
code did exactly what it was written to do — the written behavior was wrong.

The review was verified rather than trusted: every finding below was reproduced
locally before being fixed, and two findings from the review were **rejected as
incorrect** (see section 7).

## 3. Defects that produced silently wrong output

### 3.1 Assumption sections were inverted (`app/analysis_schema.py`)

`_assumptions()` normalized an unknown section by stripping a trailing `"s"` and
otherwise coercing to `"exclusion"`. That is correct for `"nonsense"` and wrong
for `"included"`: `"included"` does not end in `s` and is not in
`_ALLOWED_ASSUMPTION_SECTIONS`, so it became `"exclusion"`.

These strings are not internal hints. `app/scope_pdf.build_scope_pdf` renders
them verbatim as bullets on the Scope/Inclusions/Exclusions PDF attached to the
purchase order, and the item is checked by default. The attachment therefore
told the vendor they were **excluding** work the model had marked as
**included**, with nothing in the UI signalling the flip.

**Fix:** new `_assumption_section()` maps on the stem — `inclu*` → `inclusion`
(covers inclusion/inclusions/included/including), `exclu*` → `exclusion`,
`scope*` → `scope`. Unrecognizable values still fall back to `"exclusion"`,
which remains the conservative bucket because an over-stated exclusion is
visible to the reviewer on the attachment whereas a silently dropped one is not.

**Provenance note:** the inverted coercion was introduced by an earlier
correction round (`docs/CORRECTIONS_TO_2026_07_27_WORKFLOW_CHANGES_2026-08-10.md`,
item C3d) that was correct in intent — stop hard-failing — and wrong in the
fallback it chose.

### 3.2 The employee signature was clipped, not fitted (`app/expense_report.py`)

`employee_signature_png()` rendered at a fixed 112pt onto a fixed 1600px canvas
and then cropped with `min(1599, width + 56)`. Any name wider than the canvas
was drawn past the edge and the crop silently returned a cut-off image. The only
guard, `len(name) > 160`, does not correspond to rendered width.

Measured with the shipped face
(`/usr/share/fonts/opentype/urw-base35/Z003-MediumItalic.otf`):
`"Maria de los Angeles Fernandez-Villalobos"` renders **1708px at 112pt**.

The image is embedded at `C66` of the official JDE reimbursement form sent to
the approver, and the employee attests to it via *"I confirm this generated
signature represents me"* — so they were attesting to a truncated rendering of
their own name on a financial document.

**Fix:** the font is fitted to the canvas (measure, scale toward a fit, always
stepping down at least 1pt so no metric can stall the loop) down to
`_SIGNATURE_MIN_FONT_SIZE`. **If it still does not fit at the floor, the
function raises** rather than emitting a clipped image.

Verified across the input range:

| Input | Result |
|---|---|
| `"Evan Roden"` | renders at full 112pt |
| 41-char real name | fits at 101pt |
| 107-char name | fits |
| 160 × `"X"` | fits at floor |
| 160 × `"W"` (pathological) | **refused with an actionable message** |

Layout constants were extracted (`_SIGNATURE_CANVAS`, `_SIGNATURE_MARGIN`,
`_SIGNATURE_MAX/MIN_FONT_SIZE`, `_SIGNATURE_MAX_NAME_CHARS`) so the fitting maths
and the crop cannot drift apart.

### 3.3 Transparency was dropped onto black (`app/ocr.py`)

`oriented.convert("RGB")` discards the alpha channel and keeps whatever RGB the
transparent pixels carried — usually black for a screenshotted or scanned
receipt. A receipt with a transparent page background reached the model as a
black field with the text invisible.

This was pre-existing and became unavoidable once frames are encoded as JPEG,
which has no alpha at all. RGBA/LA/PA and palette-with-transparency images are
now composited onto **white** before the alpha channel is dropped.

## 4. Defects that destroyed operator work

### 4.1 A PDF renderer timeout discarded the completed expense report

`build_expense_package()` guarded PDF conversion with a comment promising that
*"a renderer outage never forces re-entry"*, and `app/expense_ui.py` has a
matching Excel-only fallback (`if not package.pdf_bytes: ...`). The guard caught
only `ExpenseReportError`, which is not what the two most likely failures raise:

- `convert_expense_workbook_to_pdf()` shells out via
  `subprocess.run(..., timeout=120)`, which raises `subprocess.TimeoutExpired`.
  A receipt-heavy workbook — many embedded images, one worksheet per receipt —
  is precisely what exceeds the budget, so the failure **correlates with the
  largest and most painful reports**.
- The Gotenberg backend raises `requests.ConnectionError`/`HTTPError` before any
  wrapping runs. `GOTENBERG_URL` defaults to `http://localhost:3000`, which is
  unreachable on Render.

Both escaped, and `expense_ui`'s generic `except Exception` then stored
`expense_generation_error` and **popped** `expense_generated_package`. The
Excel-only fallback was therefore unreachable *by construction*: the package it
tests for had already been discarded. The operator lost every receipt line,
allocation and mileage row entered.

**Fix:** catch `Exception`. The breadth is deliberate and bounded — the workbook
is built and validated *above* the `try`, the only statement inside it is the
conversion call, and every failure of that call must degrade to "Excel ready,
PDF unavailable". `BaseException` still propagates. The message falls back to
the exception class name because `TimeoutExpired.__str__` can be empty.

### 4.2 The workflow selector could deselect into a no-workflow state

`st.segmented_control` defaults to `required=False`. For a single-select control
that permits **deselecting** the active segment, which returns `None` — neither
`PURCHASE_WORKFLOW` nor `EXPENSE_WORKFLOW`. Execution fell through to the
Purchase Order page, rendering the PO hero, quote uploader and PO steps with
**neither segment highlighted**. The in-progress expense report appeared to
vanish.

The trigger is not exotic: the selector is a full-width ~56px tap target on a
phone, so a double-tap or a stray tap while scrolling is enough, and both flows
are used from an iPad.

**Fix:** `required=True` on the control, **plus** a defensive normalization —
any `workflow_mode` that is not one of the two known values resolves to
`PURCHASE_WORKFLOW`. `required=True` governs the widget; `session_state` can
still hold a stale or hand-set value (an older session restored after a deploy,
a test, a future third workflow removed from the tuple), and none of those may
render the half-empty hybrid page.

### 4.3 Dismissed errors resurrected permanently

`preserve_expense_draft_state()` mirrors `expense_*` values into
`expense_draft_snapshot`; `restore_expense_draft_state()` re-injects them with
`setdefault()`. The mirror only ever **added** keys, so any key the workflow
popped was re-injected on the next rerun and could never be dismissed:

- `expense_generation_error` / `expense_email_error`: one failed generation left
  its message pinned to the page permanently, sitting beside a subsequently-good
  package.
- `expense_employee_number_recalled_for_*` / `expense_approver_recalled_*`: the
  "recalled from history" captions reappeared after the operator hand-edited
  those values, so the UI claimed a value came from memory when it had just been
  typed over.

**Fix:** exclude transient state at source via three fragments — `_error`,
`_recalled`, `restored_without_uploader`. See section 6 for the rejected
alternative and the static guard that makes this maintainable.

## 5. Latent defects (not yet reachable, fixed before they become reachable)

### 5.1 Smartsheet attachment de-duplication could never match

`_attach_file()` sent the name percent-encoded (`quote(api_name, safe="")`),
turning `Quote 1 [EPC-ab12cd34ef56].pdf` into
`Quote%201%20%5BEPC-ab12cd34ef56%5D.pdf`, while `_remote_has_attachment()`
compared the **unencoded** name. The lookup could never succeed.

`submit_po()`'s resume path re-lists the row specifically to avoid re-uploading.
With the comparison permanently failing, every resume re-uploaded the quote and
scope PDF, `record_attachment` was never reached, and the row accumulated
duplicates — silently defeating the idempotency machinery (leases, submission
keys, verified attachments) for the attachment half of the submission.

The encoding was also unnecessary: `_api_attachment_name()` already constrains
the result through `_SAFE_FILENAME_RE` to plain ASCII, which RFC 6266 permits
verbatim in a quoted-string.

**Fix:** send the name verbatim, and make `_remote_has_attachment()` also match
the percent-decoded form so rows written before this fix still de-duplicate.

**Reachability:** `SMARTSHEET_API_MODE=disabled` and no non-test caller invokes
`submit_po`, so this is a latent fix landing *before* the live path is switched
on. Anyone enabling live mode should read section 8.

### 5.2 The second signature font was never installed

`_SIGNATURE_FONT_CANDIDATES` declares two fonts and falls back from the first to
the second. The image installed `fonts-dejavu-core`, which does **not** contain
`DejaVuSerif-Italic.ttf` — the italic serif faces are in `fonts-dejavu-extra`.
Verified directly: before installing the extra package that path does not exist
while `DejaVuSerif.ttf` and `DejaVuSans.ttf` do.

The fallback was therefore fiction, and signature rendering depended entirely on
`fonts-urw-base35`. Dropping that single package during a base-image bump or an
apt-list trim would have failed the signature step closed in production with
`"The cursive signature font is unavailable in this deployment"` — a message
that reads like a code bug rather than a missing OS package. No test would have
caught it, because CI's `ubuntu-latest` runner provides fonts of its own.

**Fix:** install `fonts-dejavu-extra`, and add
`test_every_signature_font_candidate_is_installed_by_the_image`, which walks
`_SIGNATURE_FONT_CANDIDATES`, maps each font **directory** to the Debian package
providing it, and asserts the Dockerfile installs it. It fails in two distinct
ways on purpose: an unmapped directory (a candidate from a new font family) and
a mapped-but-uninstalled package (a trimmed apt list).

### 5.3 Two enum guesses still hard-failed a usable extraction

`tax_status` and `work_category` were deliberately softened to degrade in the
2026-08-10 corrections; `purchase_route_guess` and `request_type_guess` were
left raising. Both already have deterministic fallbacks (`web_ui` re-derives the
route with `infer_purchase_route()`; an absent request type is a plain PO), so a
model answering `"onsite labor"` produced `AnalysisResponseError`, one retry,
and then *"The quote could not be analyzed"* — for a field the UI was about to
overwrite anyway.

**Fix:** both normalize (case, spaces, hyphens) and degrade to `None`.

**Safety property explicitly preserved:** `original_po_number` may survive only
for a **confirmed** `CHANGE ORDER`. Because an unrecognized request type now
degrades to `None` rather than raising, it reaches the existing guard as "not a
change order" and a hallucinated PO number is still cleared. This has its own
regression test so the degrade cannot later be widened into a leak.

## 6. Failure modes squashed proactively

These were not in the review. They were found while fixing the above and closed
in the same pass.

### 6.1 The vision payload was still over budget after downscaling

The earlier correction contained frames to 1568px because the API downsamples
past that anyway, aiming to stay under the ~5 MB per-image limit. It kept
lossless PNG, which does not get there. Measured at 1568px:

| Content | PNG raw | PNG base64 | JPEG raw | JPEG base64 |
|---|---|---|---|---|
| Photographic | 5.39 MB | **7.19 MB** | 0.90 MB | 1.20 MB |
| Photographed text page | 2.82 MB | 3.76 MB | 0.22 MB | 0.29 MB |

The request carries the **base64** form, so lossless PNG breached the limit for
exactly the input the feature exists to support: an iPhone photo of a paper
quote. Now JPEG at **q90** — high enough that compression ringing around small
glyphs does not cost extraction accuracy, and still an order of magnitude inside
the limit. Tests assert the **base64** size so this cannot silently regress.

Only normalized formats (HEIC/HEIF/HIF, TIFF, BMP) take this path; PNG, JPEG,
GIF and WebP still pass through untouched via `DIRECT_IMAGE_MEDIA_TYPES`, so the
switch cannot degrade a file supplied in a format the API already accepts.

### 6.2 The pixel guard ran after the raster was materialized

`_MAX_PIXELS_PER_FRAME` was checked on `oriented.size` — i.e. *after*
`frame.copy()` and `exif_transpose()` had each decoded and allocated the full
frame. Pillow's own decompression-bomb guard only trips near 178 MP, so every
frame in the **40–178 MP band** fully materialized (hundreds of MB, twice)
before rejection, once per frame, up to `_MAX_IMAGE_FRAMES` times, on a shared
Render container.

`app/expense_report._validate_receipt_dimensions` already ordered this
correctly; `app/ocr.py` now reads `frame.size` first. The regression test asserts
`Image.copy` is **never called** for an oversized frame, pinning the ordering.

### 6.3 Nothing bounded the aggregate request payload

`_MAX_IMAGE_FRAMES` caps frame *count* and the downscale caps per-frame *size*,
but nothing capped their product. Twenty individually-legal frames still exceed
the overall request ceiling, and the failure surfaced as an opaque API rejection
*after* the operator had paid the upload and OCR wait. Added
`_MAX_TOTAL_ENCODED_BYTES` (24 MB of base64) checked across all blocks, raising
an actionable "split the file into smaller uploads".

## 7. Rejected work — do not re-attempt without reading this

### 7.1 Rebuilding the expense draft mirror from the live session

This is the obvious fix for section 4.3, it is what a reviewer will suggest, and
**it is wrong.** It was implemented and backed out. There is no trustworthy
"the expense widgets rendered on the previous run" signal:

- **Keying off `workflow_mode` fails.** The selector updates `session_state`
  *before* the rerun, so on the run that switches *into* the expense workflow it
  already reads `"Expense reimbursement"` while no expense widget exists yet. The
  rebuild wiped the mirror and the restored draft came back blank. Caught by
  `tests/test_web_ui_app.py::test_expense_workflow_generates_excel_pdf_and_attached_email_draft`.
- **A completion marker set at the end of `render_expense_workflow()` also
  fails.** It fixes the above but breaks on `pages/2_Smartsheet_PO.py`: that page
  renders no expense widgets, so Streamlit collects them while the marker still
  reads true, and the next return to the main page rebuilds from a session that
  no longer holds them — wiping a half-finished report.

Losing the operator's work is strictly worse than the stale banner being fixed.

**Consequence:** the exclusion list is load-bearing, and hand-maintained lists
rot. It is therefore enforced statically by
`tests/test_expense_draft_state.py::test_every_popped_expense_key_is_excluded_from_the_mirror`,
which scans `app/expense_ui.py` for every `session_state.pop("expense_*")`
(including f-string keys), reads the live `excluded_fragments` tuple out of the
function under test, and fails naming the offending keys. The guard was verified
to actually fail — removing the `_error` fragment makes it report
`expense_email_error` and `expense_generation_error` — so it is a real
constraint, not a test that cannot fail.

### 7.2 Two review findings rejected as incorrect

Recorded so they are not "fixed" later:

- **"Generic work category is blank / the analyzer classification is not
  prefilled."** False. `app/web_ui.py` already prefills it via
  `WORK_CATEGORY_DISPLAY.get(analysis.work_category, analysis.work_category or "")`.
- **"An RRH site with no cost-code mapping silently produces a blank."** Partly
  false. A visible manual `text_input` and an explanatory caption already render.
  The genuine (smaller) gap is that the value is not *validated*; that remains
  open — see section 8.

## 8. Known-open items after this commit

Not regressions from this work; recorded so the next agent does not rediscover
them from scratch.

1. **An empty job cost code can still be sent.** `unity_specialty` is the first
   RRH site in `FACILITY_SHORT_NAMES` with no entry in `SITE_COST_CODE_LETTERS`,
   so `lookup_cost_code` returns nothing and the manual input is unvalidated.
   Contract and site hard-block on the same screen; cost code does not.
   **Open question for the product owner:** does Unity Specialty Hospital have a
   real Appendix A cost-code letter? Do not invent one.
2. **`MANUAL_COST_CODE_SITES` is referenced only by tests.** Its comment claims a
   guarantee that no runtime code implements; the block comes incidentally from
   generic `if not cost_code` checks.
3. **Dead code.** `app/document_generator.py` and `app/pdf_converter.py` have no
   production caller (the PO attachment is `app/scope_pdf.build_scope_pdf`), the
   live-API half of `app/smartsheet.py` plus `app/smartsheet_store.py` are
   reachable only from tests, and parts of `app/memory.py` are unreferenced.
4. **No authentication** on the deployed Streamlit app.
5. **UI streamlining is not started.** The agreed direction: a confidence strip
   with "Adjust" expanders so only unresolved fields are visible, `st.form`
   batching (there are currently zero forms, so most interactions trigger a full
   rerun), receipt-as-card that self-collapses when complete, and a "needs you"
   counter. Nothing removed — collapsed by default. This is a redesign of two
   ~1,800-line modules and must be its own PR with visual verification on a real
   iPad.

## 9. Verification performed

- Full suite green at merge; CI green on the PR
  (`https://github.com/evanroden/msapo-generator/actions/runs/31549321404`).
- Every fix ships regression coverage. Two tests pin **invariants** rather than
  behavior: the font-package sync (5.2) and the popped-key exclusion (7.1). Both
  were verified to fail when their protection is removed.
- Two pre-existing tests encoded the old behavior and were rewritten with
  rationale: `test_analysis_rejects_unsupported_guesses` (now asserts
  degrade-and-keep) and the OCR media-type assertions (now JPEG).
- Measurements in sections 3.2 and 6.1 were taken against this repository with
  the shipped font and Pillow, not estimated.

### 9.1 Note for anyone re-running the suite locally

`tests/test_expense_report.py::test_combined_pdf_places_signed_form_before_each_receipt`
requires **LibreOffice Calc**, and eleven signature tests require the fonts in
5.2. A sandbox lacking them reports twelve failures that are environmental, not
real. The Dockerfile provisions both deliberately. Use a container matching the
image, or expect those failures and confirm against CI.
