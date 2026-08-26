---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: main
base_commit: 4ce409f38d05e3a57b7d7de0b4e4950ec4c9f7a6
implementation_commit: the commit containing this document
date: 2026-08-26
workflow: cross_cutting
change_type: post_review_state_and_handoff_remediation
status: implemented_and_locally_verified
explicitly_deferred: public authentication and request-rate limiting
---

# Commit notes: state and handoff remediation

## 1. LLM quick context

An August 25 review of the eight commits after merge commit `bfef2a6` found two
financial-coding regressions and three lower-severity correctness problems that
the green suite did not cover. This change fixes all of them:

1. Object Account and Agreement Type became `NA` when routing was temporarily
   invalid and stayed `NA` after the amount/route was corrected.
2. Explicit `5490-OTHER` and `03 - CSAPO (CONSTRUCTION)` choices disappeared
   after switching to Expense reimbursement and back.
3. A persistent Streamlit uploader made every ordinary expense edit claim that
   the original receipt was a newly ignored duplicate.
4. One deployment-wide Eastern timezone supplied the report date for users in
   every US timezone.
5. A blank `SMARTSHEET_FORM_VALUE_MAP_JSON` replacement could be encoded and
   counted as an included required field.

The earlier decision to defer public authentication and request-rate limiting
remains authoritative. This commit neither adds nor changes an access boundary.

### 1.1 Product behavior that must remain true

1. Purchase route still derives the common-case Object Account and Agreement
   Type pair without requiring operator interaction.
2. Both fields remain editable because contract/funding context can require
   confirmed options the text classifier cannot infer.
3. A manual choice survives reruns, route changes, and workflow switches.
4. Choosing the current derived value again resumes automatic default tracking.
5. An invalid amount or route blocks generation and cannot silently convert a
   temporary display fallback into an operator override.
6. Receipt identity remains SHA-256 of bytes, not filename.
7. Re-selecting an existing receipt still produces useful feedback, but an
   unrelated field edit does not.
8. Uploaded bytes remain in the existing bounded receipt mirror and are never
   copied into the primitive expense-draft snapshot.
9. Report date remains visible and editable before package generation.
10. A required Smartsheet field is included only if its final mapped value is
    nonblank and survives URL construction.
11. The PO routing matrix, Smartsheet option spellings, report calculations,
    attachment formats, and AI call paths are unchanged.

## 2. Root causes and implemented behavior

### 2.1 PO financial-coding state

#### Former mechanism

`app.web_ui.main` attempted to infer operator intent by comparing each widget
value with a `_prior_default` value:

1. valid route produced a derived default;
2. invalid amount produced no derived default;
3. the old value was replaced with an empty string and then coerced to `NA` so
   the selectbox would accept it;
4. when the amount became valid again, `NA` differed from the empty prior
   default and was therefore treated as a manual override.

The same values lived only in Streamlit widget keys. The Expense branch returns
before PO widgets render, so Streamlit collected those keys. On return to PO,
the absence of the keys looked like a new untouched request and route-derived
defaults replaced the operator's explicit choices.

#### New state model

`_po_coding_draft` is a non-widget session dictionary keyed by the active quote
analysis token. Each coding field stores:

| Property | Meaning |
|---|---|
| `value` | Exact option currently shown/sent. |
| `default` | Current valid route-derived option, or empty while unresolved. |
| `overridden` | Explicit boolean set only by the selectbox callback. |

The mirror is limited to the current analysis token. Obsolete entries are
discarded, and malformed restored values are rebuilt instead of raising.

#### Transition table

| Event | Displayed value | `overridden` | Next valid route behavior |
|---|---|---:|---|
| First valid classification | derived value | false | follows route |
| Untouched route changes | new derived value | false | follows route |
| Amount/route becomes invalid | `NA` | false | recovery restores derived value |
| Operator selects another confirmed option | selected value | true | selection persists |
| Operator selects current default again | derived value | false | follows later route changes |
| Switch to Expense workflow | PO widgets disappear; mirror remains | unchanged | mirror restores PO widgets |
| Malformed mirror | safe derived value or `NA` | false | no exception; state repaired |

`NA` remains a legitimate explicit Smartsheet option. The change therefore does
not ban it; it records whether the operator actually selected it.

### 2.2 Receipt duplicate-warning lifecycle

#### Former mechanism

The receipt mirror was merged with the full current uploader list on every
rerun. Streamlit returns the uploader's complete selected list after any widget
change, so the same bytes appeared once in the mirror and once in the uploader.
The merge correctly discarded the second copy but incorrectly described that
ordinary persistence as a new duplicate selection.

The caller also ran two independent duplicate detectors over the same batch,
which could repeat a filename in the warning.

#### New event model

For each uploader nonce, the workflow stores the prior ordered multiset of
receipt content hashes. `_new_receipt_uploads` subtracts the prior multiset from
the current multiset and returns only newly appeared entries.

Two separate operations now occur:

1. the complete current list is merged into the bounded receipt mirror, which
   preserves data across workflow switches;
2. only newly appeared entries are merged against the mirror to determine which
   filenames deserve a duplicate warning.

A multiset is required rather than a set. If one copy existed previously and a
second file with identical bytes is added under another name, the second
occurrence remains a new event and its chosen filename is reported.

The uploader-seen key contains only hashes and is excluded from the expense
draft mirror. A clear/remove operation rotates the uploader nonce, naturally
starting a new event history.

### 2.3 Operator-local report date

The container remains on UTC. `EPC_TIMEZONE` remains the audited deployment
fallback, but it cannot represent operators in multiple zones using one shared
Render service.

`app.web_ui.main` now reads `st.context.timezone`, Streamlit's IANA browser-zone
value, and passes it through the expense workflow to `_seed_profile`.
`operator_today` resolves dates in this order:

1. valid browser IANA timezone;
2. valid `EPC_TIMEZONE` deployment fallback;
3. container date only if both are absent/invalid.

The server supplies the current instant and applies the browser's zone; it does
not trust a browser-provided date. The result remains an editable default.
Existing reports and already-seeded account drafts are not rewritten.

### 2.4 Smartsheet mapped required values

`load_config` now strips scalar replacement values and rejects empty or
whitespace-only replacements. Runtime defenses remain because a frozen config
object may be built programmatically in tests or survive refactoring:

- `build_prefilled_form_url` records `field: mapped value is empty`, does not
  append the query parameter, and therefore reports a required field missing;
- `handoff_rows` omits an empty mapped row rather than presenting a blank value
  as something the operator can copy.

The source canonical value is still validated against the confirmed internal
catalog. Translation remains exact-match first with the existing
case-insensitive second pass.

### 2.5 Documentation correction

`validate_expense_report` already numbers by unique uploaded source and adds a
line number for split reimbursement rows. Its docstring still described the
superseded line-only behavior. The text now matches the executable rule.

The Smartsheet configuration comment also now records that both the prefilled
URL and manual fallback use the same value translation.

## 3. File and function map

| File | Functions/regions | Responsibility in this change |
|---|---|---|
| `app/web_ui.py` | `_po_coding_draft`, `_po_coding_token_draft`, `_sync_po_coding_field`, `_remember_po_coding_choice`, `main` | Explicit override state, bounded token mirror, browser timezone capture. |
| `app/expense_ui.py` | `render_expense_workflow`, `_seed_profile`, `_new_receipt_uploads` | Timezone propagation and uploader-event multiset. |
| `app/config.py` | `operator_today` | Browser-zone → deployment-zone → container fallback. |
| `app/smartsheet.py` | `load_config`, `build_prefilled_form_url`, `handoff_rows` | Reject/withhold blank mapped values. |
| `app/expense_report.py` | `validate_expense_report` docstring | Align documentation with source-based numbering. |
| `tests/test_object_account_override.py` | new state-transition AppTests | Invalid recovery, workflow round trip, override clearing, malformed mirror. |
| `tests/test_web_ui_app.py` | persistent uploader AppTest | Proves ordinary expense edits do not warn. |
| `tests/test_review_bug_fixes_2026_08_18.py` | timezone and uploader helper tests | Boundary dates, fallback order, profile seeding, multiset behavior. |
| `tests/test_smartsheet_config.py` | mapping regressions | Loader rejection and runtime fail-closed behavior. |

## 4. Regression evidence

### 4.1 PO state cases

- valid synthetic request starts at `5511-SUBCONTRACTOR` and
  `03 - MSAPO (SERVICE)`;
- clearing the final amount displays `NA` while generation remains blocked;
- restoring the amount restores both route-derived values;
- `5490-OTHER` plus `03 - CSAPO (CONSTRUCTION)` survives an Expense → PO round
  trip and reaches `build_po_context`;
- reselecting the current derived account clears the override, after which a
  materials route changes it to `5301-MATERIALS`;
- malformed/obsolete mirror data repairs and remains bounded to one token.

### 4.2 Receipt cases

- first unique upload has no duplicate warning;
- changing Employee name causes a normal rerun and still has no warning;
- a persistent uploader value is not a new addition;
- adding a second copy of existing bytes is detected despite identical hash;
- only the newly chosen filenames are candidates for the warning.

### 4.3 Date cases

- at a simulated cross-midnight boundary, Los Angeles receives August 24 while
  the Eastern deployment fallback has already reached August 25;
- an invalid browser zone uses the configured Chicago fallback;
- an invalid browser and invalid deployment zone return a recoverable container
  date rather than blanking the workflow;
- `_seed_profile` passes the exact browser timezone into `operator_today`.

### 4.4 Smartsheet cases

- whitespace-only replacement is rejected during configuration loading;
- a deliberately constructed stale config with an empty required mapping does
  not encode or copy the value;
- the result lists the field as missing and records the mapped-empty reason.

## 5. Validation record

| Gate | Local result before commit |
|---|---|
| Affected focused suite | 132 passed, 2 expected environment skips |
| Full pytest suite | 496 passed, 3 expected environment skips on the final documented tree |
| Python compilation | `python -m compileall app tests` passed |
| Installed dependency consistency | `pip check` passed |
| Locked dependency vulnerability audit | `pip-audit -r requirements.lock` found no known vulnerabilities |
| Changed-file fatal/static checks | Ruff `E9,F` passed |
| Changed application security scan | Bandit found 0 medium/high issues; 7 low-confidence or documented-control findings were reviewed |
| Patch whitespace | `git diff --check` passed |

The three expected local skips are the CI-runner-only assertion and the two
LibreOffice Writer/Calc import-filter tests. GitHub Actions installs the filters
and must produce zero skips before the release is considered verified.

## 6. Security and data boundaries

- No uploaded receipt bytes, quote content, generated report, email draft,
  employee identity, or contact identity is added to source control.
- The PO coding mirror stores only confirmed catalog strings and a boolean.
- The uploader event history stores only SHA-256 content hashes, not a second
  byte copy.
- Browser timezone affects only an editable default and does not authorize an
  action or alter server credentials.
- No secret, environment variable value, API endpoint, model, or permission is
  added or changed.
- Smartsheet mapping now rejects blank translated values earlier and withholds
  incomplete required fields later.

## 7. Deployment and rollback

- No database migration is required.
- No new package or environment variable is required.
- Streamlit 1.61.1 is already locked and exposes `st.context.timezone`.
- Existing browser sessions can rebuild malformed coding mirrors; a server
  restart is not required for correctness after deployment.
- Rollback is a normal Git revert of this commit. No persisted schema or
  external row must be reverted.
- Render's existing main-branch auto-deploy remains the publication path.

## 8. Deliberately unchanged

- Public authentication and request-rate limiting remain deferred by owner
  direction.
- The four purchase-route rules and the `$25,000` threshold are unchanged.
- `NA` remains a reachable explicit option.
- Smartsheet canonical field labels and option spellings are unchanged.
- Expense reimbursement calculations, receipt AI analysis, workbook/PDF
  generation, and Outlook/iOS attachment flows are unchanged.
- No live Smartsheet submission is performed by tests or this deployment step.

## 9. Release verification still required after push

1. Confirm remote `main` was still `4ce409f` immediately before the fast-forward.
2. Confirm the remote commit tree equals the locally tested tree.
3. Wait for the exact-head GitHub Actions run and require all tests with zero
   skips.
4. Confirm Render serves a healthy root and `/_stcore/health` response from the
   new deployment.
5. Reproduce the Object Account/Agreement workflow round trip on production
   without generating or submitting a package.

## 10. Triage keywords for a future agent

`object account resets`, `agreement type resets`, `NA stuck`, `invalid amount`,
`workflow switch`, `_po_coding_draft`, `duplicate receipt warning`,
`persistent file_uploader`, `receipt multiset`, `wrong report date`,
`st.context.timezone`, `mapped value is empty`, `Smartsheet required field`.

## 11. Concise successor context

Financial coding defaults are now governed by explicit state, not comparison
with a previous value. Never remove the override boolean or move its only copy
back into widget state. Receipt warnings operate on uploader additions, while
receipt persistence operates on the complete current list; combining those two
operations recreates the false-warning defect. Report dates use the browser's
IANA zone with the deployment zone as fallback. Required Smartsheet values are
required after translation, not merely before it.
