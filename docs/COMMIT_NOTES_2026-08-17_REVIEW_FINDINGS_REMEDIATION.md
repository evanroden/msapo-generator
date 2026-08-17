---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: fix/review-findings-2026-08-17
base_commit: c7d054a2f2654accffebb2ef8a6c12b632a45bdd
implementation_commit: the commit introducing this document
date: 2026-08-17
workflow: cross_cutting
change_type: review_findings_remediation
status: proposed
review_source: two-week code review requested 2026-08-17
explicitly_deferred: public authentication and rate limiting
follows:
  - CODE_REVIEW_FINDINGS_2026-08-14.md
  - COMMIT_NOTES_2026-08-14_SCOPE_REGION_ROUTING.md
---

# Commit notes: remediate the two-week review findings

## 1. LLM quick context

This change is the implementation follow-through for the broad code review
performed after two weeks of rapid PO and expense-workflow development. The
owner asked to fix every reported issue except the first one. In that review,
the first finding was the absence of public authentication and request-rate
limiting. **That finding remains open by explicit direction; this commit does
not add, remove, or alter an access-control boundary.**

The remaining work is intentionally cross-cutting. It corrects silent routing
errors, prevents the UI from turning a deliberate non-selection back into a
guess, carries reviewed values into the generated MSAPO form, bounds every OCR
transport path, fixes approver-memory identity and mileage rounding, restores
live placement of the "Needed from you" panel, improves the Smartsheet warning
order, and makes production and CI dependency resolution reproducible.

No business matrix was changed. The fixes make the application obey the matrix
and the operator's explicit choices more reliably.

### 1.1 Invariants established or reinforced

1. **An unresolved operator choice stays unresolved.** A placeholder, an
   explicit deselection, or an invalid stored value must not silently become
   the first available contract, site, or work category.
2. **Free-form prose is weaker evidence than a dedicated field.** A one-word
   facility name in proposal prose requires destination/address context; an
   exact value in the facility control remains sufficient.
3. **Fallbacks must abstain when the evidence is generic.** Words such as
   "system", "unit", and bare "pump" do not identify one asset among many.
4. **Reviewed values are the artifact values.** When the operator corrects the
   vendor or facility, regenerating the MSAPO must print those corrected values,
   not the analyzer's stale originals.
5. **Routing negation is local.** "Labor by others" suppresses the clause it
   qualifies; unrelated legal text elsewhere in the proposal must not cancel a
   positive labor scope.
6. **Every vision request is bounded in the representation actually sent.**
   Native images, rendered PDF pages, and native PDFs all have explicit
   per-item and aggregate budgets before the API client is called.
7. **Remembered approvers are identities, not names.** Two people with the same
   display name remain separate when their email addresses differ.
8. **Python and Excel produce the same mileage total.** Monetary rounding is
   decimal half-up at two places, matching the workbook formula.
9. **Warnings precede exits.** Information needed to decide whether to open the
   Smartsheet handoff appears before the link, and troubleshooting opens when
   the app skipped optional fields.
10. **Deployments install a reviewed dependency graph.** Manifests describe
    intent; lockfiles define the exact production and test environments.

## 2. Purchase-order correctness

### 2.1 One-word facility names no longer match incidental prose

#### Symptom

Short registry names such as Beacon, Shaw, Lexington, Newport, Tulane, or UNO
could be found anywhere in extracted quote prose. A vendor address, customer
reference, or unrelated sentence containing one of those ordinary words could
select the wrong facility and therefore the wrong contract, site, cost code,
and downstream job-number options.

#### Cause

`app.contracts` treated a normalized one-token facility alias as adequate
evidence in both structured fields and unstructured prose. The matcher had no
way to distinguish a dedicated facility value from an incidental mention.

#### Fix

- Exact structured facility values continue to resolve directly.
- A one-token alias in quote prose now requires nearby destination/address
  context.
- Multi-token aliases and verified address evidence retain their stronger
  matching behavior.

Regression coverage pins both sides: incidental prose abstains, while the same
one-word name supplied as the explicit facility value still resolves.

### 2.2 RRH work category is now a required decision

#### Symptom

When the RRH work category was absent or stale, the UI and context builder could
coerce it to the first option, Chemical Treatment. That created a plausible but
unsupported cost-code/category selection.

#### Cause

The category selectbox had no first-class placeholder. Separate defaulting
paths in the routing snapshot, renderer, and context builder treated "missing"
as "choose index zero".

#### Fix

- `CATEGORY_PLACEHOLDER` represents the unresolved state explicitly.
- Missing and invalid stored categories normalize to the placeholder.
- The placeholder is excluded from generated PO context.
- Generation remains disabled until the operator chooses a valid category.
- The category control stays visible in the "Needed from you" group while it is
  unresolved.

The test suite exercises helper-level normalization, routing persistence, and a
Streamlit AppTest that proves the real page shows the placeholder and blocks
generation.

### 2.3 Contract, site, and category deselections persist

#### Symptom

An operator could deliberately return a routing selector to its prompt, only to
have the next rerun restore a guessed/default value and move the control out of
the attention panel.

#### Cause

The read-only routing snapshot recomputed defaults without distinguishing "the
widget has never been answered" from "the operator explicitly selected the
placeholder". Placement and rendering therefore disagreed for one rerun.

#### Fix

The snapshot now honors the presence of explicit widget state. A placeholder
is preserved as an unresolved selection, and the live needs calculation keeps
the corresponding selector in the attention panel.

### 2.4 Asset-type fallback now abstains on generic nouns

#### Symptom

The lowest-numbered fallback could select an arbitrary asset when quote text
contained only generic words such as "system", "unit", or "pump".

#### Cause

After exact-tag and scored matching declined, the last fallback used the first
head noun it could derive from the facility asset list. Generic nouns appeared
distinct syntactically even when they were not distinctive operationally.

#### Fix

`app.asset_guess` now permits the fallback only for a conservative set of
distinctive equipment head nouns. Generic equipment language produces no
guess. Exact asset tags and stronger scoring stages are unchanged and still
take precedence.

### 2.5 Reviewed MSAPO values reach the generated form

#### Symptom

Correcting a vendor name invalidated the existing generated form, but
regeneration still printed `analysis.vendor_name`. The Smartsheet payload could
therefore say "Trane U.S. Inc." while the attached MSAPO form still said
"Trane Co." Reviewed facility address/name values had the same propagation
gap.

#### Cause

The document signature correctly included reviewed values, but
`build_msapo_pdf` accepted no vendor/facility overrides. The invalidation signal
and the artifact input were disconnected.

#### Fix

- `build_msapo_pdf` accepts reviewed vendor, facility name, and facility address
  overrides.
- The web workflow passes the current reviewed values into the builder.
- Existing analyzer values remain fallbacks when no override is supplied.

An integration-style web test intercepts the document call and verifies all
three reviewed values are passed, in addition to builder-level PDF tests.

### 2.6 Mixed-scope routing reads positive scope independently

#### Symptoms

- A labor scope could be canceled by "by others" in an unrelated clause.
- A quote containing both equipment and parts language could be forced to the
  materials route even when an explicit equipment-unit purchase was present.
- Any pump could be interpreted as a Group A plant pump.
- A completed short proposal followed by legal boilerplate could remain
  untrimmed because it did not meet the earlier minimum-length guard.

#### Causes

Routing predicates acted as document-wide vetoes. The labor disclaimer regex
crossed clause boundaries, parts detection globally overrode equipment, and the
Group A pump rule did not require the hydronic service qualifiers named by the
business policy. The scope-region guard also equated "short" with "probably not
scope", even when a total and work description proved the proposal complete.

#### Fixes

- Labor negation is evaluated within the local clause carrying the positive
  signal.
- Explicit equipment-unit phrases are evaluated independently of incidental
  parts language.
- Group A pump recognition is restricted to chilled-water,
  condenser-water, and heating-water pumps.
- A short proposal carrying both meaningful scope and a total may be cut before
  trailing terms; ambiguous short text remains untouched.

The routing matrix and account/agreement mappings are unchanged. Tests cover
mixed labor/disclaimer clauses, mixed equipment/parts text, qualified versus
generic pumps, and short completed proposals.

## 3. OCR and vision transport hardening

### 3.1 Every supported image follows the same normalization path

Previously, already-supported formats could bypass decoding and be sent as raw
native bytes while other formats were normalized. That bypass skipped EXIF
orientation, alpha flattening, size reduction, and the final transport budget.

All images now decode through Pillow, apply orientation, flatten transparency
onto white, downscale within the dimension limit, and encode as bounded JPEG.
No extension or MIME type receives an unbounded fast path.

### 3.2 Per-image and aggregate budgets

The code now enforces both:

- a maximum base64 payload for each normalized image; and
- a maximum combined base64 payload for all images in one request.

The aggregate check happens before the API client is invoked, so many
individually valid receipt pages cannot combine into an oversized request.

### 3.3 Native PDF and rendered-page budgets

Native PDFs sent as document input have their own encoded-size limit before the
client call. When a PDF must be rendered into page images, each page follows the
same normalization path and the combined page payload is checked before
transport.

Tests assert that an oversized native PDF fails without constructing/calling
the client, and that rendered images remain within both item and request
budgets.

## 4. Expense-workflow correctness

### 4.1 Approver identity includes email

#### Symptom

Two approvers with the same normalized display name collapsed into one SQLite
row per account. Recalling or reseeding a profile could silently restore the
wrong email address.

#### Cause

The legacy uniqueness key was `(account, approver_name_normalized)`. Email was a
mutable attribute even though it is part of the recipient's identity.

#### Fix

The identity key is now `(account, approver_name_normalized, approver_email)`.
Insertion, listing, recall, and profile seeding use the full key. UI options
remain concise for unique names and add the email only when duplicate names
need disambiguation.

### 4.2 Safe in-place SQLite migration

Existing databases migrate automatically:

1. inspect the approver-memory schema;
2. acquire `BEGIN IMMEDIATE` before changing it;
3. re-read the schema after acquiring the write lock, because another process
   may have completed the migration while this process waited;
4. create the replacement table with the new uniqueness rule;
5. copy legacy rows without discarding existing names or emails;
6. replace the legacy table and commit atomically.

The second schema check prevents two web workers from attempting the same table
replacement concurrently. A failed migration rolls back through SQLite's
transaction boundary. No manual data command is required at deployment.

Tests cover legacy-schema upgrade, preservation of existing rows, duplicate
names with different emails, and the seeded-profile/reselection path.

### 4.3 Mileage rounding matches Excel

Python's binary/half-even `round` could disagree by one cent with the JDE
workbook for midpoint values. Mileage totals now use `Decimal` and
`ROUND_HALF_UP` at two decimal places, matching Excel's monetary behavior.
Boundary regression tests pin the half-cent case.

## 5. UI and handoff behavior

### 5.1 "Needed from you" uses live needs

The previous placement snapshot could lag one rerun behind operator edits. A
selector that had just become unresolved could remain in its normal section,
while a newly completed selector could remain highlighted.

Placement now uses the current needs set and retains the prior placement for a
single rerun only where Streamlit's top-to-bottom widget rendering requires it.
This preserves visual stability without turning stale needs into state.

### 5.2 Smartsheet skipped-field warning precedes the link

Warnings about optional fields that could not be prefilled now render before
the "Open Smartsheet" action. The troubleshooting expander opens automatically
when fields were skipped. Operators therefore see the exception and the manual
correction instructions before leaving the page.

## 6. Reproducible dependencies and CI

`requirements.txt` remains the human-edited production manifest. Two generated
lockfiles now define resolved installations:

- `requirements.lock` — exact production dependency graph;
- `requirements-dev.lock` — production plus test/tooling dependencies.

The Docker image installs the production lock. GitHub Actions installs the dev
lock, runs `pip check`, compiles the application modules, and executes the test
suite. The README documents which files to edit and which files deployments
consume.

This closes the gap where broad transitive dependency ranges could change a
deployment without any repository diff.

## 7. Validation evidence

Validation was run from a clean clone based on `c7d054a` after all code and test
changes:

| Check | Result |
|---|---|
| Full pytest suite | **444 passed, 3 skipped** |
| Python bytecode compilation | `python -m compileall -q app pages scripts run_web.py` passed |
| Installed dependency consistency | `pip check` passed |
| Production lock consistency | lock matches all 57 resolved production packages |
| Patch whitespace/error check | `git diff --check` passed |

The three skips are expected environmental skips:

- one assertion runs only on the GitHub Actions runner;
- two LibreOffice writer/calc filter tests are unavailable in this local
  container. CI installs and exercises those filters.

New or expanded regression coverage lives in:

- `tests/test_facility_matching.py`
- `tests/test_routing_persistence.py`
- `tests/test_lowest_numbered_asset.py`
- `tests/test_po_rules.py`
- `tests/test_msapo_pdf.py`
- `tests/test_ocr_images.py`
- `tests/test_expense_memory.py`
- `tests/test_expense_report.py`
- `tests/test_needs_value_highlight.py`
- `tests/test_smartsheet_handoff_entrypoint.py`
- `tests/test_web_ui_app.py`

## 8. Deployment and rollback notes

- No new environment variable, secret, external service, or API permission is
  required.
- The approver-memory migration runs on the existing SQLite file and preserves
  legacy rows. Take the normal persistent-volume backup before deployment if
  the environment does not already snapshot it.
- The Docker build now depends on `requirements.lock`; changing only
  `requirements.txt` will not change production until the lock is regenerated.
- Rolling application code back after the SQLite migration is not expected to
  lose data, but the old code's name-only uniqueness assumption cannot represent
  duplicate-name approvers faithfully. Restore the pre-deploy database backup
  as well if a full behavioral rollback is required.

## 9. What was NOT verified

- The three locally skipped renderer/runner cases were not executed in this
  container; their CI job is the verification environment.
- No live OpenAI request was sent. Transport limits and call prevention are
  verified with test doubles.
- No live Smartsheet row was created. The browser handoff and skipped-field
  presentation are verified at the UI/entrypoint boundary.
- No production SQLite file was migrated. The migration is verified against a
  legacy-schema fixture and concurrent-safe transaction logic.
- Authentication and rate limiting were not implemented or penetration-tested,
  because the owner explicitly deferred that first finding.

## 10. Deliberately unchanged

- Public access/authentication and request-rate limiting: deferred by explicit
  owner instruction.
- The PO business routing matrix, object-account numbers, agreement types, and
  facility registry values.
- The analyzer/model prompt and model selection.
- Smartsheet API mode and permissions.
- The rule that exact asset tags and strong scored matches win before any
  lowest-numbered fallback.
- The existing user data other than the automatic approver-memory schema
  upgrade.

## 11. File map

| Area | Primary files |
|---|---|
| Facility, category, and reviewed-value contracts | `app/contracts.py`, `app/document_generator.py`, `app/web_ui.py`, `app/po_context.py` |
| Asset and route inference | `app/asset_guess.py`, `app/equipment_policy.py`, `app/po_rules.py` |
| OCR request bounds | `app/ocr.py` |
| Expense identity, UI, and rounding | `app/memory.py`, `app/expense_ui.py`, `app/expense_report.py` |
| Smartsheet handoff | `app/smartsheet_inline.py` |
| Reproducible builds | `requirements.txt`, `requirements.lock`, `requirements-dev.lock`, `Dockerfile`, `.github/workflows/tests.yml`, `README.md` |
| Regression tests | the eleven test modules listed in §7 |
