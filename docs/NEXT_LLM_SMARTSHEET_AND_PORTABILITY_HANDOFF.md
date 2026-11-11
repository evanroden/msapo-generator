# Email Process Control — Next-LLM Handoff for the Smartsheet and Infrastructure Transition

**Repository:** `evanroden/msapo-generator`  
**Document purpose:** give the next implementation LLM a single, authoritative explanation of why the current transition work exists, what has already been changed, what business behavior must remain unchanged, what is still unknown, and how to continue safely without recreating rejected designs or weakening the reliability controls.  
**Primary transition branches:**

- PR **#25**, branch `agent/smartsheet-three-mode`, head `9765276`: three-mode Smartsheet preparation and reliability hardening.
- PR **#26**, branch `agent/portable-runtime-adapters`, stacked on PR #25: provider-neutral AI, PDF, conversion, storage, and hosting abstractions.

**Status when this document was written:** both PRs are open drafts and unmerged. PR #25 is based on `main`; PR #26 is intentionally stacked on PR #25. The latest full stacked GitHub Actions run for PR #26 passed. Neither branch is production behavior until merged and deployed.

---

## 0. Why this document exists

This is not a generic architecture note. It is a continuity and safety document for the next LLM or developer who takes over the project.

The project is approaching two changes at the same time:

1. **A business-process change:** ENFRA expects the current email-based purchase-order process to move to a Smartsheet form or sheet workflow.
2. **A technology-governance change:** ENFRA may require the application to move away from the current host, Anthropic API, PyMuPDF, LibreOffice, SQLite, or other present-day dependencies.

At the time the work began, the final ENFRA PO form did not yet exist, the final Smartsheet sheet schema was unknown, API permission was uncertain, and it was not known whether the eventual path would be:

- manual copy/paste into a Smartsheet form;
- query-string URL prefilling;
- direct API row creation and attachment upload;
- or some combination of those routes.

It was also unknown whether ENFRA would provide:

- a different AI model or internal AI gateway;
- an OpenAI-compatible enterprise endpoint;
- another proprietary AI API;
- a different PDF parser or OCR service;
- a different DOCX-to-PDF tool;
- a managed database;
- a different application host;
- an SSO layer;
- or a requirement to remove unapproved third-party dependencies.

The danger was not only that the future integration would be unfinished. The larger danger was that a rushed future change would silently alter business rules, submit wrong data, attach stale documents, create duplicate POs, leak one contract’s information into another, or make the application inseparable from whichever vendor happened to be used first.

The work described here therefore had two objectives:

- **Prepare multiple safe Smartsheet routes without activating any unverified route.**
- **Separate business behavior from infrastructure so future providers can be replaced through controlled adapters instead of rewriting the application.**

The next LLM should treat this document as an operating map, not as proof that every external dependency has been approved or live-tested. The code deliberately distinguishes between:

- implemented internal safeguards;
- disabled integration scaffolding;
- configuration that still requires exact real-world values;
- and external acceptance work that cannot be completed without ENFRA, Render, Smartsheet, real devices, or replacement-provider credentials.

---

## 1. The product and the business process it protects

Email Process Control is a Streamlit application that turns a vendor quote into a reviewed PO package.

The current user workflow is:

1. Select a standard MSAPO workflow or an Equipment-only PO workflow.
2. Upload a vendor quote as PDF/image/text or paste quote text.
3. Extract the quote text.
4. Use an AI model to return structured quote information.
5. Review vendor, project, location, scope, inclusions, exclusions, tax treatment, contact, pricing, work category, contract, site, cost code, and asset.
6. Generate an MSAPO DOCX and usually a PDF for standard POs.
7. Build a ready-to-send administrator email with the quote and generated documents attached.
8. Let the user send the email through Outlook or Apple Mail.
9. Record explicitly confirmed sends so recurring contact information can be suggested later within the same contract.

The future workflow may replace or supplement Step 7–9 with a Smartsheet handoff. The upstream work—quote reading, review, routing, MSAPO creation, pricing, asset handling, and attachment preparation—still matters and must remain the source of truth.

### 1.1 Standard MSAPO versus Equipment-only PO

A standard MSAPO submission includes the quote and generated MSAPO files. It is not RRH-only. Evan explicitly rejected a prior proposal to skip MSAPO generation for non-RRH contracts. Do not reintroduce that behavior.

An Equipment-only PO is for equipment delivered by a third party when the vendor will not visit the site. It skips the MSAPO document and sends/submits the quote and PO details only. Asset behavior and bullet ordering differ from the standard flow.

### 1.2 The governing correctness principle

A missing or blocked field is safer than a plausible wrong field.

Examples:

- No asset is safer than a guessed asset.
- An explicit “select contract” state is safer than silently defaulting to RRH.
- A blocked stale document is safer than attaching a document generated for a previous site.
- An uncertain API result is safer than blindly retrying and creating a duplicate PO.
- A disabled integration is safer than fuzzy-matching a Smartsheet column.

Every future change should preserve this fail-closed philosophy.

---

## 2. Non-negotiable business and product rules

The next LLM must preserve all of the following unless Evan explicitly changes the rule.

### 2.1 MSAPO generation applies across contracts

Do not gate standard MSAPO document generation to RRH. PR #10 proposed that and was closed unmerged after Evan clarified that other contracts also use the MSAPO document.

### 2.2 RRH must not regress

RRH is the oldest, most exercised workflow. It has dedicated site names, derived cost codes, site-specific valid work categories, a fixed administrator, and a curated asset registry. Generic-contract improvements must not weaken or overwrite RRH logic.

### 2.3 Contract isolation is absolute

Administrator suggestions, vendor representatives, contacts, and any future learned values must be scoped to the selected contract. Information learned under one contract must never appear under another.

### 2.4 Asset selection must be conservative

A quote must identify a specific tagged unit before the application confidently proposes an asset. The proposed tag must resolve to a real asset at the selected contract/site. The default is no applicable asset. Do not default to the first item in a dropdown.

### 2.5 The original quote must be preserved

The uploaded quote bytes are kept unchanged for attachment. Images may be normalized or PDFs may be decrypted in memory for analysis, but that analysis copy does not replace the original attachment.

### 2.6 AI output remains editable and subordinate to user review

AI extraction is an assistive step. The user can correct routing and business fields, approve or remove AI-suggested inclusions/exclusions, and decide whether the package is ready.

### 2.7 The generated document and submission fields must agree

Contract, site, facility, inclusions, exclusions, and other document-affecting values cannot be changed after generation without invalidating the generated files. The handoff page intentionally locks source-controlled values and sends the user back to Email Process Control for corrections and regeneration.

### 2.8 Optional integrations remain inert until configured

A route must not appear live simply because code exists. Manual Smartsheet mode requires a verified form URL. URL prefill requires exact tested labels and an explicit enable flag. API mode progresses from disabled to dry-run to live and requires exact column specifications, credentials, durable idempotency state, and controlled acceptance tests.

### 2.9 The application should degrade gracefully, but never at the cost of silent corruption

Examples:

- PDF conversion can fail while preserving DOCX.
- Contact learning can become unavailable without blocking the email workflow.
- Smartsheet API submission must fail closed if duplicate-prevention storage is unavailable.
- A replacement AI or PDF adapter must fail clearly when its contract is not met.

### 2.10 iPad usability is a first-class requirement

Evan uses the application from an iPad. Any future host, form, authentication layer, clipboard flow, attachment flow, or UI refactor needs real-device Safari acceptance testing.

---

## 3. Branch and pull-request topology

Understanding the stack is essential before merging or rebasing.

### 3.1 PR #25 — Smartsheet transition and reliability hardening

- Branch: `agent/smartsheet-three-mode`
- Base: `main`
- Head when this document was created: `9765276`
- Status: open draft, mergeable, unmerged
- Purpose: prepare the application for manual, URL-prefill, or API Smartsheet intake without activating unverified behavior.

PR #25 also contains broader correctness work required to make a Smartsheet handoff trustworthy: source-context reconstruction, document fingerprint validation, idempotency, concurrency controls, attachment verification, configuration validation, failure-mode documentation, and automated tests.

### 3.2 PR #26 — portability and replaceable providers

- Branch: `agent/portable-runtime-adapters`
- Base: `agent/smartsheet-three-mode`
- Status: open draft, mergeable, unmerged
- Purpose: make the PR #25 application portable to another host and replaceable AI/PDF/storage tools without changing the business workflow.

PR #26 is stacked. It must not be merged directly into `main` while its base is still the PR #25 branch unless the branch relationship is intentionally changed. Safe options are:

1. Merge PR #25 first, then retarget/rebase PR #26 to `main` and rerun the full suite.
2. Squash or otherwise reconstruct the combined change deliberately, preserving all tests and documentation.

Do not assume GitHub’s “mergeable” flag means the stack is in the desired release order.

### 3.3 Why both remain drafts

They are drafts because the final external system is unknown. Internal code can be correct while activation is still unsafe.

The following are not yet proven:

- final PO form URL;
- final sheet ID;
- final column IDs, titles, types, options, and required fields;
- query-string prefill behavior on the final form;
- service-account credentials and permissions;
- attachment behavior on the final form/sheet;
- real Smartsheet API row-plus-attachments round trip;
- recovery behavior against a real test sheet;
- real Safari behavior;
- production authentication/SSO;
- final replacement AI/PDF/hosting requirements.

---

## 4. What PR #25 changed for the upcoming Smartsheet process

PR #25 was not a simple “submit to Smartsheet” feature. It was designed as a controlled transition framework.

## 4.1 A separate Smartsheet handoff page

The branch adds `pages/2_Smartsheet_PO.py`.

The page shares the current Streamlit session with Email Process Control, but it does not independently reanalyze the quote or recreate routing logic. Instead, it requests a verified PO context from `app/po_context.py`.

Core fields originating in the email workflow are displayed as read-only on the handoff page:

- PO type;
- contract;
- site;
- work category;
- cost code;
- asset ID;
- vendor;
- vendor contact;
- administrator email;
- description;
- reviewed scope;
- subtotal;
- tax;
- total;
- tax status.

Fields that depend on the eventual form but cannot safely be inferred remain human-entered, such as:

- requester name;
- O&M agreement relationship;
- billing method;
- customer PO;
- estimated start and completion dates;
- customer representative;
- service-branch technician requirement;
- send-copy preference;
- additional instructions.

This separation prevents the handoff page from creating a second, divergent version of the PO.

## 4.2 Verified PO context reconstruction

`app/po_context.py` reconstructs the active PO from session state and verifies that the state belongs together.

It checks, among other things:

- that there is an analysis object;
- that the analysis token matches the current analyzed text;
- that the active quote is the quote that produced the analysis;
- that the selected contract and site are present;
- that pricing and other required values are present;
- that a standard PO has current generated files;
- that a pasted quote does not inherit an older uploaded attachment;
- that an uploaded file’s hash and extracted text match the analyzed quote;
- that document paths point to files whose stored document signature matches the current routing and review selections.

It returns:

- normalized submission fields;
- verified attachments;
- a safe attachment basename;
- warnings/blockers;
- a deterministic context ID.

The deterministic context ID namespaces Smartsheet widgets and result state. When a new quote or materially different PO is active, old handoff values and results are not reused.

## 4.3 Approved-scope reconstruction

The Smartsheet scope is not copied blindly from the model response.

The context builder rebuilds the scope using the reviewed base scope plus the final user-approved inclusion and exclusion lists. AI-estimated items removed in Email Process Control do not reappear in Smartsheet simply because they were present in the original analysis object.

## 4.4 Document fingerprint enforcement

A deterministic document signature links generated files to:

- the analysis token;
- selected contract;
- selected site;
- final inclusions;
- final exclusions.

If any of those change, the existing DOCX/PDF is treated as stale. The handoff blocks submission and requires regeneration.

This addresses a major prior failure mode: a file could retain old content while being renamed using new routing values.

## 4.5 Attachment integrity

The handoff preserves original quote bytes and accepts generated files only after context validation.

Manual-download names are sanitized and grouped with a shared ordered basename so they appear together in a file picker. The displayed name may change for usability, but the original quote bytes are unchanged.

API attachment names are deterministic and include a content fingerprint. This matters for safe recovery when Smartsheet receives a file but the client loses the response.

Preflight blocks:

- empty files;
- duplicated sanitized filenames;
- oversized files;
- unsafe names;
- missing verified attachments.

## 4.6 Three independent Smartsheet routes

The routes share a verified source record but are configured independently.

### Route A — manual copy/paste

Manual mode requires only the final verified `SMARTSHEET_FORM_URL` and any confirmed form order/required-field configuration.

It provides:

- a button to open the form;
- one-tap copy controls for populated values;
- automatic advancement/highlighting;
- progress tracking;
- copy-all support;
- mobile clipboard fallback;
- safely grouped attachment downloads.

The progress key includes a hash of exact field labels and values. A new PO or a revised form cannot inherit old completion checkmarks.

Browser storage holds completion indexes only, not sensitive PO values.

Manual mode is blocked when source integrity, attachment preflight, or configured form-required fields fail.

### Route B — exact-label URL prefill

URL prefill is deliberately not fuzzy.

It uses:

- `SMARTSHEET_FORM_FIELD_MAP_JSON` for exact visible field labels;
- `SMARTSHEET_FORM_VALUE_MAP_JSON` for exact option translations;
- `SMARTSHEET_FORM_REQUIRED_FIELDS` for confirmed form requirements;
- `SMARTSHEET_PREFILL_MAX_URL_LENGTH` for a practical URL ceiling;
- `SMARTSHEET_URL_PREFILL_ENABLED=true` only after the final form is tested.

Behavior includes:

- preserving unrelated existing query parameters;
- replacing an already-present mapped parameter instead of duplicating it;
- including mapped populated fields in configured order;
- omitting unmapped/empty/oversized fields with explicit reasons;
- blocking the form link when required values are missing;
- warning that files are never carried in the URL.

Do not revive the earlier assumption that a guessed query string will work. The example Work Order Request Form did not prove the final PO form supports prefill.

### Route C — direct API submission

API mode is controlled by `SMARTSHEET_API_MODE`:

- `disabled` — no live API action;
- `dry_run` — validate credentials/schema without row creation;
- `live` — permit controlled writes only after all readiness checks pass.

The API path requires:

- API token;
- sheet ID;
- exact column specifications;
- confirmed required fields;
- a dedicated submission-key column;
- durable duplicate-prevention storage.

The code does not select columns using title similarity. Each logical field maps to an exact numeric column ID plus expected title and type. Picklists can also specify expected options.

Before a write, live validation checks:

- column ID exists;
- title is unchanged;
- type is unchanged;
- configured options still match;
- target is writable;
- target is not locked;
- target is not a formula/system column;
- required logical fields are mapped and populated.

Values are sent in strict typed form:

- amounts as numbers;
- dates as ISO dates;
- checkboxes as booleans;
- contacts as validated email values;
- picklist values only when exact options match;
- text only within Smartsheet’s supported cell length.

The integration does not use `strict:false` coercion.

---

## 5. Idempotency, concurrency, and API recovery introduced in PR #25

This is one of the most important parts of the transition. Do not simplify it into a boolean “submitted” flag.

## 5.1 Deterministic submission fingerprint

The submission key is derived from normalized populated fields and attachment content hashes. It changes when the substantive payload changes.

The full key is written into a dedicated Smartsheet text column. This makes remote reconciliation possible even if local SQLite state is lost.

## 5.2 Persistent submission state

`app/smartsheet_store.py` records:

- submission key;
- status;
- remote row ID;
- attachment fingerprints;
- last error;
- update time;
- lease token;
- lease expiration;
- attempt count.

The important statuses include:

- pending;
- complete;
- partial;
- failed;
- uncertain.

## 5.3 Expiring ownership lease

A submission attempt obtains an atomic lease. Only the lease owner may record the row, attachment progress, or final state.

This blocks:

- double clicks;
- Streamlit reruns;
- two browser sessions;
- concurrent workers;
- a second process beginning attachment work after the first process has already created the row.

The lease expires so a crashed worker does not block the PO forever. After expiration, a known row can be resumed. A definitely failed pre-row request can be retried.

## 5.4 Ambiguous row creation

A write request can reach Smartsheet even when the client times out before receiving the response.

Blind retry would risk a duplicate row. Therefore:

- definite non-retryable rejection becomes `failed`;
- an ambiguous timeout/network/server outcome becomes `uncertain`;
- an uncertain submission without a known row ID is blocked from normal retry;
- the UI instructs the user not to press Submit again;
- reconciliation searches for the exact full submission key;
- candidate rows are verified by reading the actual submission-key cell;
- exactly one match can be adopted;
- zero matches do not immediately authorize a replacement because Smartsheet search indexing may lag;
- multiple matches require administrator intervention.

## 5.5 Local-state loss recovery

Reconciliation can upsert the remotely verified row into a new local database. This is essential when moving hosts or restoring storage.

The next LLM must not replace this with an in-memory map. Multi-instance or ephemeral hosts require a real durable transactional store adapter.

## 5.6 Attachment upload recovery

Each API attachment has a deterministic remote name containing a content fingerprint.

Before/resuming uploads, the integration lists remote attachment names. After an ambiguous upload failure, it lists them again.

If the deterministic name exists, the attachment is recorded as complete rather than uploaded again. If it does not exist, the row remains partial and can be resumed safely.

## 5.7 Corrupt or unavailable state fails closed

Invalid attachment-history JSON is treated as corruption, not as an empty set. Storage failure does not silently disable duplicate prevention when API mode is live.

Old completed/failed records can be cleaned by retention policy. Partial and uncertain records are retained for recovery.

---

## 6. Failure-mode work added with PR #25

`docs/FAILURE_MODES_AND_CONTROLS.md` is the detailed reliability register. It covers more than 40 failure modes across:

- quote and analysis integrity;
- generated document integrity;
- attachment integrity;
- Streamlit state isolation;
- manual handoff;
- URL prefill;
- API mapping and typed values;
- idempotency and concurrency;
- ambiguous network outcomes;
- storage and host behavior;
- security and access;
- real-device acceptance;
- operational recovery.

It also contains:

- route-specific activation gates;
- incident runbooks;
- automated acceptance expectations;
- manual acceptance expectations;
- residual business decisions.

A future LLM should update that document when it changes controls. Do not claim a control is implemented unless code and tests enforce it.

---

## 7. What PR #26 changed for host/provider portability

PR #26 does not replace the current user experience. It changes where infrastructure-specific behavior lives.

The public application calls remain conceptually stable:

- `analyze_quote(quote_text)`;
- `extract_text(file_bytes, filename)`;
- `convert_to_pdf(docx_path)`.

Behind those functions, provider selection and capability validation now occur through explicit adapters.

The goal is that ENFRA can replace one infrastructure concern at a time without rewriting contracts, asset logic, scope review, tax handling, document generation, email formatting, or Smartsheet safety behavior.

---

## 8. Runtime and hosting abstraction

## 8.1 `app/runtime.py`

Runtime paths and network settings are separated from Render assumptions.

The runtime model distinguishes:

- `EPC_TEMPLATE_PATH` — read-only MSAPO template path;
- `EPC_DATA_DIR` — persistent state;
- `EPC_WORK_DIR` — ephemeral scratch directory;
- `EPC_OUTPUT_DIR` — generated transient DOCX/PDF directory;
- `EPC_HOST` — bind address;
- `EPC_PORT` or platform `PORT` — HTTP port.

This prevents a read-only application image from failing merely because code previously attempted to create `output/` inside the repository at import time.

The default writable area uses the operating system’s temporary/work directory. Production persistence still requires an explicit durable `EPC_DATA_DIR`.

## 8.2 `app/entrypoint.py`

The host-neutral entrypoint launches Streamlit using configured host and port.

Use:

```bash
python -m app.entrypoint
```

This works better than embedding `8501` in every hosting definition. Platforms such as Heroku-like PaaS products commonly supply `PORT` dynamically.

## 8.3 Docker changes

The Dockerfile now supports build arguments so a replacement deployment can omit unneeded default adapters or LibreOffice.

The current/default image can still install:

- Streamlit and core dependencies;
- Anthropic adapter;
- PyMuPDF reader;
- image normalization support;
- LibreOffice.

An ENFRA-internal build can install core plus an approved adapter package and omit default provider dependencies.

The container command uses the generic entrypoint and no longer hardcodes one hosting platform’s process assumptions.

## 8.4 Other host examples

The branch includes:

- `Procfile` for command-based PaaS deployment;
- generic Docker Compose configuration;
- updated Render blueprint example;
- host-neutral environment examples.

These are examples, not proof that a target platform’s networking, storage, health check, secrets, or SSO configuration is complete.

---

## 9. AI-provider abstraction

## 9.1 `app/ai_provider.py`

The provider-neutral contract accepts an `AIRequest` containing:

- operation name;
- system instructions;
- prompt text;
- optional binary parts;
- media types;
- requested token ceiling.

A provider advertises capabilities such as:

- text;
- image;
- native PDF/document input.

The OCR pipeline checks capabilities instead of assuming every provider supports Anthropic-style document blocks.

## 9.2 Built-in Anthropic adapter

The existing behavior remains available through a lazily loaded Anthropic provider.

Configuration supports the new neutral variables while retaining legacy compatibility:

```text
EPC_AI_PROVIDER=anthropic
EPC_AI_API_KEY=...
EPC_AI_MODEL=...
```

Legacy variables remain accepted:

```text
ANTHROPIC_API_KEY=...
ANTHROPIC_MODEL=...
```

Anthropic is no longer imported by business modules at top level merely to define analysis behavior.

## 9.3 OpenAI Chat Completions-compatible adapter

A built-in HTTP adapter supports an enterprise endpoint that follows the Chat Completions request/choice shape.

Typical configuration:

```text
EPC_AI_PROVIDER=openai_chat_compatible
EPC_AI_ENDPOINT=https://approved.example/v1/chat/completions
EPC_AI_API_KEY=...
EPC_AI_MODEL=...
```

This is not a claim that every “OpenAI-compatible” product handles images, documents, JSON, token limits, or errors identically. Capability and adapter tests are still required for the actual ENFRA endpoint.

## 9.4 Custom AI adapter

A trusted deployment can configure a factory:

```text
EPC_AI_PROVIDER=custom
EPC_AI_ADAPTER=company_epc.ai:create_provider
```

The factory may accept no arguments or one environment mapping. It returns an object implementing the provider contract.

The import path comes only from trusted deployment environment variables, never from user-supplied quote/form data.

## 9.5 Retry and error classification

Provider-specific authentication, rate-limit, quota, transient-server, and response parsing behavior belongs inside the adapter.

The portability bug hunt corrected a dangerous behavior in which non-transient enterprise-AI `4xx` responses could be retried or mislabeled as connection failures.

The OCR layer also avoids hiding authentication/network/quota failures by launching a second expensive fallback request. A format/capability failure can lead to a legitimate fallback; a provider outage should remain visible.

## 9.6 Input limits

Quote input is bounded using `EPC_AI_MAX_INPUT_CHARS`. Oversized input is rejected clearly rather than silently truncated, because truncation could remove totals, tax clauses, exclusions, or facility information while producing a plausible incomplete analysis.

---

## 10. PDF-reading and OCR abstraction

## 10.1 `app/pdf_reader.py`

The PDF reader contract separates local PDF mechanics from OCR/business behavior.

A reader implements:

- embedded text extraction;
- page rendering;
- diagnostic information.

Its return objects validate:

- page count;
- page order;
- supported media type;
- non-empty bytes;
- dimensions and limits.

## 10.2 Built-in PyMuPDF reader

The current PyMuPDF behavior remains available as the default adapter.

It handles:

- embedded text extraction;
- owner-locked PDFs that are openable without a user password;
- in-memory analysis copies;
- page rasterization.

The original quote bytes remain unchanged for attachment.

## 10.3 Custom PDF reader

A replacement library or service can be configured:

```text
EPC_PDF_READER=custom
EPC_PDF_READER_ADAPTER=company_epc.pdf:create_reader
```

The custom reader can use:

- another Python PDF library;
- an internal document service;
- a cloud OCR service;
- an ENFRA-approved extraction API.

Business code must not import that provider directly.

## 10.4 OCR pipeline behavior

The pipeline now follows capability-aware stages:

1. Decode plain text directly.
2. For PDF, ask the configured reader for embedded text.
3. Accept embedded text only when it passes minimum-length and quality checks.
4. If the provider supports native PDF input, attempt native-document OCR.
5. Otherwise—or after a legitimate unsupported-format result—render bounded page images.
6. Send rendered pages in bounded batches to a provider that supports images.
7. Combine ordered text output.

Image uploads are normalized where needed while preserving original bytes.

## 10.5 OCR bounds

Environment controls include:

```text
EPC_PDF_TEXT_MIN_CHARS=20
EPC_OCR_MAX_PAGES=30
EPC_OCR_DPI=150
EPC_OCR_PAGES_PER_BATCH=5
EPC_OCR_MAX_PIXELS_PER_PAGE=40000000
EPC_OCR_MAX_TOTAL_IMAGE_BYTES=52428800
```

Controls prevent:

- unlimited page rendering;
- decompression-bomb-like pixel counts;
- one enormous model request;
- unbounded memory use;
- empty-page false success;
- excessive cost from accidental giant scans.

Password-to-open PDFs fail explicitly. Owner-lock normalization remains an analysis-only action.

---

## 11. PDF-conversion abstraction

`app/pdf_converter.py` now selects a converter object rather than depending on global backend functions and one shared output directory.

Available selections include:

```text
EPC_PDF_CONVERTER=libreoffice
EPC_PDF_CONVERTER=gotenberg
EPC_PDF_CONVERTER=docx2pdf
EPC_PDF_CONVERTER=none
EPC_PDF_CONVERTER=custom
```

Legacy `PDF_BACKEND` compatibility remains where appropriate.

## 11.1 LibreOffice hardening

Each conversion uses:

- a unique LibreOffice user profile;
- a unique conversion directory;
- an explicit expected source/output relationship;
- timeout handling;
- PDF signature validation.

This avoids concurrent conversions fighting over one LibreOffice profile and prevents a stale PDF from a prior request being mistaken for a new successful result.

## 11.2 Gotenberg hardening

The remote converter checks:

- URL safety;
- HTTPS requirement for non-local production services unless explicitly allowed for controlled tests;
- HTTP status;
- response size;
- PDF signature;
- non-HTML/non-error response.

An HTTP 200 response is not accepted automatically as a PDF.

## 11.3 docx2pdf

This remains an option for Windows/macOS hosts with Microsoft Word and the appropriate optional package. It is not expected to work in a Linux container without Word.

## 11.4 Controlled DOCX-only mode

`EPC_PDF_CONVERTER=none` lets a host operate without PDF generation while preserving the existing graceful DOCX behavior.

Do not interpret this as permission to omit a required PDF if ENFRA’s final process requires one. That is a business/acceptance decision.

## 11.5 Custom converter

```text
EPC_PDF_CONVERTER=custom
EPC_PDF_CONVERTER_ADAPTER=company_epc.convert:create_converter
```

Every custom converter must return a real file with a PDF signature. The wrapper validates output rather than trusting the adapter’s filename.

---

## 12. Persistence abstraction

Two persistence concerns exist and have different failure policies.

## 12.1 Contact-learning memory

The current SQLite contact-learning behavior is now behind a memory backend contract.

Selections:

```text
EPC_MEMORY_BACKEND=sqlite
EPC_MEMORY_BACKEND=disabled
EPC_MEMORY_BACKEND=custom
EPC_MEMORY_ADAPTER=company_epc.memory:create_backend
```

A custom backend implements:

- `record_send`;
- `suggest_admin_emails`;
- `suggest_contacts`;
- `vendor_reps`;
- `diagnostic`.

Contract isolation remains a business invariant regardless of backend.

Contact learning may degrade gracefully. If the backend is unavailable, the main quote/email workflow can continue without suggestions.

## 12.2 Smartsheet submission store

The submission store has a stricter policy because it prevents duplicate financial records.

Selections:

```text
EPC_SUBMISSION_STORE_BACKEND=sqlite
EPC_SUBMISSION_STORE_BACKEND=custom
EPC_SUBMISSION_STORE_ADAPTER=company_epc.submissions:create_store
```

A custom store must implement the existing lease/idempotency/reconciliation behavior. A managed database adapter should use transactional compare-and-set, row locks, or equivalent semantics.

Live Smartsheet mode cannot disable the store and cannot silently use an implicit temporary SQLite directory.

## 12.3 `/test1` removal as a hidden default

The previous memory module looked for `/test1`, a Render-specific mount path. Portability work moves the decision into explicit runtime configuration.

Render may still set `EPC_DATA_DIR=/test1`, but application modules should not infer Render merely from that directory existing.

---

## 13. Deployment diagnostics

`app/doctor.py` provides a predeployment diagnostic.

Run:

```bash
python -m app.doctor
python -m app.doctor --json
```

It checks:

- runtime paths;
- template existence/readability;
- writable work/output paths;
- AI provider configuration/capabilities;
- PDF reader configuration;
- PDF converter availability;
- memory backend;
- submission-store configuration;
- host and port;
- persistence expectations relevant to live Smartsheet mode.

The next LLM should use the diagnostic in the exact target environment, not only in GitHub Actions.

A diagnostic pass does not replace a real quote, document, email, Smartsheet, browser, or restart test.

---

## 14. Dependency packaging

Dependencies are split so a replacement host does not need to install unapproved defaults.

### `requirements-core.txt`

Contains provider-neutral application dependencies required for the web/document workflow.

### `requirements-default-adapters.txt`

Contains current adapter dependencies such as Anthropic, PyMuPDF, and HEIC support.

### `requirements.txt`

Installs both sets for backward-compatible current behavior.

An ENFRA replacement deployment can instead use:

```bash
pip install -r requirements-core.txt
pip install company-epc-adapters
```

The replacement package must provide tested adapter factories and any vendor SDKs it requires.

Do not remove the default adapters from the current deployment until the replacement environment has passed contract and end-to-end tests.

---

## 15. Files introduced or materially changed by the transition work

This list is a navigation guide, not a substitute for reading the current branch.

### Smartsheet/reliability layer

- `app/po_context.py` — reconstructs and validates the reviewed PO snapshot.
- `app/smartsheet.py` — configuration, manual rows, exact prefill, schema validation, API submission, typed cells, attachment upload, reconciliation.
- `app/smartsheet_store.py` — persistent leased idempotency state.
- `app/smartsheet_ui.py` — manual mobile copy assistant.
- `pages/2_Smartsheet_PO.py` — handoff page.
- `docs/FAILURE_MODES_AND_CONTROLS.md` — reliability register and runbooks.
- `tests/test_po_context.py` — source-context and stale-document tests.
- `tests/test_smartsheet_config.py` — configuration/prefill/preflight tests.
- `tests/test_smartsheet_api.py` — typed cells, schema drift, ambiguous writes, attachment reconciliation.
- `tests/test_smartsheet_store.py` — lease, resume, corruption, reconciliation, retention tests.

### Portability layer

- `app/adapter_loader.py` — trusted factory loading and contract validation.
- `app/ai_provider.py` — AI request/provider contracts and built-in providers.
- `app/pdf_reader.py` — reader/rendering contracts and PyMuPDF implementation.
- `app/pdf_converter.py` — converter contracts and hardened built-ins.
- `app/runtime.py` — host/path settings.
- `app/entrypoint.py` — portable Streamlit launcher.
- `app/doctor.py` — deployment diagnostics.
- `app/memory.py` — backend-neutral contact learning.
- `docs/PORTABILITY.md` — adapter/deployment guide.
- `tests/test_portability.py` — adapter and runtime contract tests.
- `requirements-core.txt` — neutral dependencies.
- `requirements-default-adapters.txt` — current adapters.
- `Procfile`, `Dockerfile`, `docker-compose.yml`, `render.yaml`, `.env.example` — deployment/configuration examples.

### Existing modules intentionally preserved behind stable calls

- `app/web_ui.py` still orchestrates the user workflow.
- `app/quote_analyzer.py` still owns business prompt/post-processing and returns `QuoteAnalysis`, but it calls the configured AI provider.
- `app/ocr.py` still owns the extraction strategy and image normalization, but it calls configured reader/provider adapters.
- `app/document_generator.py` still generates the MSAPO.
- `app/eml_builder.py` still builds email content.
- `app/contracts.py`, `app/assets.py`, and RRH configuration still own routing/business data.

---

## 16. Tests and current validation state

PR #25’s branch passed its 50-test suite after the hardening work.

PR #26 added a focused portability contract suite and then passed the full stacked GitHub Actions workflow. The PR remains a draft not because CI is failing, but because external integration and acceptance inputs do not exist yet.

The tests cover, among other things:

- safe default-disabled configuration;
- unknown/misspelled logical fields;
- duplicate column IDs;
- unsafe URLs/hosts;
- exact prefill parameter replacement;
- option translation;
- required form values;
- URL-length limit;
- stale quote/upload detection;
- pasted-text attachment isolation;
- stale document signature;
- standard versus EPO attachment behavior;
- strict amount/date/checkbox/contact conversion;
- live schema drift;
- submission fingerprint stability;
- concurrent lease exclusion;
- lease-expiration recovery;
- partial attachment resume;
- ambiguous creation block;
- local-state-loss reconciliation;
- corrupt attachment history fail-closed;
- attachment-response loss reconciliation;
- custom adapter loading;
- provider capability enforcement;
- PDF reader result validation;
- converter output validation;
- runtime path/port behavior;
- live Smartsheet persistence requirements.

### 16.1 Tests still required with real systems

Automated unit/contract tests cannot prove:

- the final Smartsheet form accepts the configured query labels;
- the final sheet’s actual column types/options match the mapping;
- a real API token has the expected permissions;
- attachment upload/list behavior matches mocks;
- Smartsheet search indexing behaves within the recovery runbook’s timing assumptions;
- the replacement AI returns sufficiently reliable structured quote data;
- the replacement PDF reader handles the actual vendor PDFs;
- generated DOCX/PDF appearance remains acceptable across replacement tools;
- real iPad Safari clipboard/share behavior;
- real Outlook and Apple Mail behavior;
- persistence across an actual host restart;
- SSO/access protection.

---

## 17. Configuration reference for the next LLM

Do not copy placeholder values into production. Confirm every value with the actual target system.

## 17.1 Runtime

```text
EPC_TEMPLATE_PATH=/path/to/Master_MSAPO_Template.docx
EPC_DATA_DIR=/durable/path
EPC_WORK_DIR=/ephemeral/work
EPC_OUTPUT_DIR=/ephemeral/output
EPC_HOST=0.0.0.0
EPC_PORT=8501
PORT=<platform-provided-port>
EPC_REQUESTER_NAME=...
```

## 17.2 AI

```text
EPC_AI_PROVIDER=anthropic|openai_chat_compatible|custom
EPC_AI_API_KEY=...
EPC_AI_MODEL=...
EPC_AI_ENDPOINT=...
EPC_AI_ADAPTER=package.module:factory
EPC_AI_MAX_INPUT_CHARS=...
```

Legacy Anthropic variables remain supported for migration.

## 17.3 PDF reading/OCR

```text
EPC_PDF_READER=pymupdf|custom
EPC_PDF_READER_ADAPTER=package.module:factory
EPC_PDF_TEXT_MIN_CHARS=20
EPC_OCR_MAX_PAGES=30
EPC_OCR_DPI=150
EPC_OCR_PAGES_PER_BATCH=5
EPC_OCR_MAX_PIXELS_PER_PAGE=40000000
EPC_OCR_MAX_TOTAL_IMAGE_BYTES=52428800
```

## 17.4 PDF conversion

```text
EPC_PDF_CONVERTER=libreoffice|gotenberg|docx2pdf|none|custom
EPC_PDF_CONVERTER_ADAPTER=package.module:factory
GOTENBERG_URL=...
```

Review `.env.example` for the current exact names and compatibility variables before configuring.

## 17.5 Memory and idempotency

```text
EPC_MEMORY_BACKEND=sqlite|disabled|custom
EPC_MEMORY_ADAPTER=package.module:factory
EPC_SUBMISSION_STORE_BACKEND=sqlite|custom
EPC_SUBMISSION_STORE_ADAPTER=package.module:factory
```

## 17.6 Smartsheet manual/form

```text
SMARTSHEET_FORM_URL=https://app.smartsheet.com/b/form/FINAL_FORM_ID
SMARTSHEET_FORM_ORDER=...
SMARTSHEET_FORM_REQUIRED_FIELDS=...
SMARTSHEET_URL_PREFILL_ENABLED=false
SMARTSHEET_PREFILL_MAX_URL_LENGTH=7000
SMARTSHEET_FORM_FIELD_MAP_JSON={...}
SMARTSHEET_FORM_VALUE_MAP_JSON={...}
```

## 17.7 Smartsheet API

```text
SMARTSHEET_API_MODE=disabled|dry_run|live
SMARTSHEET_API_TOKEN=...
SMARTSHEET_SHEET_ID=...
SMARTSHEET_COLUMN_SPECS_JSON={...}
SMARTSHEET_REQUIRED_FIELDS=...
SMARTSHEET_ROW_POSITION=top|bottom
SMARTSHEET_ALLOW_CUSTOM_API_BASE=false
SMARTSHEET_API_BASE_URL=https://api.smartsheet.com/2.0
```

Live tokens are restricted to the official Smartsheet API host. Custom API bases are for controlled non-live tests only when explicitly allowed.

---

## 18. Safe activation sequence for the final Smartsheet change

Do not activate all routes simultaneously merely because they exist.

### Phase 1 — obtain authoritative artifacts

Collect from ENFRA/Smartsheet:

- final PO form URL;
- final destination sheet ID;
- form owner and sheet owner;
- exact field labels and order;
- exact required fields;
- exact dropdown/radio values;
- attachment requirements and limits;
- whether authentication is required;
- whether email remains part of the process;
- whether a service account/token is allowed;
- whether a dedicated submission-key column can be added;
- who approves schema changes;
- go-live and rollback dates.

### Phase 2 — configure manual mode first

Manual mode is the lowest-permission route and the most robust fallback.

1. Configure the verified form URL.
2. Configure exact form order and required fields.
3. Test a complete standard PO and EPO.
4. Test all required attachments.
5. Test real iPad/iPhone Safari and Windows.
6. Confirm the user can identify which values remain human-entered.
7. Keep email available until ENFRA confirms replacement behavior.

### Phase 3 — test URL prefill independently

1. Use a non-production/test form if available.
2. Verify that query-string prefill is supported.
3. Capture exact visible labels after punctuation/capitalization is final.
4. Configure exact value translations.
5. Test empty, special-character, long-scope, and dropdown fields.
6. Verify files still require manual attachment.
7. Enable the flag only after acceptance.

A failed prefill experiment must fall back to manual mode, not to guessed parameters.

### Phase 4 — prepare API dry-run

1. Obtain an approved least-privilege service-account token.
2. Confirm the exact sheet ID.
3. Add a dedicated submission-key text column.
4. Capture numeric IDs, exact titles, exact types, and option lists.
5. Configure confirmed required fields.
6. Verify durable storage.
7. Run `python -m app.doctor`.
8. Set API mode to `dry_run`.
9. Validate live schema repeatedly before any write.

### Phase 5 — controlled live API test

Use a test sheet or approved test row.

Test:

- standard PO row;
- EPO row;
- all attachment types;
- strict dates, amounts, contacts, checkboxes, and picklists;
- duplicate click;
- browser rerun;
- restart persistence;
- partial attachment failure;
- ambiguous row-creation simulation;
- exact-key reconciliation;
- schema drift block;
- revoked token;
- permission denial;
- oversized cell/file block.

Only then set production API mode to live.

### Phase 6 — decide process sequencing

ENFRA must decide whether Smartsheet:

- replaces email;
- supplements email;
- must occur before email;
- must occur after email;
- or generates another approval event.

Do not encode that sequence based on assumptions from the Work Order Request Form example.

---

## 19. Safe migration sequence for a replacement AI/PDF/host

Change one infrastructure concern at a time.

### 19.1 Replacement AI

1. Keep current Anthropic configuration available for rollback.
2. Implement or configure the new provider adapter.
3. Verify capability declarations.
4. Run adapter contract tests.
5. Run redacted text quotes through both providers.
6. Compare required fields, tax, totals, scope, assumptions, facility, and asset references.
7. Test malformed output, auth failure, quota, rate limits, timeout, and server failure.
8. Test scanned PDF/image OCR if the provider is used for OCR.
9. Confirm data-governance and logging requirements.
10. Switch only after acceptance.

Do not modify the business schema to accommodate one provider’s casual output. The provider must meet the application contract.

### 19.2 Replacement PDF reader/OCR tool

1. Implement the reader contract.
2. Use redacted fixtures representing:
   - normal text PDF;
   - scanned PDF;
   - owner-locked PDF;
   - multi-page quote;
   - image upload;
   - poor scan;
   - unsupported password-to-open PDF.
3. Validate page order and extracted completeness.
4. Enforce page/pixel/byte limits.
5. Confirm original bytes remain the attachment.
6. Compare analysis results downstream.
7. Switch the reader only after contract and workflow tests pass.

### 19.3 Replacement PDF converter

1. Implement the converter contract.
2. Validate PDF signature and output path.
3. Visually compare the MSAPO on representative templates.
4. Test concurrency.
5. Test timeout and malformed output.
6. Preserve DOCX-only fallback if allowed.
7. Switch only after document acceptance.

### 19.4 Replacement host

1. Configure template, data, work, and output paths explicitly.
2. Configure host/port using the platform’s contract.
3. Provide persistent storage or managed stores.
4. Run the deployment doctor in the built image/runtime.
5. Test health checks and startup.
6. Test restart persistence.
7. Test concurrent sessions.
8. Configure secrets outside the repository.
9. Configure access control/SSO.
10. Verify outbound access to approved AI/Smartsheet services.
11. Test real browsers and mail clients.
12. Maintain a rollback deployment until acceptance is complete.

---

## 20. Security and governance items the code cannot decide

The application processes potentially sensitive operational information:

- vendor pricing;
- contacts;
- facility names and addresses;
- equipment/asset identifiers;
- scopes of work;
- contract routing;
- PO values.

The next LLM must not assume that passing tests means organizational approval.

External decisions still include:

- approved AI provider and data-retention terms;
- whether quote content may leave ENFRA systems;
- approved host and region;
- SSO/authentication;
- authorized user population;
- least-privilege Smartsheet account ownership;
- token rotation and incident response;
- log retention/redaction;
- persistent database backup;
- access to generated files;
- legal applicability of the MSAPO template across contracts.

The current production application has historically lacked a merged application-level login. Broad rollout should not occur until access control is resolved.

---

## 21. Known limitations and open decisions

Do not invent answers to these.

1. Does Smartsheet fully replace email?
2. What is the final PO form URL?
3. What are the final exact labels/options/required fields?
4. What is the final sheet ID and schema?
5. Will ENFRA permit API access and a service account?
6. Can the form accept multiple files, and what are its file limits?
7. Can one PO cover multiple assets?
8. How should amendments/corrections relate to an existing row?
9. Does a changed payload create a new PO or update an existing one?
10. Who owns the asset and cost-code source data?
11. How often do contract/site/asset exports change?
12. Which AI/PDF/host tools will ENFRA approve?
13. What authentication/SSO solution is required?
14. What persistent managed database is available on a multi-instance host?
15. What backup and disaster-recovery requirements apply?
16. Is the current MSAPO template legally valid for every contract, including non-text branding or embedded elements?
17. Are Outlook desktop, New Outlook, Outlook Web, Apple Mail, and real Safari all required supported clients?
18. What monitoring/alerting platform should receive provider, storage, and submission errors?

---

## 22. What not to do

The next LLM should explicitly avoid these shortcuts.

- Do not merge PR #26 before understanding that it is stacked on PR #25.
- Do not activate Smartsheet settings with the example work-order form values.
- Do not use fuzzy title matching for API columns.
- Do not use `strict:false` to make bad values “work.”
- Do not retry ambiguous row creation automatically.
- Do not use an in-memory duplicate map for a financial workflow.
- Do not interpret a missing Smartsheet search result as proof a row does not exist.
- Do not remove deterministic attachment names or remote reconciliation.
- Do not allow two workers to attach to the same row under separate active leases.
- Do not treat corrupted attachment history as empty.
- Do not let a pasted quote inherit an old uploaded file.
- Do not allow a contract/site change without document regeneration.
- Do not make handoff fields independently editable when they affect the attached document.
- Do not default unknown routing to RRH.
- Do not guess an asset.
- Do not expose one contract’s learned data to another.
- Do not reintroduce RRH-only MSAPO gating.
- Do not silently truncate quote input, scope, or Smartsheet values.
- Do not assume every AI provider supports native PDFs or images.
- Do not hide provider auth/quota failures behind fallback OCR calls.
- Do not accept an HTTP 200 response as a PDF without signature validation.
- Do not hardcode Render’s `/test1` or port 8501 inside business modules.
- Do not import custom adapters from user-controlled values.
- Do not put production tokens, mappings, or secrets in Git.
- Do not scale SQLite state across multiple host instances without a shared transactional replacement.
- Do not mark an external blocker complete merely because a mock test passed.

---

## 23. Recommended next-LLM operating procedure

When beginning a new session:

1. Read this document.
2. Read `docs/FAILURE_MODES_AND_CONTROLS.md`.
3. Read `docs/PORTABILITY.md`.
4. Inspect PR #25 and PR #26 status and heads; do not rely on the commit IDs in this document if the branches moved.
5. Check whether `main` changed since the branches were created.
6. Inspect current CI and review comments.
7. Identify whether the requested work belongs on PR #25, PR #26, a new branch, or `main` after merges.
8. Reconfirm the business rule affected before changing code.
9. Use exact real artifacts for Smartsheet/provider work.
10. Add or update contract tests before changing an adapter.
11. Batch changes and run tests before pushing to avoid notification floods.
12. Keep PRs draft while external acceptance blockers remain.
13. Update this document when architectural status materially changes.

For code changes, report clearly:

- branch and base;
- files changed;
- business rule preserved;
- failure mode addressed;
- tests run;
- mock versus live validation;
- remaining external blocker;
- whether production changed.

---

## 24. Acceptance checklist before declaring the upcoming transition ready

### Source package

- [ ] Quote identity verified.
- [ ] Original attachment bytes preserved.
- [ ] Analysis matches active quote.
- [ ] Contract/site explicitly selected.
- [ ] Cost code confirmed.
- [ ] Asset either valid for site or explicitly not applicable.
- [ ] Pricing reviewed and arithmetic consistent.
- [ ] Inclusions/exclusions reviewed.
- [ ] Generated document fingerprint current.
- [ ] Standard/EPO attachment rules correct.

### Manual Smartsheet route

- [ ] Final form URL confirmed.
- [ ] Exact field order confirmed.
- [ ] Required fields confirmed.
- [ ] Attachment behavior confirmed.
- [ ] Windows browser tested.
- [ ] Real iPhone/iPad Safari tested.
- [ ] Copy fallback tested.
- [ ] No PO values stored in browser persistence.

### URL-prefill route

- [ ] Final form supports prefill.
- [ ] Exact labels captured.
- [ ] Exact option translations configured.
- [ ] Existing query parameters preserved.
- [ ] Duplicate mapped parameters replaced.
- [ ] Long fields handled safely.
- [ ] Required fields block correctly.
- [ ] Files still handled manually.

### API route

- [ ] Approved service account/token.
- [ ] Least privilege verified.
- [ ] Final sheet ID.
- [ ] Dedicated submission-key column.
- [ ] Exact IDs/titles/types/options.
- [ ] Required fields confirmed.
- [ ] Durable state verified across restart.
- [ ] Dry-run passes.
- [ ] Controlled row creation passes.
- [ ] All attachments pass.
- [ ] Double-click blocked.
- [ ] Partial attachment resumes same row.
- [ ] Ambiguous row recovery tested.
- [ ] Local-state-loss reconciliation tested.
- [ ] Schema drift blocked.
- [ ] Revoked permissions fail safely.

### Replacement infrastructure

- [ ] Adapter contract implemented.
- [ ] Adapter diagnostic passes.
- [ ] Redacted representative fixtures pass.
- [ ] Error classification tested.
- [ ] Input/output limits tested.
- [ ] Business output compared against current provider.
- [ ] Deployment doctor passes in target runtime.
- [ ] Persistent data survives restart.
- [ ] Access control configured.
- [ ] Rollback configuration retained.

### Release process

- [ ] PR stack resolved correctly.
- [ ] Full CI green after final rebase.
- [ ] External owners sign off.
- [ ] Monitoring/runbook owner named.
- [ ] Backup/restore tested.
- [ ] Production secrets configured outside Git.
- [ ] One controlled production submission observed.
- [ ] Email-vs-Smartsheet sequencing confirmed.

---

## 25. Compact briefing for a future LLM

You are taking over Email Process Control in `evanroden/msapo-generator`.

The application converts vendor quotes into reviewed PO packages and currently produces a ready-to-send administrator email. ENFRA expects the process to move to Smartsheet, but the final form, sheet, schema, API access, and sequencing remain unknown.

PR #25 adds a disabled-by-default three-route Smartsheet handoff: manual copy/paste, exact-label URL prefill, and direct API. It also adds verified PO context reconstruction, stale-upload/document protection, deterministic context and submission fingerprints, exact typed column mapping, leased idempotency, uncertain-write reconciliation, deterministic attachment recovery, failure-mode runbooks, and tests.

PR #26 is stacked on PR #25 and makes infrastructure replaceable: AI provider, PDF reader/OCR, PDF converter, contact memory, Smartsheet submission store, runtime paths, port, and deployment packaging. Current Anthropic/PyMuPDF/LibreOffice/SQLite behavior remains available, but trusted adapters can replace those tools. The user-facing calls remain stable.

Do not merge the stack casually, activate guessed Smartsheet mappings, weaken duplicate protection, reintroduce RRH-only MSAPO gating, guess assets, leak contract-specific memory, or silently truncate/convert data. Read the two detailed docs, inspect current branch heads and CI, and obtain the real ENFRA artifacts before completing activation.

---

## 26. Final status statement

The project is now **prepared for the upcoming change**, not **fully activated for the upcoming change**.

Prepared means:

- multiple Smartsheet routes exist;
- unverified routes default to off;
- source data and attachments are validated;
- API mapping is exact;
- duplicates and ambiguous writes have a recovery model;
- infrastructure dependencies are behind replaceable contracts;
- deployment paths and ports are configurable;
- diagnostics and tests exist;
- failure modes and runbooks are documented.

Not yet activated means:

- the real PO form/sheet is still required;
- mappings and credentials are still required;
- live API and real-device acceptance are still required;
- ENFRA’s approved AI/PDF/host stack is still required;
- authentication, governance, persistence, and process sequencing still require external decisions.

The next LLM’s job is not to fill those unknowns with assumptions. Its job is to preserve the controls, obtain the authoritative inputs, validate one route/provider at a time, and move the system from prepared to accepted without changing the business behavior that users already depend on.
