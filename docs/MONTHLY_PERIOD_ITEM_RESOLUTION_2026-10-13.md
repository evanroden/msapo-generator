# Item-specific reporting-period resolution

This bounded P1-U01 slice addresses directly typed narrative items with an
older date. It does not declare all source-resolution work complete.

## Existing behavior and scope

On baseline `6d044cd`, `carried_period` is a hard gate for carried
`utility_analysis` and `mbcx_status`. Their existing whole-block confirmation
is separate from the soft lexical `period` checks on narrative, captions and
tables. Source date/facility forms already correct canonical source metadata.

The new item resolver is for manual narrative lines only. It shows the exact
wording and dated references, section title and line number. A source filename
and page/item are shown only when that page is explicitly linked and contains
the exact normalized passage. Otherwise it accurately identifies entered report
wording without established exact source lineage. A link goes directly to the
block's existing editor for wording/date correction; there is no second editor.

`Retain as historical context` prepends **Historical context:** to this exact
exported item. It requires earlier references only: mixed current/future,
invalid dates and priced wording cannot be collectively relabeled. Its receipt
binds the target report month, exact output wording and current linked evidence.
A changed source or edited item requires a fresh decision. No source date is
rewritten, and filenames are never date evidence.

`Exclude this item from this report` removes one occurrence from canonical
text and records the allowed remaining count. Repeated import cannot silently
restore the same removed wording in that report month. `Restore this wording`
is an explicit reversible action and restores normal period review. The receipt
preserves removed wording for this draft; it does not delete a source, standing
record or historical snapshot, or silently omit the item in another month.

## Architecture and integration

- `monthly_report_period_items.py` owns pure item detection, guarded decisions,
  exact historical receipts and same-month omission reconciliation.
- `monthly_report_period_items_ui.py` exposes
  `render_period_items(block, period, sources, prefix, *, section_title,
  editor_anchor) -> ResolvedBlock` beside the existing authoritative editor.
- The guided caller must emit `editor_anchor` once immediately before that
  editor and reconcile returned changes through its current guarded draft/widget
  transition. Do not assign to an already-mounted widget or leave its old
  non-widget mirror to overwrite a returned decision on the next rerun.
- `preflight` treats accepted narrative items separately from all table cells
  and captions, even identical wording. All original pricing, source integrity,
  AI review and carried-period hard checks remain active. If excluded wording
  reappears and direct generation bypasses the UI reconciliation, a hard
  `period_removed` check prevents export until that conflict is resolved.
- Receipts use versioned `period-item:v1:` references in the existing serialized
  block. No persistent schema migration is required. They are excluded from
  source-reference and picture-provenance lists, so changing one narrative item
  does not invalidate an unchanged picture or invent new source evidence.

The guided editor now emits one block anchor immediately before its existing
manual narrative editor and renders these item actions directly below it.
Returned decisions use a report-incarnation and month-bound transition receipt.
An interrupted full render replays only against the exact prior canonical or
submitted block; a newer unrelated draft rejects the old decision. The previous
text callback is consumed with the item action so it cannot restore excluded
wording. A visible editor refresh occurs after the complete canonical draft and
its recovery write attempt, never by mutating an already-mounted widget.

Five guided AppTests cover current editor/canonical agreement for exclusion,
restore and historical context; changed wording; repeated material and obsolete
widget callbacks; interrupted decisions and newer drafts; interrupted manual
recovery alongside an omission; and real guided durable recovery. An actual
synthetic DOCX package scan checks every retained package part for an excluded
price, its original wording and its encoded restore receipt. None are exported.
Restoring that wording reinstates the mandatory pricing block. These are local
AppTest/package checks, not deployed browser or authentic acceptance.

## Executed evidence

```sh
ANTHROPIC_API_KEY=test-key-not-used python -m pytest -q \
  tests/test_monthly_report_period_items.py \
  tests/test_monthly_report_period_carry.py \
  tests/test_monthly_report_asset_review.py \
  tests/test_monthly_report_ai.py \
  tests/test_monthly_report_source_details.py \
  tests/test_monthly_report.py \
  tests/test_monthly_report_review_warning_clarity.py \
  tests/test_monthly_report_sections.py
```

Observed: **127 passed, 1 skipped**. The skipped existing real-PDF test requires
LibreOffice Writer/Calc, unavailable locally. The new test assembles and opens
an actual synthetic DOCX and checks the exact historical label and wording.
It does not prove the native master, PDF pagination or authentic output.

Tests also cover source/target/text fingerprint invalidation, unchanged original
source objects and historical snapshot, durable block round-trip, repeated
merge reconciliation, direct-generation hard blocking, explicit restore,
duplicate occurrences, preserved picture approval, AI/caption/table separation
and the unchanged hard carried-period gate. Initial test development had two
harness failures: an omitted existing warning acknowledgment in DOCX assembly,
and an incorrect asset-approval helper name. Both were corrected without
changing application safety checks. The later 67-pass subset is included in the
127-pass result and is not additive.

## Remaining obligations and rollback

Source-linked AI paragraphs, tables, captions and images retain their existing
review paths; this slice adds no per-item historical approval for them. The
hard utility/MBCx carried-block gate is intentionally not cleared by a manual
line decision. Source metadata warnings remain independent. Correcting report
wording does not claim that the original source itself was corrected.

Guided AppTest typing/recovery and repeated-material reconciliation are now
covered locally; actual browser refresh/repeated-upload behavior, exact-head CI,
deployed behavior, native PDF and authentic owner acceptance remain separate
obligations. A code revert needs no data reset. Existing
historical labels and exclusion receipts remain in saved drafts; old code will
again warn on historical wording and lacks the new repeated-import suppression,
so that rollback limitation must be disclosed.

## Guided wiring verification

`python -m pytest tests/test_monthly_report_guided_period_items.py tests/test_monthly_report_rich_text_hydration.py tests/test_monthly_report_period_items.py tests/test_monthly_report_active_recovery_ui.py -q`: **37 passed** locally. This overlaps earlier helper coverage and is not additive. Local NumPy is 2.3.5 because the locked binary crashes in this environment; repository dependency files are unchanged and exact-lock CI remains required.
