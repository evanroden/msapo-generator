# MSAPO issue #440 — blocking warning → native owner / recovery matrix

Base audited: `main` `57c5cd87e3e441dfea3cddbc666248f8e469d986`.
Work branch: `repair/440-blocking-warning-native-owners-20261111`.
Integration owner: P20; navigation owners P02/P18; guided editor owners P04/P08.
Code modified only on the isolated branch; **not deployed**.

The authoritative warning definitions come from `preflight` in
`app/monthly_report_checks.py`, `layout_checks` in
`app/monthly_report_layout_checks.py`, and the saved-source recovery check
in `app/monthly_report_guided.py`. A warning code can originate from multiple
fields. A single generic section anchor is not evidence of complete coverage.

| Blocking code(s) | Actual field / explicit action | Bound identity and fail-closed behavior |
| --- | --- | --- |
| `prepared_by` | Existing native Prepared by input | Report/editor identity and input key; no auto-filled actor |
| `sections` | Choose one unique excluded section then Include | Snapshot fingerprint; explicit click only |
| `duplicate_sections`, `duplicate_blocks` | Dedupe byte-identical records only, or open Manage source files / Shared report history to restore conflicted originals | Never guess which distinct record to discard |
| `title` | Native included section-title input for blank/unsafe headings | Unique section key, structural revision, original literal text retained |
| `follow_up_limit` | Select one exact issue/proposal occurrence and Leave out | Actual position, unique item key, full draft fingerprint; no bulk removal |
| `follow_up_identity` | Existing `unique_followup_keys` procedure under explicit Review action | Reassign collisions only; preserve text/source/status; changed decisions re-review |
| `follow_up_section` | Include its unique owning section or Leave that exact item out | Bound item key/index and draft fingerprint |
| `follow_up` | Existing issue/proposal reason-specific native editor | `followup_target`: item revision, category, sources, scope; no implied confirmation |
| `carried_period` | Existing exact carried-period confirmation control | Block fingerprint and report period; explicit acknowledgement |
| `period_removed` | Existing ordinary narrative editor / dated item actions | Block identity; no silent restoration of excluded wording |
| `org_chart` | Native exact node field, validated chart representation choice, or positional duplicate-node recovery | Node index/key/revision; ambiguous manager relationships require explicit choice |
| `photo_layout` | Explicit bounded photos-per-page correction | Original block fingerprint; no unapproved picture inclusion |
| `table_columns`, `table_missing_columns` | Physical positional heading inputs; block row grid withheld until correct widths | Preserve duplicate/blank headings, exact rows and reference; commit then rerun |
| `required` | Existing ordinary rich-text field; explicit re-open of omitted/missing required summary; existing chart builder | Does not manufacture content or treat opening as approval |
| `review` | Existing AI paragraph/evidence owner, or ordinary native text owner | Paragraph/fact/source revision; not auto-approved |
| `pricing`, `placeholder`, `text_character` | Native rich text, exact picture caption, row-cell, chart node, section title, report identity, footer, or schema-heading correction according to origin | Specific picture occurrence, table/index/cell, node, field and scope; price gates unchanged |
| `client_pages`, `photo_caption`, `document_caption` | Existing picture review and caption editor | Immutable picture instance and (for source pages) source/page provenance |
| `client_source_page`, `financial_page` | Existing source/financial page owner | Source fingerprint and page identity; navigation never approves |
| `source_facility`, `source_period` | Existing source-details date/site editor | Exact source ID; re-selection never waives a foreign site |
| `source` | Native block source selection correction | Unique block, allowed value, explicit action |
| `source_missing` | Manage source files plus missing source-ID receipt and truthful re-upload/relink guidance | No filename/byte substitution; original absent so never auto-authorize |
| `client_source_missing`, `unavailable_source` | Manage source files with known source ID or no-ID recovery action | Missing original remains a blocker until valid original or deliberate exclusion |
| `receivable_source` | Manage source files and existing conservative Accounts Receivable review | Stale invoice receipt never auto-renews nor approves amounts |
| `library_save` | Existing inline block action or unmounted cover/footer/layout action to retain report-only content | Pending shared-library replacement cancelled only on explicit click |

Nonblocking `period`, `empty` and `size` are **not** converted into
blocking corrections. Existing financial/client/source eligibility gates are
not modified to grant new approvals.

## Focused verification checklist

Run against **one exact PR head**, not a superseded cancelled Actions run:

```bash
python -m pytest -q tests/test_monthly_report_warning_field_owners.py \
 tests/test_monthly_report_warning_photo_caption_navigation.py \
 tests/test_monthly_report_review_warning_clarity.py \
 tests/test_monthly_report_correction_ui.py
```

Then the hosted `Monthly exact warning routes` workflow, real pointer and
keyboard journeys, a native unblurred editor → warning → exact focus →
Return to Review round trip, stale/deleted targets, two same-name source IDs,
two equal-byte picture occurrences, and save/reopen plus actual DOCX/PDF checks.
On each correction, verify that no contents, reviews or source identities
change before an explicit decision. Confirm that preflight still blocks
pricing, foreign-site, ambiguous dates, unreviewed pictures, and stale AR.

**Evidence at authoring:** new branch code and focused tests committed; live
native journeys, output artifacts and exact-head CI **NOT RUN / PENDING**.
No PASS assertion or production deployment follows from the presence of tests.
P20 should integrate only after exact-head proof and owner review.
