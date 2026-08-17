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
explicitly_deferred: public authentication and rate limiting
---

# Commit notes: remediate the two-week review findings

## 1. LLM quick context

This implements every requested finding from the 2026-08-17 two-week review
except the first: public authentication and request-rate limiting. That item is
still open by explicit owner direction; this commit does not alter an access
boundary.

The remaining changes correct silent PO routing, preserve explicit unresolved
choices, pass reviewed values into the MSAPO, bound every OCR transport path,
fix expense approver identity and mileage rounding, repair live UI placement,
improve Smartsheet warnings, and lock production/CI dependencies. The business
routing matrix itself is unchanged.

### 1.1 Invariants

1. A placeholder or explicit deselection stays unresolved; it never becomes
   the first available contract, site, or category.
2. A one-word facility in free prose needs destination/address context. The
   same exact value in the dedicated facility field remains valid evidence.
3. Generic terms such as `system`, `unit`, and bare `pump` do not identify an
   asset among several candidates.
4. Regeneration prints reviewed vendor/facility values, not stale analyzer
   values.
5. Routing negation is clause-local; unrelated legal text cannot cancel a
   positive scope.
6. Vision limits are enforced on the encoded representation before any client
   call, per item and per request.
7. Approver identity is account + normalized name + email, not name alone.
8. Mileage uses decimal half-up cents, matching Excel.
9. Warnings needed to decide whether to leave the page appear before the exit.
10. Deployments install exact reviewed dependency graphs.

## 2. Root causes and fixes

### 2.1 Purchase-order correctness

| Finding | Root cause | Fix and behavior |
|---|---|---|
| One-word facilities such as Beacon, Shaw, Lexington, Newport, Tulane, and UNO matched incidental proposal prose. | `app.contracts` gave a one-token alias equal weight in structured fields and unstructured OCR text. | Dedicated exact values still resolve. In prose, a one-token alias now needs nearby destination/address context. Incidental vendor/customer text abstains instead of selecting another account. |
| Missing/invalid RRH work category became Chemical Treatment. | Separate snapshot/render/context defaults treated missing as option zero; there was no category sentinel. | `CATEGORY_PLACEHOLDER` is a real unresolved state, excluded from PO context. Generation is disabled until a valid category is chosen. |
| Contract/site/category deselections were restored on rerun. | The read-only routing snapshot could not distinguish never answered from explicitly returned to the prompt. | Explicit widget state wins. A prompt remains unresolved and the selector remains in “Needed from you.” |
| Lowest-numbered asset fallback guessed from generic nouns. | The final fallback accepted any derived head noun after exact/scored matching declined. | Only conservative distinctive equipment heads may trigger the fallback. Generic system/unit/pump language returns no guess; exact tags and strong scoring are unchanged. |
| Corrected vendor/facility values invalidated the form but regeneration printed analyzer originals. | The signature included reviewed values, while `build_msapo_pdf` accepted no overrides. | The builder accepts reviewed vendor name, facility name, and address; the web flow passes them. Analyzer values remain backward-compatible fallbacks. |
| Mixed labor/parts/equipment scopes misrouted. | Labor disclaimers and parts detection acted as document-wide vetoes; equipment phrases were not evaluated independently. | Negation is clause-local. Explicit equipment-unit language survives incidental parts text. Genuine “labor by others” in the scope still suppresses that labor clause. |
| Generic pumps became Group A equipment. | Pump detection lacked the hydronic service qualifier required by policy. | Group A pump handling is limited to chilled-water, condenser-water, and heating-water pumps. |
| A completed short proposal retained trailing legal boilerplate. | Scope trimming equated “short” with “possibly incomplete,” even when scope plus total proved completion. | A short proposal with meaningful scope and a total may cut at the legal heading; ambiguous short text remains unchanged. |

Tests cover incidental versus dedicated facility values, category placeholder and
generation blocking, deselection persistence, generic asset abstention, reviewed
MSAPO arguments, mixed-scope routing, qualified pumps, and short proposals.

### 2.2 OCR and vision transport

| Finding | Root cause | Fix and behavior |
|---|---|---|
| Supported native images bypassed normalization. | A raw-byte fast path skipped EXIF orientation, alpha flattening, downscaling, and the final payload limit. | Every supported image decodes through Pillow, orients, flattens onto white, downsizes, and encodes as bounded JPEG. |
| Many valid images could combine into an oversized request. | Only per-image size was considered. | Enforce both per-image and aggregate base64 budgets before the client is called. |
| Native PDFs and rendered PDF pages had inconsistent limits. | Document input and page-fallback paths measured different representations. | Native PDF encoded size is checked before transport. Rendered pages use the same image normalization and a combined page budget. |

Tests prove oversized native PDFs fail before client construction/call and that
image/page batches stay within item and request budgets.

### 2.3 Expense correctness

| Finding | Root cause | Fix and behavior |
|---|---|---|
| Same-name approvers collapsed to one email. | SQLite uniqueness was `(account, normalized_name)` and treated email as mutable metadata. | Identity is `(account, normalized_name, email)`. UI labels add email only when duplicate names require disambiguation. Seed/reselection persists the email. |
| Python mileage could differ from the workbook by one cent. | Binary/half-even `round` disagreed with Excel on midpoint values. | `Decimal` + `ROUND_HALF_UP` at two places matches the workbook formula. |

#### SQLite migration

Existing approver memory upgrades in place and requires no operator command:

1. inspect the schema;
2. acquire `BEGIN IMMEDIATE`;
3. re-read the schema after the write lock, because another worker may have
   migrated while this worker waited;
4. create the replacement table with name + email uniqueness;
5. copy legacy rows, replace the table, and commit atomically.

Failure rolls back transactionally. Tests pin legacy-row preservation,
duplicate-name/different-email storage, and seeded profile restoration.

### 2.4 UI and handoff

| Finding | Root cause | Fix and behavior |
|---|---|---|
| “Needed from you” placement lagged a rerun. | Placement used a stale snapshot while Streamlit rendered top-to-bottom. | Placement uses live needs with one-rerun retention only where widget ordering requires stability. |
| Skipped Smartsheet fields were explained after the outbound link. | Warning/troubleshooting rendered below the primary action. | Warning renders before “Open Smartsheet”; troubleshooting auto-opens when optional fields were skipped. |

## 3. Reproducible dependencies

- `requirements.txt` remains the human-edited production manifest.
- `requirements.lock` is the exact 57-package production graph.
- `requirements-dev.lock` adds exact test/tooling dependencies.
- Docker installs the production lock.
- GitHub Actions installs the dev lock, runs `pip check`, compiles the app, and
  runs the suite. The README documents manifest-versus-lock ownership.

This prevents a deployment from changing solely because a transitive resolver
selected a newer version without a repository diff.

## 4. Validation

| Check | Result |
|---|---|
| Full pytest suite | **444 passed, 3 skipped** |
| Compilation | `python -m compileall -q app pages scripts run_web.py` passed |
| Dependency consistency | `pip check` passed |
| Production lock consistency | Matches all 57 resolved production packages |
| Patch validation | `git diff --check` passed |

Expected local skips: one CI-runner-only assertion and two LibreOffice
writer/calc filter tests. CI installs and exercises those filters.

Regression coverage was added or expanded in facility matching, routing
persistence, lowest-numbered assets, PO rules, MSAPO PDF, OCR images, expense
memory/reporting, needs highlighting, Smartsheet handoff, and Streamlit AppTest.

## 5. Deployment and rollback

- No new environment variable, secret, external service, or permission is
  required.
- The SQLite migration preserves legacy rows. Use the normal volume backup
  before deployment if the environment does not already snapshot it.
- Docker now depends on `requirements.lock`; editing only the manifest no longer
  changes production.
- For a full rollback after migration, restore the pre-deploy database too: old
  code cannot faithfully represent same-name/different-email approvers.

## 6. Not verified

- The three locally skipped runner/renderer cases await CI.
- No live OpenAI call was sent; limits and call prevention use test doubles.
- No live Smartsheet row was created; the handoff boundary is tested locally.
- No production SQLite file was migrated; a legacy-schema fixture was.
- Authentication/rate limiting was neither implemented nor penetration-tested,
  by explicit owner direction.

## 7. Deliberately unchanged

- Public authentication and request-rate limiting.
- PO matrix, account numbers, agreement types, and facility registry values.
- Analyzer prompt/model selection and Smartsheet API permissions.
- Exact-tag and strong-score precedence over asset fallback.
- User data other than automatic approver-memory schema upgrade.

## 8. File map

| Area | Primary files |
|---|---|
| Facility/category/reviewed values | `app/contracts.py`, `app/document_generator.py`, `app/web_ui.py`, `app/po_context.py` |
| Asset and route inference | `app/asset_guess.py`, `app/equipment_policy.py`, `app/po_rules.py` |
| OCR budgets | `app/ocr.py` |
| Expense identity/UI/rounding | `app/memory.py`, `app/expense_ui.py`, `app/expense_report.py` |
| Smartsheet handoff | `app/smartsheet_inline.py` |
| Reproducible builds | locks, `requirements.txt`, `Dockerfile`, workflow, README |
