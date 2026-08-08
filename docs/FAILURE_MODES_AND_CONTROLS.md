# Email Process Control and Smartsheet Failure Modes

> **Historical reliability register.** The authoritative business workflow as
> of 2026-08-08 is
> [`STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md`](STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md).
> The current quick-path and reliability controls, including the second-pass
> bug register, are in
> [`RRH_STREAMLINING_AND_HARDENING_2026-08-08.md`](RRH_STREAMLINING_AND_HARDENING_2026-08-08.md).
> This file preserves valuable failure analysis, but its references to email,
> EPO mode, full MSAPO generation, editable Object Account, and three-file
> packages are superseded.

**Status:** living reliability specification  
**Scope:** current quote-to-email workflow plus live manual Smartsheet PO handoff  
**Last reviewed:** 2026-08-08
**Primary implementation:** draft PR #25

## 1. Purpose

This document defines the ways Email Process Control can produce a wrong, incomplete, duplicated, exposed, or unavailable purchase-order package and the controls required to prevent or recover from each failure.

The governing safety rule is: **block or require review rather than silently manufacture a plausible result.** A missing value is recoverable; a wrong cost code, asset, amount, contract, attachment, or duplicate PO may not be.

The live Smartsheet PO form URL, visible labels, required inputs, RRH job choices, and a historical internal-sheet export have now been supplied. They are authoritative for the manual handoff. Direct-API column IDs/types and non-RRH job/site option catalogs remain unverified.

## 2. Severity and control states

| Level | Meaning |
|---|---|
| Critical | Could expose confidential data, create a duplicate financial record, route work to the wrong contract, or create an unrecoverable remote state. |
| High | Could submit materially wrong or incomplete PO data or attachments. |
| Medium | Could interrupt the workflow, lose convenience state, or require manual recovery without corrupting a PO. |
| Low | Cosmetic, documentation, or minor usability defect. |

Control states:

- **Implemented:** code and regression coverage exist in PR #25 or current `main`.
- **Configured later:** code exists but remains inert until verified environment configuration is supplied.
- **External blocker:** requires ENFRA, Render, Smartsheet, legal, or real-device action.
- **Residual:** risk cannot be eliminated completely; an operator runbook is defined.

## 3. Safety architecture

1. The email workflow remains the source record for contract, site, cost code, asset, vendor, scope, pricing, and attachments.
2. A deterministic context ID isolates Streamlit widgets and results for each reviewed PO.
3. The generated Scope/Inclusions/Exclusions PDF is accepted only when its stored document fingerprint matches the current analysis, contract, site, inclusions, and exclusions.
4. The manual route uses the verified live form; URL-prefill and API routes remain independent and disabled until separately verified.
5. URL prefill uses exact configured labels and values; it never guesses.
6. API submission uses exact verified column IDs, titles, types, options, and strict typed values.
7. Every API submission includes a deterministic submission key in a dedicated sheet column.
8. SQLite uses an expiring ownership lease so only one worker can mutate a submission at a time.
9. Ambiguous row creation is marked `uncertain` and blocked from retry until exact-key reconciliation.
10. Attachments have deterministic names and fingerprints so remote state can be checked before retry.
11. Secrets are accepted only from environment configuration; live tokens may be sent only to `api.smartsheet.com`.

## 4. Failure-mode register

### A. Quote, analysis, and source-record integrity

#### FM-A01 — New unreadable upload leaves a prior analysis visible
- **Severity:** Critical
- **Trigger:** extraction fails after another quote was already analyzed in the same browser session.
- **Impact:** the user could submit the prior quote's details while believing the new file is active.
- **Detection:** uploaded-file hash, extraction hash, extracted text, stored quote text, and analysis token are compared.
- **Control:** the active page now removes the prior analysis, document, and
  generated context immediately. Failed extraction has a separate error hash
  and explicit retry action; only a successful extraction enters the cache.
- **State:** Implemented and regression-tested in the 2026-08-08 hardening pass.

#### FM-A02 — Pasted quote attaches an older uploaded file
- **Severity:** Critical
- **Trigger:** a user uploads one quote, then switches to pasted text without clearing upload-related session state.
- **Impact:** the correct fields could be paired with the wrong vendor document.
- **Detection:** an uploaded file is active only when its hash and extracted text match the analyzed quote text.
- **Control:** Upload and Paste are now mutually exclusive active sources. The
  selected source is stored in the verified context; Paste always creates
  `Vendor Quote.txt`, including when its text happens to equal an older upload.
- **State:** Implemented and tested.

#### FM-A03 — Analysis object and quote text do not match
- **Severity:** Critical
- **Trigger:** stale Streamlit state, partial reset, or manual session manipulation.
- **Impact:** incorrect vendor, facility, pricing, or scope.
- **Detection:** recompute the 12-character analysis token from the stored quote text.
- **Control:** block the handoff and require re-analysis.
- **State:** Implemented and tested.

#### FM-A04 — Claude returns malformed or schema-drifted JSON
- **Severity:** High
- **Trigger:** malformed JSON, wrong types, unsupported enums, trailing explanation, or a future model response change.
- **Impact:** constructor error or incorrectly typed business fields.
- **Detection:** dedicated response parser and validator.
- **Control:** reject the analysis with a clear error; do not populate the UI.
- **State:** Implemented on `main` in PR #24.

#### FM-A05 — AI invents an asset
- **Severity:** Critical
- **Trigger:** ambiguous equipment language or hallucinated tag.
- **Impact:** PO charged to the wrong asset.
- **Detection:** proposed tag must resolve to a real asset at the selected contract and site.
- **Control:** default to no applicable asset; never fall back to the first dropdown item.
- **State:** Implemented on `main`.

#### FM-A06 — Unknown facility silently becomes RRH
- **Severity:** Critical
- **Trigger:** facility matcher finds no known contract/site.
- **Impact:** wrong administrator, cost code family, filename, or legal routing.
- **Control:** explicit contract and site placeholders block downstream preparation.
- **State:** Implemented on `main`.

#### FM-A07 — Pricing components do not add to total
- **Severity:** High
- **Trigger:** extraction error or manual edit.
- **Impact:** wrong PO amount.
- **Detection:** parse subtotal, tax, and total as decimals when all are present.
- **Control:** warning in source workflow and blocking warning in handoff when difference exceeds $0.01.
- **State:** Implemented.

#### FM-A08 — A value exceeds Smartsheet's cell limit
- **Severity:** High
- **Trigger:** long scope or instructions over 4,000 characters.
- **Impact:** Smartsheet can truncate a cell, producing an incomplete scope without an obvious failure.
- **Control:** preflight blocks API use and omits the field from a prefill URL with an explicit reason. Description of Work is capped at 20 characters; the full scope remains in the attached Scope/Inclusions/Exclusions PDF.
- **State:** Implemented.

#### FM-A09 — Zero, negative, or repaired amount reaches classification
- **Severity:** Critical
- **Trigger:** zero/negative input, exponent-like text, or extra decimals.
- **Impact:** invalid PO value or wrong Standard PO tier.
- **Control:** one strict currency parser is used by classification, context
  reconciliation, and Smartsheet validation. Every route requires a value
  greater than zero; generation stays disabled until it passes.
- **State:** Implemented and tested.

#### FM-A10 — Negated work controls route inference
- **Severity:** Critical
- **Trigger:** phrases such as `installation excluded`, `labor by others`, or
  `rental not included` appear in the quote.
- **Impact:** wrong Object Account and Agreement Type.
- **Control:** deterministic fallback evaluates terms within their clause and
  ignores locally negated/excluded work. The model prompt carries the same rule.
- **State:** Implemented and tested.

#### FM-A11 — Asset UID matches inside a longer serial number
- **Severity:** Critical
- **Trigger:** one configured UID is a substring of unrelated quote text.
- **Impact:** wrong full asset code is exported.
- **Control:** normalized identifier-boundary matching plus the existing
  unique-best registry requirement.
- **State:** Implemented and tested.

#### FM-A12 — Oversized quote cannot become a valid package
- **Severity:** High
- **Trigger:** uploaded quote exceeds Smartsheet's 30 MB attachment limit or
  extracted/pasted input exceeds 500,000 characters.
- **Impact:** wasted OCR/model work followed by a late attachment failure.
- **Control:** reject at the uploader/input boundary before extraction or model
  analysis.
- **State:** Implemented and tested.

### B. Document and attachment integrity

#### FM-B01 — A PDF-bearing value changes after generation
- **Severity:** Critical
- **Trigger:** user edits contract, site, vendor, Scope, Inclusions, or Exclusions
  after building the document.
- **Impact:** form values and the attached Scope/Inclusions/Exclusions PDF disagree.
- **Detection:** deterministic document signature covers the analyzed quote,
  contract, site, vendor, full scope text, Inclusions, and Exclusions.
- **Control:** remove stale paths from use and require regeneration.
- **State:** Implemented on `main` and reverified by the Smartsheet context builder.

#### FM-B02 — Generated path exists but belongs to another session
- **Severity:** Critical
- **Trigger:** filename collision or shared output directory.
- **Impact:** another user's document could be attached.
- **Control:** unique internal filenames, 24-hour cleanup, and document-signature validation.
- **State:** Implemented on `main`.

#### FM-B03 — Quote attachment is empty, oversized, or duplicated
- **Severity:** High
- **Trigger:** failed upload, zero-byte file, duplicate filenames, or file over 30 MB.
- **Impact:** missing backup or API rejection.
- **Control:** attachment preflight checks bytes, duplicate sanitized names, and size before a write.
- **State:** Implemented.

#### FM-B04 — Unsafe vendor filename reaches browser or API headers
- **Severity:** High
- **Trigger:** path traversal text, newlines, control characters, or reserved punctuation in upload name.
- **Impact:** confusing downloads or header injection.
- **Control:** strip paths/control characters, allow a conservative filename character set, and cap length. Original bytes remain unchanged.
- **State:** Implemented and tested.

#### FM-B05 — API upload succeeds but response is lost
- **Severity:** Critical
- **Trigger:** timeout or network interruption after Smartsheet stored an attachment.
- **Impact:** blind retry creates duplicate attachments.
- **Detection:** deterministic API filename includes a content fingerprint; list remote row attachments after an error.
- **Control:** mark the attachment complete when the exact deterministic remote name exists; otherwise leave the row partial.
- **State:** Implemented; live API verification remains external.

#### FM-B06 — Local attachment history is damaged
- **Severity:** Critical
- **Trigger:** corrupt SQLite JSON or disk fault.
- **Impact:** previously attached files could be uploaded again.
- **Control:** corruption fails closed instead of being treated as an empty list.
- **State:** Implemented and tested.

#### FM-B07 — PDF conversion fails
- **Severity:** Medium
- **Trigger:** LibreOffice failure or timeout.
- **Impact:** PDF is absent.
- **Control:** preserve DOCX, warn clearly, and allow DOCX-only package where business rules permit.
- **State:** Implemented on `main`.

### C. Streamlit and manual handoff

#### FM-C01 — A new quote inherits another quote's Smartsheet widget values
- **Severity:** Critical
- **Trigger:** fixed widget keys across multipage Streamlit reruns.
- **Impact:** an old requester, job number, object account, or additional-information value can be submitted.
- **Control:** namespace all fields and results with a context ID derived from source fields and attachment hashes; clear prior handoff keys on context change.
- **State:** Implemented.

#### FM-C02 — Manual completion checkmarks carry to another PO or form revision
- **Severity:** Medium
- **Trigger:** browser local storage key based only on a filename.
- **Impact:** user skips fields they did not copy for the current request.
- **Control:** progress key includes a hash of the exact labels and values. Browser storage contains only completed indexes, never PO values.
- **State:** Implemented.

#### FM-C03 — Clipboard API is unavailable on iOS
- **Severity:** Medium
- **Trigger:** browser permission, insecure context, or older Safari behavior.
- **Control:** immediate Clipboard API attempt, then a hidden editable textarea and `execCommand` fallback; display manual-selection guidance if both fail.
- **State:** Implemented; real-device Safari test is an external blocker.

#### FM-C04 — User edits a document-bearing value without regenerating the document
- **Severity:** Critical
- **Trigger:** a second editable copy of contract, source site, cost code, asset, scope, amount, or attachment-bearing data exists on the handoff page.
- **Impact:** submitted values and the attached Scope/Inclusions/Exclusions PDF disagree.
- **Control:** all operator corrections occur above one final generation action. A context-ID mismatch hides the old downloads/link, and a document-signature mismatch requires the PDF to be rebuilt.
- **State:** Implemented.

#### FM-C05 — Manual route opens despite an invalid source package
- **Severity:** High
- **Trigger:** stale source warnings are displayed but the form link remains active.
- **Control:** manual and prefill actions are blocked when source-integrity or configured required-field checks fail.
- **State:** Implemented in final hardening pass.

#### FM-C06 — Form field order or labels change
- **Severity:** Medium
- **Trigger:** Smartsheet administrator edits the live form.
- **Impact:** manual order becomes inconvenient; URL prefill can stop working.
- **Control:** the current exact labels/order are represented in code and configuration. URL prefill remains off until retested after every form revision.
- **State:** Implemented for the current form; ongoing change control required.

#### FM-C07 — A shared browser prefills the wrong requester
- **Severity:** Medium
- **Trigger:** several people use one browser profile, or Streamlit reruns are mistaken for repeated use.
- **Impact:** a PO can be attributed to the wrong requester.
- **Detection:** requester events are tied to a verified PO context ID and exact account, not Streamlit reruns.
- **Control:** remember the latest successfully used requester after the first ready package for the exact anonymous device+account pair. Never cross accounts or browsers. A later verified user naturally takes over on a shared device; no Forget action appears in the active UI. The browser cookie contains only a random token, which is hashed before server storage. Blocked/cleared cookies disable convenience without blocking the workflow.
- **State:** Implemented and regression-tested; real Safari cookie behavior remains an acceptance check.

#### FM-C08 — Stale selectbox value is no longer in the deployed catalog
- **Severity:** High
- **Trigger:** an app deployment changes contract, site, category, job, route,
  request-type, or asset options while a browser session remains active.
- **Impact:** widget exception or export of a retired value.
- **Control:** sanitize every keyed selection against its current catalog before
  rendering; reset to the detected/default value or a blocking placeholder.
- **State:** Implemented in the 2026-08-08 hardening pass.

#### FM-C09 — Automatic choices create too much routine review
- **Severity:** Medium
- **Trigger:** every AI/defaulted field remains visible for every PO.
- **Impact:** operators re-read or alter correct defaults, increasing time and
  error likelihood.
- **Control:** keep only requester plus one compact exported-value summary in the
  normal RRH path. Full controls remain in an exception-only review section that
  opens when a critical guess is missing or invalid.
- **State:** Implemented and covered by the UI contract tests.

#### FM-C10 — Embedded handoff API or runtime security settings drift
- **Severity:** Medium
- **Trigger:** Streamlit removes its deprecated components HTML helper, or CORS
  is configured off while XSRF protection requires it on.
- **Impact:** the Smartsheet link/copy fallback or browser identity bootstrap can
  stop rendering after an upgrade; contradictory startup settings can hide the
  intended request-origin policy.
- **Control:** pin Streamlit below 2.0, use the supported `st.iframe` API, and
  explicitly keep CORS and XSRF protection enabled together.
- **State:** Implemented and regression-tested in the 2026-08-08 follow-up.

### D. URL-prefill route

#### FM-D01 — Wrong guessed query parameter fills the wrong field
- **Severity:** Critical
- **Control:** no fuzzy matching; only exact administrator-configured visible labels are encoded.
- **State:** Implemented.

#### FM-D02 — Existing query and generated value create duplicate parameters
- **Severity:** High
- **Impact:** form behavior may be ambiguous.
- **Control:** remove an existing mapped parameter before adding the current value; preserve unrelated query parameters.
- **State:** Implemented and tested.

#### FM-D03 — URL exceeds browser, proxy, or Smartsheet practical limits
- **Severity:** High
- **Control:** configurable maximum length; fields are skipped in configured order with reasons. Default is 7,000 characters.
- **State:** Implemented.

#### FM-D04 — Dropdown/radio internal value differs from form option
- **Severity:** High
- **Control:** exact per-field value map; no automatic translation.
- **State:** Implemented, configured later.

#### FM-D05 — User assumes files were included in the URL
- **Severity:** High
- **Control:** attachment downloads remain prominent and the UI explicitly states that URL prefilling cannot carry files.
- **State:** Implemented.

#### FM-D06 — Required form fields are missing
- **Severity:** High
- **Control:** independently configured `SMARTSHEET_FORM_REQUIRED_FIELDS`; block
  until each value is populated **and actually included in the final encoded
  URL**. A missing label mapping or URL-length skip withholds the link. Change
  Orders apply the same gate to Original PO Number.
- **State:** Implemented, configured, and regression-tested for the current form.

### E. API schema and value safety

#### FM-E01 — Correct column ID now points to a renamed or repurposed column
- **Severity:** Critical
- **Trigger:** sheet schema drift.
- **Control:** validate exact ID, title, and type against the live sheet before writes.
- **State:** Implemented.

#### FM-E02 — Two logical fields map to one column
- **Severity:** Critical
- **Control:** configuration load rejects duplicate numeric column IDs.
- **State:** Implemented and tested.

#### FM-E03 — Configuration contains a misspelled logical field
- **Severity:** High
- **Control:** reject any key outside the known field registry.
- **State:** Implemented and tested.

#### FM-E04 — Dropdown option no longer exists
- **Severity:** High
- **Control:** optional expected-option list in column specification plus exact picklist validation.
- **State:** Implemented.

#### FM-E05 — Locked, formula, or system column is configured
- **Severity:** High
- **Control:** live schema validation rejects non-writable targets.
- **State:** Implemented.

#### FM-E06 — Date, checkbox, contact, or amount is sent as plausible text
- **Severity:** High
- **Trigger:** `strict:false` coercion.
- **Control:** strict cells only; convert dates to ISO, yes/no to booleans, amounts to numbers, and validate contact emails.
- **State:** Implemented.

#### FM-E07 — Required API field is not mapped or empty
- **Severity:** Critical
- **Control:** separately configured required list; readiness rejects unmapped fields and preflight rejects empty values.
- **State:** Implemented.

#### FM-E08 — No durable submission key exists in the sheet
- **Severity:** Critical
- **Impact:** ambiguous writes cannot be reconciled reliably after local-state loss.
- **Control:** live readiness requires a dedicated `submission_key` column populated with the deterministic full hash.
- **State:** Implemented.

#### FM-E09 — Live token is sent to a malicious custom endpoint
- **Severity:** Critical
- **Control:** form must be HTTPS on a Smartsheet domain; live API base must be `api.smartsheet.com`. Custom API base is permitted only for non-live controlled tests with explicit opt-in.
- **State:** Implemented and tested.

### F. Idempotency, concurrency, and ambiguous network results

#### FM-F01 — User double-clicks Submit or Streamlit reruns
- **Severity:** Critical
- **Control:** atomic SQLite claim with an expiring ownership lease; later request receives `in_progress`.
- **State:** Implemented and tested.

#### FM-F02 — Second process resumes attachments while first process is active
- **Severity:** Critical
- **Trigger:** original draft treated any row ID as resumable.
- **Control:** active lease blocks all other workers even after row creation.
- **State:** Implemented and tested.

#### FM-F03 — Worker crashes and leaves the submission locked forever
- **Severity:** Medium
- **Control:** lease expires; a later worker can resume the known row or retry a definitely failed pre-row request.
- **State:** Implemented.

#### FM-F04 — Row creation succeeds remotely but local response times out
- **Severity:** Critical
- **Impact:** automatic retry can create a second row.
- **Control:** mark `uncertain`, release lease, and block Submit. Search the sheet for the exact full submission key and verify the row cell before adopting it.
- **Residual:** Smartsheet search indexing may lag; “not found” does not authorize a new row. Wait and retry reconciliation.
- **State:** Implemented; controlled live test required.

#### FM-F05 — Row is created but local state cannot record its ID
- **Severity:** Critical
- **Control:** return the known row ID and block blind retry. Exact-key reconciliation can upsert/adopt it after storage recovery.
- **State:** Implemented in final hardening pass.

#### FM-F06 — Local idempotency database is deleted
- **Severity:** Critical
- **Control:** dedicated key column permits verified remote reconciliation; reconciliation upserts local state. API submission otherwise fails closed when storage is unavailable.
- **State:** Implemented; backups remain recommended.

#### FM-F07 — Same logical PO is changed slightly and submitted again
- **Severity:** High
- **Trigger:** field or attachment changes produce a new deterministic key.
- **Control:** UI locks source fields and requires review. This is intentionally a new submission because the payload differs.
- **Residual:** business policy must determine whether amendments should update a prior row instead.
- **State:** Business decision required.

#### FM-F08 — Submission database grows indefinitely
- **Severity:** Low/Medium
- **Control:** cleanup removes old complete/failed records after retention; partial/uncertain records are retained for recovery.
- **State:** Implemented.

### G. Availability, security, and operations

#### FM-G01 — Render URL is publicly accessible
- **Severity:** Critical
- **Impact:** quotes, prices, contacts, facilities, and asset data may be exposed.
- **Control:** interim fail-closed password gate exists in PR #18 but must not merge until `EPC_ACCESS_PASSWORD` is configured. ENFRA SSO is preferred before broad rollout.
- **State:** External blocker.

#### FM-G02 — API token has excessive permissions or belongs to a person
- **Severity:** Critical
- **Control:** use a dedicated service account shared only to the destination sheet with least privilege; rotate through approved secret management.
- **State:** External blocker.

#### FM-G03 — Render dashboard overrides blueprint configuration
- **Severity:** High
- **Control:** deployment checklist compares both locations; startup configuration validation fails visibly.
- **State:** Operational control.

#### FM-G04 — Persistent disk is absent, read-only, corrupt, or full
- **Severity:** Critical for API, Medium for contact learning
- **Control:** API duplicate prevention fails closed; do not downgrade to in-memory idempotency. Alert and restore disk/backups.
- **State:** Implemented; monitoring/backup external.

#### FM-G05 — Render scales to multiple instances
- **Severity:** Critical
- **Impact:** local SQLite and disk are not shared reliably.
- **Control:** remain single-instance or migrate idempotency and learning to a shared transactional database before scaling.
- **State:** External architecture constraint.

#### FM-G06 — Smartsheet service, rate limit, or network outage
- **Severity:** Medium/High
- **Control:** safe GET operations use bounded retry and `Retry-After`; write operations are not blindly retried. Manual route remains independent when the form is available.
- **State:** Implemented.

#### FM-G07 — Logs expose token or full sensitive payload
- **Severity:** Critical
- **Control:** never log authorization headers or submitted fields; user-facing errors are truncated and sanitized. Environment secrets are never committed.
- **State:** Implemented by design; centralized logging review external.

#### FM-G08 — Current template is legally inapplicable to a contract
- **Severity:** Critical
- **Control:** text audit found no RRH wording, but legal applicability and non-text branding require business/legal confirmation.
- **State:** External blocker before broad rollout.

#### FM-G09 — Real Safari or Outlook behavior differs from emulation
- **Severity:** Medium/High
- **Control:** maintain manual fallback; run acceptance tests on real iPhone, iPad, Outlook Web, New Outlook, and Classic Outlook.
- **State:** External blocker.

#### FM-G10 — The live PO form changes after implementation
- **Severity:** High
- **Control:** keep manual labels/order under regression coverage, retain editable exact job/site inputs where catalogs are incomplete, and leave URL prefill/API disabled until each changed schema is reverified.
- **State:** Current manual schema implemented; ongoing Smartsheet change control required.

## 5. Activation gates

### Manual route

- Final PO form URL confirmed and configured.
- URL is HTTPS on a Smartsheet domain.
- Final field order and required fields confirmed from the live form/screenshots and represented in code.
- One desktop and one real iPad/iPhone test completed.
- Verified attachment field accepts the required number, types, and sizes of files.

### URL-prefill route

All manual gates, plus:

- Query-prefill behavior tested on the final form.
- Exact visible labels captured after final punctuation/capitalization.
- Exact option translations configured.
- Long-value behavior tested; attachment instructions remain visible.
- `SMARTSHEET_URL_PREFILL_ENABLED=true` only after acceptance.

### API route

- Smartsheet plan permits API access.
- Dedicated least-privilege service account and token obtained.
- Destination sheet ID confirmed.
- Dedicated text column created for full submission key.
- Exact column specification JSON records ID, title, type, and expected options.
- Required field list confirmed by process owner.
- Persistent disk verified and backed up.
- Dry-run live schema validation passes.
- Controlled test row with all attachments succeeds.
- Ambiguous-create and partial-attachment recovery runbooks exercised in a test sheet.
- `SMARTSHEET_API_MODE=live` enabled only after approval.

## 6. Incident runbooks

### IR-1 — “Outcome uncertain” after row creation

1. Do not press Submit again and do not manually create a replacement row.
2. Copy the displayed submission key.
3. Wait for Smartsheet search indexing, then run exact-key reconciliation.
4. If exactly one row is found and its key cell matches, adopt that row and resume attachments.
5. If no row is found, wait and retry; absence from search is not proof of absence.
6. If multiple rows are found, stop and ask the sheet administrator to resolve duplicates before continuing.

### IR-2 — Row exists, attachments partial

1. Leave the row in place.
2. Re-submit the exact unchanged context.
3. The lease resumes the same row, lists remote deterministic attachment names, and uploads only missing files.
4. Review any persistent failure for size, permission, MIME, or rate-limit cause.

### IR-3 — Live schema drift

1. Do not change code to guess new columns.
2. Compare the configured ID/title/type/options with the live sheet.
3. Confirm the change with the sheet owner.
4. Update exact specifications in the approved environment secret.
5. Run dry-run validation before returning to live mode.

### IR-4 — Form prefill stops working

1. Switch to manual copy/paste; do not infer new query keys.
2. Capture exact final labels and option text.
3. Test a non-production form link.
4. Update field/value maps and re-enable only after verification.

### IR-5 — Idempotency database unavailable or lost

1. Disable API live mode.
2. Restore the persistent disk/database if possible.
3. For a known uncertain submission, search by the full submission key and reconcile.
4. Do not use an in-memory fallback.
5. Before re-enabling, verify single-instance deployment and database write access.

### IR-6 — Wrong data discovered after submission

1. Do not silently overwrite or create a second row.
2. Record the existing row ID and submission key.
3. Follow ENFRA's amendment/cancellation policy once defined.
4. Correct the source workflow, regenerate the document, and treat the changed payload as a distinct submission unless the process owner authorizes row updates.

## 7. Regression and acceptance matrix

Automated coverage must include:

- default configuration inert;
- unsafe hosts, unknown fields, duplicate labels/IDs rejected;
- exact prefill replacement, order, required fields, option translation, and URL limit;
- strict amount/date/checkbox/contact/picklist conversion;
- exact live column title/type/options/writability validation;
- source quote hash/token and stale-upload detection;
- stale document fingerprint exclusion;
- EPO attachment and asset behavior;
- lease concurrency before and after row creation;
- lease expiry recovery;
- corrupt history fail-closed;
- definite failure retry versus ambiguous failure block;
- row reconciliation after local-state loss;
- remote attachment reconciliation after lost response;
- 4,000-character, 30 MB, empty, duplicate, and unsafe filename preflight;
- deterministic context and submission fingerprints;
- device+account requester isolation, first-package recall, rerun deduplication, correction, and latest-user takeover.

Manual acceptance must include:

- final form on Windows and real iPhone/iPad Safari;
- final API sheet in dry-run and one controlled live submission;
- Outlook Web/New/Classic and Apple Mail attachment review;
- form/file size and multi-file behavior;
- Render restart with idempotency persistence;
- credential rotation and revoked-permission failure;
- controlled ambiguous-write recovery in a test sheet.

## 8. Residual decisions and blockers

The following cannot be solved safely through code assumptions:

1. Whether Smartsheet replaces email or supplements it.
2. Final destination sheet and exact API column IDs, titles, types, options, and submission-key column.
3. Exact non-RRH job-number and site/location option catalogs.
4. Whether one PO may contain multiple assets.
5. Whether a changed PO updates an existing row or creates an amendment.
6. Authentication/SSO and approved user population.
7. Service-account ownership and token-rotation policy.
8. Template legal applicability across every contract.
9. Persistent-disk backup, monitoring, and disaster recovery.
10. Multi-instance/shared-database strategy.

Until these are resolved, PR #25 should remain draft. The manual route can be tested against the verified form; URL prefill and API submission must remain disabled until their own activation gates pass.
