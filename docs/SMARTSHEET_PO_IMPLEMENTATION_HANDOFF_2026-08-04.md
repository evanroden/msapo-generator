# Smartsheet PO Implementation Handoff — 2026-08-04

> **Historical implementation record.** The authoritative business policy as of
> 2026-08-08 is
> [`STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md`](STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md).
> Preserve this file for incident history, but do not restore its prior
> email/EPO/MSAPO package rules.

## 0. Purpose and authority

This document is the implementation-level handoff for the Smartsheet PO work added to draft PR #25. It is written for a future developer or coding agent that may need to test, repair, extend, merge, or replace this work without access to the original conversation.

For this feature, use the following authority order:

1. Evan's explicit business rules in this handoff.
2. The final live Smartsheet form, screenshots, and internal-sheet workbook supplied on 2026-08-04.
3. The invariants already enforced by Email Process Control.
4. Code defaults and inferred mappings.

Do not replace an explicit business rule with a plausible technical assumption.

## 1. Current repository and PR state

- Repository: `evanroden/MSAPO-generator`
- Product: Email Process Control
- Draft PR: #25, `agent/smartsheet-three-mode` into `main`
- Core implementation commit: `9c197fc71d65c5e93acfa19c9731b592b9c18131`
- PR state after the implementation commit: open, draft, mergeable
- Full GitHub Actions result on the implementation commit: 59 tests passed
- PR #26 is stacked on the PR #25 branch and must be refreshed/reconciled after PR #25 changes before it is merged.

The PR remains draft because the manual path still needs a real-device Safari pass and an end-to-end test against the actual form. URL-prefill and direct API modes remain disabled.

## 2. What Evan requested

The requested behavior was:

1. Remember the requester based on the browser/device accessing the site.
2. Learn only after the same requester has been entered three times on that browser.
3. Always use `PO` as Request Type because Email Process Control currently creates only purchase orders.
4. Always use `NA` for `DISPATCH WO TO SERVICE CENTER?` because service-center dispatch applies only to work orders.
5. Prioritize RRH job numbers and use the supplied RRH subset rather than rendering the entire Smartsheet job catalog.
6. Use the completed live form URL:

   `https://app.smartsheet.com/b/form/019e8e6717c471628f9a02280a892100`

7. Use the uploaded internal-sheet workbook and screenshots as the source for exact field labels, required fields, and option text.

## 3. Evidence supplied for the implementation

### 3.1 Final public form

The live form URL above was supplied directly by Evan. Screenshots showed the field order, required indicators, dropdown choices, attachment control, and mobile layout.

### 3.2 Internal Smartsheet workbook

The supplied workbook was named `WORK ORDERS_PURCHASE ORDERS REQUEST FORM.xlsx`. Its sheet `WORK ORDERS_PURCHASE ORDERS REQ` contained the following 19 internal columns, in order:

1. `REQUEST COMPLETED`
2. `PO #`
3. `WORK ORDER #`
4. `REQUESTER`
5. `JOB NUMBER`
6. `SITE NUMBER / LOCATION`
7. `REQUEST TYPE`
8. `COST CODE`
9. `OBJECT ACCOUNT`
10. `AGREEMENT TYPE FOR PO`
11. `ORIGIONAL PO NUMBER`
12. `VENDOR NAME`
13. `VENDOR CONTACT NAME`
14. `VENDOR CONTACT EMAIL`
15. `DESCRIPTION OF WORK`
16. `PO/CO AMOUNT`
17. `ASSET ID`
18. `DISPATCH WO TO SERVICE CENTER?`
19. `ADDITIONAL INFORMATION IF NEEDED`

The misspelling `ORIGIONAL PO NUMBER` exists in the live system and is preserved intentionally. Do not silently correct it in external field mappings unless the Smartsheet administrator first renames the actual column and form field.

The workbook did not contain the RRH job-number rows needed for the new flow. The authoritative RRH choices came from Evan's screenshots and prior confirmed context.

### 3.3 Required form fields

The screenshots confirmed these required inputs:

- `REQUEST TYPE`
- `REQUESTER`
- `JOB NUMBER`
- `SITE NUMBER / LOCATION`
- `COST CODE`
- `OBJECT ACCOUNT`
- `AGREEMENT TYPE FOR PO`
- `PO/CO AMOUNT`
- `DESCRIPTION OF WORK`
- `DISPATCH WO TO SERVICE CENTER?`

Vendor and vendor-contact fields, asset ID, original PO number, and additional information appeared optional.

## 4. Business rules that must not regress

### 4.1 Purchase-order-only scope

Email Process Control currently creates POs, not work orders.

- `REQUEST TYPE` must be exactly `PO`.
- It is locked on the Smartsheet handoff page.
- The value is also validated against the exact allowed value `PO` before any route can proceed.
- Do not expose `WO`, `BOTH PO&WO`, or `CHANGE ORDER` in the current workflow.

If work orders are added later, implement an explicit workflow type with separate required fields and validation. Do not infer a work order from an empty PO field or reuse the current PO constants conditionally in scattered UI code.

### 4.2 Service-center dispatch

Service-center dispatch is used for work orders, not the current PO workflow.

- `DISPATCH WO TO SERVICE CENTER?` must be exactly `NA`.
- It is locked on the handoff page.
- Validation rejects `LITTLE ROCK`, `DALLAS`, `LAFAYETTE`, `OTHER`, or any other value in this PO workflow.

Evan described the value as N/A; the exact dropdown option visible in Smartsheet is `NA`, so the implementation uses `NA`.

### 4.3 MSAPO and equipment-only behavior

The preexisting invariant remains authoritative:

- Standard orders generate an MSAPO for every contract, not only RRH.
- Equipment-only POs skip MSAPO generation and attach the original quote only.
- Never reintroduce PR #10's rejected RRH-only document gating.

The Smartsheet defaults are:

| Email Process Control mode | Object account | Agreement type |
|---|---|---|
| Standard MSAPO | `5511-SUBCONTRACTOR` | `03 - MSAPO (SERVICE)` |
| Equipment-only PO | `5302-EQUIPMENT` | `OR - EQUIPMENT PO` |

Object account remains editable on the handoff page because a person may need one of the other confirmed account choices. Agreement type remains locked to the Email Process Control order mode so it cannot contradict the generated document package.

## 5. Exact option catalogs represented in code

### 5.1 RRH job numbers

RRH defaults to the O&M job number and offers exactly the four supplied choices:

1. `RRH-695400022-O&M`
2. `RRH-695400023-START UP`
3. `RRH-695400030-ISDC`
4. `RRH-695400034-ES JOB CCJ`

The default is `RRH-695400022-O&M`.

Non-RRH contracts use exact free-text entry until authoritative job catalogs are supplied. Do not copy RRH choices into other contracts or guess non-RRH values from naming patterns.

### 5.2 Object accounts

The confirmed dropdown choices are:

1. `5301-MATERIALS`
2. `5490-OTHER`
3. `5511-SUBCONTRACTOR`
4. `5302-EQUIPMENT`
5. `5411-OUTSIDE RENTALS`

### 5.3 Agreement types

The confirmed dropdown choices are:

1. `NA`
2. `03 - MSAPO (SERVICE)`
3. `03 - MRAPO (RENTAL)`
4. `03 - CSAPO (CONSTRUCTION)`
5. `ON - STANDARD PO UNDER $25K`
6. `OR - STANDARD PO OVER $25K`
7. `OR - EQUIPMENT PO`

Only the MSAPO service and equipment-PO options are selected automatically today because those are the two modeled Email Process Control order modes.

### 5.4 Service centers

The live form displayed:

- `NA`
- `LITTLE ROCK`
- `DALLAS`
- `LAFAYETTE`
- `OTHER`

The current PO flow always uses `NA`.

## 6. Final logical field model

`app/smartsheet.py` contains the external field registry. Unknown internal source fields are deliberately excluded from manual rows, URL prefilling, and API mappings.

| Logical field | Exact external label | Required | Source/default | Handoff behavior |
|---|---|---:|---|---|
| `request_type` | `REQUEST TYPE` | Yes | Constant `PO` | Locked |
| `requester_name` | `REQUESTER` | Yes | Environment fallback or remembered browser requester | Editable |
| `job_number` | `JOB NUMBER` | Yes | RRH O&M default; blank for other contracts | RRH select; non-RRH exact text |
| `site_location` | `SITE NUMBER / LOCATION` | Yes | Reviewed source site | Editable only for exact Smartsheet option wording |
| `cost_code` | `COST CODE` | Yes | Existing verified workflow value | Locked |
| `object_account` | `OBJECT ACCOUNT` | Yes | Mode-dependent default | Confirmed selectbox |
| `agreement_type` | `AGREEMENT TYPE FOR PO` | Yes | Mode-dependent default | Locked |
| `original_po_number` | `ORIGIONAL PO NUMBER` | No | Blank | Reserved for future change-order support |
| `total` | `PO/CO AMOUNT` | Yes | Reviewed quote total | Locked and amount-validated |
| `vendor` | `VENDOR NAME` | No | Reviewed analysis | Locked |
| `contact_name` | `VENDOR CONTACT NAME` | No | Reviewed contact | Locked |
| `contact_email` | `VENDOR CONTACT EMAIL` | No | Reviewed contact email | Locked and email-validated when present |
| `description_of_work` | `DESCRIPTION OF WORK` | Yes | Reviewed scope plus approved inclusions/exclusions | Locked |
| `asset_id` | `ASSET ID` | No | Selected verified asset | Locked; blank for no asset/EPO |
| `dispatch_service_center` | `DISPATCH WO TO SERVICE CENTER?` | Yes | Constant `NA` | Locked |
| `instructions` | `ADDITIONAL INFORMATION IF NEEDED` | No | Tax note/default | Editable |
| `send_copy_email` | `Send me a copy of my responses` | No | Blank | Optional form checkbox |
| `submission_key` | `Email Process Control Submission Key` | API only | Deterministic hash | Requires a future dedicated sheet column |

The internal source fields `contract`, `site`, `scope_of_work`, `order_type`, tax components, administrator email, and other orchestration values remain available to the context builder but are not automatically emitted as final Smartsheet inputs unless explicitly registered.

## 7. Requester memory design

### 7.1 Why it is browser-profile memory

The implementation does not fingerprint hardware. It assigns one random identifier to a browser profile. This is safer, simpler, and predictable:

- Same device and same browser profile: remembered.
- Same device but another browser: separate identity.
- Private browsing: separate or temporary identity.
- Cleared site data/cookies: memory starts over.
- Blocked cookies: requester memory is disabled, but the PO workflow continues.

Future UI and documentation should say “this browser” rather than promising recognition of physical hardware.

### 7.2 Browser identifier

`app/device_identity.py` implements the identifier:

1. Cookie name: `epc_device_id`.
2. Generates 16 random bytes and stores 32 lowercase hexadecimal characters.
3. Uses `window.crypto.getRandomValues` when available.
4. Uses a one-year `Max-Age`, `Path=/`, and `SameSite=Lax`.
5. Adds `Secure` on HTTPS.
6. Reloads the parent page once after successful cookie creation so `st.context.cookies` can see it on the next request.
7. Avoids an infinite reload through a session-storage guard.
8. Returns an empty identity when the cookie is absent or malformed.

The cookie contains no requester name, quote data, vendor, price, site, asset, or PO identifier.

### 7.3 Server-side privacy boundary

The raw random browser token is hashed with SHA-256 before SQLite storage. The database stores the hash, requester display name, normalized requester key, use count, timestamps, and opaque PO context IDs.

The requester name itself is stored because it is the value being learned. Do not claim that the database contains no requester PII; the privacy property is that the browser cookie contains no PII and the raw browser token is not persisted.

### 7.4 SQLite schema

Two tables were added to the existing `epc_memory.db` schema:

`device_requesters`

- `device_hash`
- `requester_key`
- `display_name`
- `use_count`
- `last_used`
- primary key: `(device_hash, requester_key)`

`device_requester_events`

- `device_hash`
- `context_id`
- `requester_key`
- `recorded_at`
- primary key: `(device_hash, context_id)`

The schema is installed with `CREATE TABLE IF NOT EXISTS`, so an existing production database is upgraded in place without deleting the older contract-memory tables.

### 7.5 What counts as one use

A use is one distinct verified Email Process Control PO context, not a Streamlit rerun and not a keystroke.

The page records a requester only when all of the following are true:

1. A valid browser token exists.
2. Requester name is nonempty.
3. The source PO context has no warnings.
4. The verified manual form URL is configured.
5. All confirmed required form fields are populated.

The context ID is a deterministic 20-character digest of the finalized source fields and attachment names/content hashes. The event table's primary key prevents the same context from incrementing repeatedly during Streamlit reruns or repeated page visits.

Important limitation: this currently counts a completed, valid handoff context, not a proven Smartsheet form submission. There is no callback from the external form. If future business policy requires three confirmed submissions, move the learning event to an explicit locally recorded completion action or an API-confirmed row result.

### 7.6 Normalization, correction, and takeover

- Requester whitespace is collapsed.
- Matching uses case-folded normalized text.
- Display casing is retained and updated.
- If a requester is corrected on the same context, the old requester's count is decremented and the event is moved; the correction does not create a second use.
- Learning begins at three distinct contexts.
- The most recently used requester that has reached three contexts is selected.
- A different primary user can take over a shared browser after entering their own name on three distinct contexts.
- A visible Forget action removes only this browser's requester rows/events and does not delete contract-specific administrator/vendor memory.

Writes use `BEGIN IMMEDIATE` so concurrent Streamlit requests cannot race the same event count.

### 7.7 Operational dependency

Requester memory uses the same persistent SQLite location as existing learning:

- Render: `EPC_DATA_DIR=/test1`
- Local fallback: repository `data_store`

The feature soft-fails when storage is unavailable. It must not crash or block PO preparation.

SQLite remains a single-instance design. Before Render scales horizontally, move requester learning, contract learning, and Smartsheet idempotency to a shared transactional database.

## 8. Source-record and attachment controls

`app/po_context.py` remains the boundary between the current email workflow and Smartsheet.

The implementation added final PO fields but retained these protections:

1. Analysis token must match the stored quote text.
2. Uploaded quote bytes must match the extraction hash and analyzed text before reuse.
3. Pasted text cannot accidentally attach a prior upload.
4. Contract and site must be explicitly selected.
5. Cost code and total must be present.
6. Standard MSAPO documents must exist and match the document signature for analysis, contract, site, inclusions, and exclusions.
7. Stale generated files are excluded.
8. Original quote bytes remain unchanged.
9. Standard MSAPO attachments are quote plus DOCX and PDF when conversion succeeded.
10. Equipment-only attachments contain the quote only.
11. Subtotal plus tax is compared with total when all are parseable.
12. No-asset selections are emitted as blank rather than the phrase `None Applicable`.

The handoff page shows the source site separately from the editable `SITE NUMBER / LOCATION` value. This makes any adjustment to match Smartsheet's exact dropdown wording visible rather than silently rewriting the document's facility.

## 9. Manual, URL-prefill, and API activation state

### 9.1 Manual route

The Render blueprint and `.env.example` now contain the verified form URL. This enables the manual copy assistant when the PR is deployed.

The assistant:

- displays populated values in the final form order;
- supports one-tap copy and progress tracking;
- keeps progress isolated to the exact label/value set;
- provides safely named adjacent downloads for the quote and MSAPO files;
- blocks opening when source warnings, field validation, missing required inputs, or attachment preflight failures exist.

### 9.2 URL prefill

URL-prefill remains off:

- `SMARTSHEET_URL_PREFILL_ENABLED=false`

Earlier attempts showed that Smartsheet query prefilling was not proven and cannot carry file attachments. Do not enable it merely because the visible field labels are now known. First prove query behavior against the live form with non-production values and exact option text.

### 9.3 Direct API

Direct API remains off:

- `SMARTSHEET_API_MODE=disabled`

The workbook and screenshots reveal titles but not safe API column specifications. Live API mode still requires:

1. Approved least-privilege service-account token.
2. Exact destination sheet ID.
3. Exact numeric column IDs.
4. Exact titles, types, and dropdown options.
5. Dedicated writable full submission-key text column.
6. Confirmed API required-field list.
7. Dry-run schema validation.
8. Controlled test row with all attachments.
9. Ambiguous-write and partial-attachment recovery exercises.

Never restore the old alias-based title matching or `strict:false` coercion.

## 10. Deployment configuration

`render.yaml` now sets:

- `EPC_DATA_DIR=/test1`
- `SMARTSHEET_FORM_URL=https://app.smartsheet.com/b/form/019e8e6717c471628f9a02280a892100`
- `SMARTSHEET_URL_PREFILL_ENABLED=false`
- `SMARTSHEET_PREFILL_MAX_URL_LENGTH=7000`
- `SMARTSHEET_API_MODE=disabled`
- `SMARTSHEET_ALLOW_CUSTOM_API_BASE=false`

API token and sheet ID remain unconfigured secrets.

Render dashboard environment values can shadow the blueprint. This previously caused a model-ID fix to appear ineffective. During deployment verification, compare the dashboard and `render.yaml`, especially `SMARTSHEET_FORM_URL`, `EPC_DATA_DIR`, and all Smartsheet mode flags.

## 11. File-by-file change map

### `app/device_identity.py` — new

- Creates and validates the anonymous browser cookie.
- Contains no requester or PO values.
- Soft-fails when cookies are unavailable.

### `app/memory.py`

- Adds the two requester-memory tables.
- Adds the three-use threshold.
- Adds record, retrieve, and forget operations.
- Deduplicates reruns by context ID.
- Handles correction and shared-browser takeover.
- Keeps older contract-scoped contact learning intact.

### `app/po_context.py`

- Emits the final PO field set.
- Locks Request Type to `PO` and dispatch to `NA`.
- Defaults RRH to O&M job number.
- Maps standard/EPO object account and agreement type.
- Reuses reviewed scope as `DESCRIPTION OF WORK`.
- Converts no-asset/EPO to blank asset ID.

### `app/smartsheet.py`

- Replaces the provisional work-order-oriented field registry with exact PO labels.
- Preserves `ORIGIONAL PO NUMBER` deliberately.
- Defines final field order and confirmed required fields.
- Defines exact RRH jobs, object accounts, and agreement types.
- Enforces exact PO/NA and dropdown validation.
- Skips unknown internal fields in manual and prefill output.
- Retains fail-closed API/idempotency controls.

### `pages/2_Smartsheet_PO.py`

- Reads/creates the browser identity.
- Prefills a learned requester.
- Exposes requester-memory status and Forget action.
- Shows locked Request Type, source contract/site, cost code, agreement, dispatch, quote values, and document values.
- Uses the RRH job select and editable non-RRH job entry.
- Allows exact Smartsheet site wording and object-account confirmation.
- Records only complete warning-free contexts.

### `.env.example` and `render.yaml`

- Configure the verified form URL.
- Keep URL-prefill/API modes off.
- Document exact logical fields and safety gates.

### `README.md`

- Documents the final form, requester memory, PO/NA rules, RRH choices, privacy boundary, and activation state.

### `docs/FAILURE_MODES_AND_CONTROLS.md`

- Removes the claim that the final form is unknown.
- Adds shared-browser requester risks and controls.
- Updates manual activation and residual blockers.

### Tests

- `tests/test_device_identity.py`
- `tests/test_requester_memory.py`
- `tests/test_po_context.py`
- `tests/test_smartsheet_config.py`
- `tests/test_smartsheet_api.py`

## 12. Verification completed

### 12.1 Focused local verification

The reconstructed focused checkout passed:

- 34 focused tests
- Python compilation for changed app/page/test files
- import ordering and unused-symbol lint for changed files
- `.env.example` parse with manual enabled and URL-prefill/API disabled
- `render.yaml` parse with the exact form URL and disabled automation
- Streamlit startup and `/_stcore/health` smoke test

### 12.2 Full repository verification

GitHub Actions run #46 on `9c197fc` passed:

- 59 tests passed
- 0 failures

### 12.3 Behaviors covered by regression tests

Tests cover:

- exact final form order and required fields;
- exact four RRH jobs and O&M default;
- exact PO/NA output and rejection of WO/service-center alternatives;
- standard and EPO object/agreement defaults;
- final scope, site, asset, and original quote behavior;
- requester threshold after three distinct contexts;
- browser isolation;
- rerun deduplication;
- name correction without double-counting;
- forgetting one browser without affecting another;
- new primary-user takeover after three uses;
- hashing of the raw device token before persistence;
- exact API schema/value coercion and drift blocking;
- prior Smartsheet idempotency and attachment recovery controls.

## 13. What has not been verified

Do not convert these unknowns into claims:

1. No real Smartsheet form response was submitted by this implementation work.
2. No live Smartsheet API call was made.
3. URL-prefill behavior remains unproven and disabled.
4. Requester-cookie persistence has not been tested on a real iPhone or iPad Safari build.
5. Clipboard fallback has not been retested on real Safari after this field-model update.
6. Exact RRH `SITE NUMBER / LOCATION` dropdown option strings were not supplied.
7. Non-RRH job-number/site catalogs were not supplied.
8. The attachment field's multi-file behavior and practical size limits need a real-form pass.
9. The Render dashboard and `/test1` persistent disk were not inspected during this code change.
10. Authentication/SSO remains unresolved before broad rollout.
11. API column IDs/types/options and service-account permissions remain unknown.
12. Multiple assets per PO remain unsupported.

## 14. Required manual acceptance procedure

Use a preview deployment or approved test deployment. Do not create a production PO merely to test convenience behavior.

### 14.1 Standard RRH PO

1. Process a readable RRH quote through Email Process Control.
2. Select the correct RRH site, work category, cost code, contact, and asset/no-asset state.
3. Generate the MSAPO package.
4. Open the Smartsheet PO handoff.
5. Confirm Request Type displays `PO` and cannot be changed.
6. Confirm dispatch displays `NA` and cannot be changed.
7. Confirm RRH job defaults to `RRH-695400022-O&M`.
8. Confirm all four and only the four supplied RRH jobs appear.
9. Confirm object account defaults to `5511-SUBCONTRACTOR`.
10. Confirm agreement type is `03 - MSAPO (SERVICE)`.
11. Confirm the source site is visible separately from the Smartsheet site/location entry.
12. Confirm description contains the reviewed scope and approved inclusions/exclusions.
13. Confirm quote/DOCX/PDF downloads have adjacent safe names and correct bytes.
14. Open the live form and copy each value in order.
15. Confirm the form accepts exact PO, job, object-account, agreement, and NA values.
16. Attach every required file and verify multi-file behavior.
17. Stop before Submit unless the test response has been explicitly authorized.

### 14.2 Equipment-only PO

1. Repeat with Equipment-only PO mode.
2. Confirm Request Type remains `PO`.
3. Confirm object account defaults to `5302-EQUIPMENT`.
4. Confirm agreement type is `OR - EQUIPMENT PO`.
5. Confirm Asset ID is blank.
6. Confirm only the unchanged quote is offered as an attachment.
7. Confirm dispatch remains `NA`.

### 14.3 Requester memory

Use three different valid PO contexts, not repeated reruns of one quote.

1. On browser A, enter the same requester on PO context 1.
2. Confirm the UI says two more prepared POs are needed.
3. Trigger ordinary Streamlit reruns on context 1 and verify the count does not advance.
4. Enter the same requester on context 2 and confirm one more is needed.
5. Enter the same requester on context 3 and confirm remembered status.
6. Open context 4 and confirm the requester prefills.
7. On browser B or a separate profile, confirm no requester is inherited.
8. Correct a name on one context and confirm the mistaken name is not double-counted.
9. Use a second requester on three new contexts and confirm that requester becomes the new prefill.
10. Press Forget and confirm the next context is blank while contract/vendor memories remain unaffected.
11. Repeat the essential path on real iPhone Safari and real iPad Safari.
12. Clear site data and confirm requester memory safely starts over.

## 15. Troubleshooting and recovery

### Requester never becomes remembered

Check, in order:

1. The same browser profile is being used.
2. Cookies/site data are allowed.
3. Three distinct valid context IDs were used.
4. The source contexts have no warnings.
5. All required fields are complete.
6. `SMARTSHEET_FORM_URL` is configured.
7. `EPC_DATA_DIR` is writable and the Render disk is mounted.
8. The app remains single-instance or uses shared storage.

Do not lower the threshold or count reruns to mask a cookie/disk problem.

### Wrong requester prefills on a shared browser

1. Use the visible Forget action.
2. Enter the correct requester on three distinct new contexts.
3. Consider separate browser profiles on a permanently shared workstation.

Do not silently bind a requester to IP address, user agent, or device fingerprint.

### Manual route remains unavailable after deployment

1. Compare `render.yaml` and Render dashboard `SMARTSHEET_FORM_URL`.
2. Confirm the value is the exact HTTPS Smartsheet form URL.
3. Check startup for configuration validation errors.
4. Confirm the deployed commit includes the final form model.

### Required fields appear missing despite reviewed source data

1. Return to Email Process Control.
2. Resolve contract, source site, cost code, amount, and document warnings.
3. Regenerate the MSAPO if the signature is stale.
4. Reopen the handoff so its context ID and widget namespace reset.
5. Enter the exact job and site/location option where catalogs are incomplete.

## 16. How to add work orders later

Work-order support is explicitly deferred. When it is authorized:

1. Add a first-class workflow type rather than overloading EPO/MSAPO mode.
2. Define work-order-specific required fields from an authoritative form/schema.
3. Add service-center routing with exact options and an explicit default decision.
4. Decide whether `WORK ORDER #`, `PO #`, or both are user-entered or generated.
5. Separate WO attachment/document rules from MSAPO rules.
6. Namespace learning and idempotency by workflow type where required.
7. Add regression fixtures for PO, WO, both, and change-order paths.
8. Preserve the current invariant that PO flow always emits `PO` and `NA` until the user deliberately selects a different supported workflow.

Do not expose the dormant Smartsheet `WO` choices before this design exists.

## 17. Non-regression checklist for future changes

Before modifying this feature, confirm that the change preserves all of the following:

- All contracts still receive MSAPO documents for standard orders.
- EPO still skips MSAPO and uses quote-only attachment behavior.
- RRH remains the priority flow.
- Contract learning remains isolated.
- No asset is preferred over an unsupported guess.
- Original quote bytes remain unchanged.
- Stale analysis/documents/attachments block handoff.
- Request Type remains exactly `PO` for the current tool.
- Service-center dispatch remains exactly `NA` for the current tool.
- RRH O&M remains the default unless Evan changes it.
- Browser requester learning requires three distinct contexts.
- Streamlit reruns never increase the learning count.
- The browser cookie contains no requester or PO values.
- Raw browser tokens are not stored.
- Shared users can forget or replace the learned requester.
- Cookie/storage failure degrades to manual entry rather than workflow failure.
- Manual form URL is verified independently of URL-prefill/API modes.
- URL-prefill remains off until proven.
- API remains off until exact IDs/types/options and live recovery tests exist.
- Render dashboard overrides are checked during deployment.
- SQLite is not treated as shared multi-instance storage.

## 18. Immediate next actions

1. Deploy PR #25 to an approved preview/test environment.
2. Run the standard and EPO acceptance paths against the live form without creating an unauthorized production response.
3. Run requester learning on real iPhone and iPad Safari.
4. Capture the exact RRH `SITE NUMBER / LOCATION` option strings.
5. Verify the form attachment control with quote, DOCX, and PDF together.
6. Confirm `/test1` persistence across a Render restart.
7. Resolve the stacked PR #26 conflict/base relationship after PR #25 stabilizes.
8. Keep PR #25 draft until those checks are recorded.

## 19. Compact successor instruction

> Continue from draft PR #25 on `agent/smartsheet-three-mode`. The live manual Smartsheet PO form is configured, but URL-prefill and API writes remain disabled. The current tool must always emit Request Type `PO` and service-center dispatch `NA`. RRH defaults to `RRH-695400022-O&M` and offers four confirmed RRH job numbers. Requester memory is per browser profile: an opaque cookie is hashed server-side, and the most recent requester with three distinct valid PO contexts is prefilled; reruns do not count, corrections move one event, and users can forget the browser. Preserve all existing source/document/attachment safety gates. Before merge, test the manual form and requester cookie on real iPhone/iPad Safari, verify exact RRH site/location options and multi-file attachment behavior, inspect Render disk persistence, and reconcile stacked PR #26.

## Production integration correction — 2026-08-06

### What production testing found

Render correctly deployed merge commit 155d6dc2af003b97d7df7d59de71c3d7c4cdfc55, and the
pages/2_Smartsheet_PO.py route existed. That did **not** make the handoff
usable from the ordinary Email Process Control workflow:

- run_web.py starts with the Streamlit sidebar collapsed.
- app/web_ui.py contained no visible Smartsheet action after email preparation.
- The only discoverable route was Streamlit's sidebar navigation.
- A user opening /Smartsheet_PO directly created a new Streamlit websocket
  session, so st.session_state no longer contained the analyzed quote,
  reviewed routing, document signatures, or attachment bytes.
- The direct page therefore displayed “Analyze a vendor quote in Email Process
  Control first,” even though the user had completed the workflow in another
  session.

The prior deployment checks proved that the service and commit were live; they
did not prove that the new feature was reachable with its required session state.
Future acceptance must distinguish infrastructure health from workflow
reachability.

### Correction

app/web_ui.py now renders an explicit **Continue to Smartsheet PO handoff**
control immediately after the email/share panel and before contact-learning
confirmation.

The first production correction used st.page_link. A second live test proved
that this deployment rendered the page link as an ordinary route navigation;
following it opened a fresh websocket and again lost st.session_state. The
final control is therefore a Streamlit button whose active-session event calls
st.switch_page("pages/2_Smartsheet_PO.py"). The page switch occurs server-side
inside the existing session.

A third live pass showed that preserving the session alone was still
insufficient: Streamlit removes widget-backed session keys when their widgets
are not rendered on the destination page. Analysis state survived, but
contract, site, cost code, asset, contact, and pricing widget values could
disappear before the handoff rebuilt its context. The source page now calls
build_po_context while every source widget is still rendered, stores the
immutable POContext under PREPARED_PO_CONTEXT_STATE_KEY, and then switches
pages. The destination consumes that verified non-widget snapshot on every
rerun. Returning to the source page clears the snapshot so a later handoff
must be rebuilt from current values.

The visible step number remains correct for both supported workflows:

- Standard MSAPO: Step 4 email → Step 5 Smartsheet.
- Equipment-only PO: Step 3 email → Step 4 Smartsheet.

A caption tells the user to continue in the same tab because opening the route
as a fresh URL cannot carry transient session state.

### Regression boundary

tests/test_smartsheet_handoff_entrypoint.py verifies that:

1. the main workflow calls the handoff renderer after the email/share renderer;
2. the renderer uses a button followed by st.switch_page, rather than a direct
   page link or URL;
3. the label, primary treatment, and full-width presentation remain explicit; and
4. the standard/EPO step-number selection remains present.

The regression checks also require the source to build and persist the
verified snapshot before st.switch_page, require the destination to prefer it
over reconstructing from disappearing widget keys, and require the source page
to invalidate any old snapshot when it is rendered again.

### Production acceptance for this correction

A deployment is accepted only when all of the following are true:

1. GitHub Actions passes on the correction commit.
2. Render reports that exact commit as live.
3. The root workflow returns HTTP 200 and Streamlit health returns ok.
4. A sample or redacted quote can be analyzed and its MSAPO generated.
5. The main page visibly presents **Continue to Smartsheet PO handoff**.
6. Activating that control changes to the Smartsheet page without starting a
   blank context.
7. The Smartsheet page displays the prepared PO fields and verified attachments,
   rather than the “Analyze a vendor quote first” message.
8. Manual mode opens the configured production form; URL prefill and API mode
   remain disabled.

Do not treat a Render live status or HTTP 200 health response alone as proof
that a cross-page Streamlit workflow is usable.

## Mobile state-loss incident and inline-route correction — 2026-08-06

### User-visible production failure

An actual iPhone Safari attempt disproved the final assumption in the prior
correction. The user completed quote analysis and document preparation, tapped
the Smartsheet action, and arrived at the separate **Smartsheet PO Handoff**
page. That page contained only this empty-state message:

> Analyze a vendor quote in Email Process Control first. This page will then
> reuse the reviewed PO values and attachments.

The user therefore had no prepared values, no attachment buttons, no form
button, and no actionable instruction. A screenshot captured the failure at
10:37 on an iPhone. This is authoritative real-device evidence that the
server-side `st.switch_page` plus immutable snapshot strategy did not reliably
preserve the production session across mobile multipage navigation.

The exact mechanism may be Safari reconnect behavior, Streamlit multipage
websocket handling, or an infrastructure/session affinity interaction. The
product-level conclusion does not depend on selecting among those internal
causes: crossing the Streamlit page boundary is not a dependable way to carry
quote bytes and generated files on the target production device.

### Corrected architecture

The primary Smartsheet flow no longer navigates to
`pages/2_Smartsheet_PO.py`. It renders inside the same `app/web_ui.py` page and
active session that owns the analyzed quote and generated attachments.

`app/web_ui.py` now:

1. Builds the immutable `POContext` while all reviewed source widgets still
   exist.
2. Displays two explicit, adjacent choices under **Submit the PO request**:
   - **Prepare Smartsheet submission** (recommended route)
   - **Use email backup** (established fallback)
3. Stores only the chosen presentation route in `st.session_state`, scoped by
   `POContext.context_id` so a new quote cannot reopen the prior quote's panel.
4. Calls `render_inline_smartsheet_handoff(po_context)` for Smartsheet without
   calling `st.switch_page` or constructing a new URL.
5. Renders the existing Outlook/Apple Mail component only after the user
   chooses **Use email backup**.
6. Shows the existing “I sent it” contract-learning confirmation only with the
   email route, because that confirmation describes a client-side email send.
7. Bootstraps the anonymous requester cookie at initial root-page load, before
   a quote is analyzed. If an inline fallback must create the cookie later, it
   does so without reloading the parent page.

The email content and attachments are unchanged. Smartsheet remains the
recommended path, while email remains visibly available rather than being
removed during the pilot.

### Inline handoff module

`app/smartsheet_inline.py` is the mobile-safe manual-route presentation layer.
It deliberately reuses, rather than weakens, the existing validated domain
functions:

- `load_config` and `manual_enabled` for the verified production form URL;
- `missing_required_fields` and `validate_submission_fields` for exact form
  values;
- `preflight_attachments` and `download_names` for safe files;
- `handoff_rows` for exact labels and final field order;
- `render_manual_handoff` for copy buttons, progress, and the external form
  link;
- the existing device cookie and requester-memory functions for the three-PO
  learning threshold.

The inline experience is intentionally manual and tells the user this plainly.
Its visible sequence is:

1. Confirm Requester, Job number, exact Smartsheet site/location, Object
   account, and optional additional information.
2. Download the verified quote and generated document files.
3. Read the explicit explanation that the external form does **not** receive
   values automatically yet.
4. Open the Smartsheet form in a new tab.
5. Return to Email Process Control and use the copy buttons in exact form order.
6. Upload the downloaded files and submit in Smartsheet.

The view surfaces locked constants before form entry:

- Request Type = `PO`
- Agreement Type = the reviewed MSAPO/EPO mapping
- Dispatch service center = `NA`

The form assistant remains blocked if the source context, required fields, or
attachments fail their existing preflight checks. URL-prefill and API modes are
not exposed by the inline pilot and remain disabled in configuration.

`app/device_identity.py` now accepts a `reload_parent` option. Its default
remains `True` for the safe initial app bootstrap. The inline handoff passes
`False`; otherwise first-time requester setup could force a full Safari reload,
create a fresh Streamlit session, and discard the very PO state this correction
is designed to preserve. If the fallback creates a cookie without reloading,
the current handoff continues normally and a later browser request can observe
the cookie. Cookie failure still degrades only requester convenience, never PO
preparation.

### Legacy page behavior

`pages/2_Smartsheet_PO.py` remains in the repository for compatibility and for
future API/prefill work. It is no longer the primary production entrypoint. If
someone reaches it without a valid context, its empty state now explains that
mobile navigation can create a new session and directs the user back to the
inline **Prepare Smartsheet submission** action. Do not restore cross-page
navigation as the primary manual route without a proven durable server-side job
or artifact store and real-device acceptance.

### Regression boundary added for this incident

`tests/test_smartsheet_handoff_entrypoint.py` now requires:

1. Delivery controls to render before either conditional route.
2. Exactly two adjacent full-width action buttons with the production labels.
3. Route state to contain distinct `smartsheet` and `email` values.
4. No `st.switch_page` call in `app/web_ui.py`.
5. The inline handoff to retain the manual copy component, attachment download
   controls, and requester-memory recording.
6. The locked `PO` and `NA` statements to remain visible.
7. The legacy empty state to explain the mobile session boundary and inline
   recovery path.
8. The cookie script to support a non-reloading mode for an active mobile
   workflow.

Focused syntax compilation and all four focused entrypoint checks passed before
publication. Full GitHub Actions and the Render production acceptance pass must
still be recorded against the resulting commit.

### Required production acceptance for this correction

Do not accept this change based only on desktop emulation. After GitHub Actions
and Render deployment succeed:

1. Start from the root Email Process Control URL on an actual iPhone/iPad.
2. Analyze a redacted or approved quote and generate the correct document
   package.
3. Confirm **Prepare Smartsheet submission** and **Use email backup** appear
   beside each other.
4. Tap **Prepare Smartsheet submission** and confirm the URL/page does not
   change.
5. Confirm the same screen immediately shows the success explanation,
   Requester, RRH job default, site/location, object account, attachment
   downloads, and instructions.
6. Enter Requester and confirm the prepared copy rows and purple **Open
   Smartsheet form** control appear.
7. Download every offered attachment and confirm the external form accepts
   them.
8. Switch back to the root page, choose **Use email backup**, and confirm the
   existing Apple Mail/Outlook route still works with the same attachments.
9. Start a different quote and verify the prior delivery panel state and values
   do not carry into its new `context_id`.

The overriding rule from this incident is: **transient Streamlit session data
that includes files must not cross a mobile page boundary unless the data has
first been persisted to a durable, authenticated server-side record.**
