# Email Process Control — Comprehensive Project Handoff Dossier

**Repository:** `evanroden/msapo-generator` (private)  
**Default branch:** `main`  
**Current production-code head:** `5a03b86` — `Validate Claude quote-analysis responses`  
**Open transition work:** PR **#25** (`agent/smartsheet-three-mode`) and stacked PR **#26** (`agent/portable-runtime-adapters`)  
**Separate security draft:** PR **#18** (`agent/add-access-gate`)  
**Dossier date:** 2026-07-29  
**Prepared by:** GPT-5.6 Thinking, after repository inspection, implementation, testing, and the work described below

---

## 0. READ THIS FIRST — purpose, authority, and limits

### 0.1 Why this dossier exists

This is the current successor to the handoff dossier that initiated the most recent reliability and architecture work. It is intended to let the next LLM or developer understand, in one place:

- what the product is;
- why it exists;
- how the current production workflow works;
- what has already been merged into `main`;
- what is prepared but still unmerged in PR #25 and PR #26;
- which historical approaches were explicitly rejected;
- which defects were found and fixed during the latest takeover;
- what was learned about the codebase, deployment model, Smartsheet transition, and infrastructure portability;
- which assumptions remain unverified because ENFRA, Render, Smartsheet, real devices, or replacement-provider credentials are required;
- how to continue without weakening the fail-closed controls or accidentally changing business behavior.

This document is deliberately broader than `docs/NEXT_LLM_SMARTSHEET_AND_PORTABILITY_HANDOFF.md`. That document is focused on the upcoming process and infrastructure transition. This dossier reconstructs the entire project history and current operating state, similar to the original external handoff, but updated with all work completed during this conversation.

### 0.2 Confidence labels

The following labels are used where useful:

- **[Confirmed]** — verified in current code, current GitHub metadata, a merged PR, a passing test, or an explicit user instruction.
- **[Strongly inferred]** — supported by code structure and repeated behavior, but not directly confirmed by the process owner.
- **[Tentative]** — plausible, but requires verification before acting.
- **[Unknown — external confirmation required]** — cannot be answered safely from the repository or this conversation.

### 0.3 Source-of-truth hierarchy

When sources conflict, use this order:

1. The current checked-out branch or current GitHub branch being changed.
2. Explicit instructions from Evan.
3. Merged code and tests on `main`.
4. Open PR code and tests, with the PR stack understood correctly.
5. This dossier.
6. Older README text, old PR descriptions, old comments, and historical summaries.

This document describes a fast-moving repository. Always re-read current GitHub state before changing code. Do not assume the SHA values or PR bases in this document remain current forever.

### 0.4 What this dossier cannot prove

The repository does not provide access to:

- the Render dashboard;
- the actual public/private reachability of the deployed URL;
- whether Render auto-deploy is enabled;
- the mounted disk’s real contents, free space, or backup state;
- the final ENFRA PO Smartsheet form;
- the final destination sheet and live column IDs/types/options;
- an approved Smartsheet service-account token;
- ENFRA SSO or identity-provider configuration;
- ENFRA legal approval of the MSAPO template across every contract;
- real iPhone/iPad Safari behavior;
- Outlook desktop, New Outlook, Classic Outlook, or Apple Mail end-to-end behavior;
- the exact AI, PDF, OCR, conversion, hosting, or database platform ENFRA may eventually require.

Where these items matter, the code is designed to remain disabled or fail closed rather than guess.

---

## 1. Executive handoff

### 1.1 What the product is

Email Process Control is a Streamlit web application that turns a vendor quote into a reviewed purchase-order package.

The current production workflow does all of the following:

1. Accepts a vendor quote as a PDF, image, text file, or pasted text.
2. Extracts readable text locally when possible.
3. Uses an AI model for quote analysis and for OCR/vision fallback when required.
4. Produces structured vendor, project, facility, scope, tax, contact, pricing, work-category, and asset-reference information.
5. Lets the user review and correct AI-derived information.
6. Applies contract/site routing, RRH cost-code rules, and conservative asset validation.
7. Generates an MSAPO DOCX and normally a PDF for standard POs.
8. Builds a ready-to-send administrator email with the original quote and generated files attached.
9. Supports Outlook `.eml` on desktop and an Apple share/copy workflow on iPhone/iPad.
10. Learns recurring contacts and administrators only after the user explicitly confirms a completed send, and only within the same contract.

Despite the repository name, this is not merely an “MSAPO generator.” The user-facing product is the quote-to-administrator workflow.

### 1.2 Who it is for

The project began as Evan’s personal ENFRA workflow tool and expanded to support RRH plus 36 additional ENFRA contracts. The application may eventually serve a much larger internal population. **[Confirmed]**

That wider rollout creates requirements that were not critical in the earliest personal-tool version:

- authentication or SSO;
- deterministic correctness;
- contract isolation;
- concurrency safety;
- persistent idempotency;
- testable provider interfaces;
- documented incident recovery;
- deployment portability;
- legal and governance review;
- auditability and change control.

### 1.3 Where the repository stands now

#### `main` — merged production code

`main` currently includes:

- the original quote-to-email application;
- multi-contract support;
- conservative asset selection;
- corrected non-RRH filenames and routing;
- per-contract learning;
- OCR and owner-locked PDF handling;
- Outlook Web base64 body encoding;
- neutral non-RRH greetings;
- stale-document blocking;
- explicit unknown contract/site handling;
- collision-safe generated files and cleanup;
- a current README;
- a committed pytest suite and GitHub Actions;
- removal of the abandoned FastAPI/SendGrid path;
- HEIC/HEIF/TIFF/BMP image normalization;
- strict validation of AI quote-analysis JSON.

Current `main` head at dossier creation: `5a03b86`.

#### PR #25 — Smartsheet transition and reliability hardening

PR #25 is open, draft, mergeable, and unmerged. It prepares three independent future routes:

1. Manual copy/paste into a Smartsheet form.
2. Exact-label URL prefilling.
3. Direct Smartsheet API row creation and attachment upload.

It also adds a large fail-closed reliability layer, persistent idempotency, exact schema validation, attachment reconciliation, a failure-mode dossier, and incident runbooks.

PR #25 is not production behavior and must remain disabled until the final form/sheet and credentials exist.

#### PR #26 — portability and provider abstraction

PR #26 is open, draft, mergeable, stacked on PR #25, and unmerged. It decouples:

- AI generation/vision;
- PDF text extraction and page rendering;
- DOCX-to-PDF conversion;
- contact-learning storage;
- Smartsheet idempotency storage;
- runtime paths, host, port, and packaging.

It adds built-in Anthropic, OpenAI Chat-compatible, PyMuPDF, LibreOffice, Gotenberg, docx2pdf, SQLite, disabled, and custom adapter options, plus deployment diagnostics and provider contract tests.

PR #26 must not merge before PR #25 unless it is cleanly rebased and revalidated.

#### PR #18 — interim shared-password gate

PR #18 remains an open draft. It adds a fail-closed shared password using `EPC_ACCESS_PASSWORD`.

It is intentionally unmerged because:

- merging without the Render secret would lock everyone out;
- the branch is based on an older stack and needs a clean rebase before use;
- a shared password is only an interim control;
- ENFRA SSO or another approved identity provider is preferable before broad rollout.

### 1.4 The single most important historical rule

**Standard MSAPO document generation applies to all contracts.**

PR #10 proposed skipping the MSAPO for non-RRH contracts. Evan explicitly rejected that after reviewing the behavior. PR #10 was closed unmerged with zero commits.

Do not reintroduce contract-based MSAPO gating.

### 1.5 The single most important engineering rule

**A blocked or missing value is safer than a plausible wrong value.**

Examples:

- no asset is safer than a guessed asset;
- explicit contract selection is safer than silently defaulting to RRH;
- a stale MSAPO should be blocked, not attached;
- an uncertain API write should be reconciled, not retried;
- a disabled integration is safer than fuzzy-mapping columns;
- an unsupported provider should fail diagnostics, not silently fall back to a different provider.

---

## 2. Current branch topology and merge order

```text
main @ 5a03b86
  ├── merged PR #16: correctness + tests
  ├── merged PR #17: remove abandoned webhook/SendGrid
  ├── merged PR #19: normalize HEIC/TIFF/BMP
  └── merged PR #24: validate AI output

agent/smartsheet-three-mode @ 9765276
  └── PR #25 (draft, based on main)
       ├── three Smartsheet routes
       ├── source-record verification
       ├── fail-closed API/idempotency
       ├── reliability dossier/runbooks
       └── 50-test branch suite at last recorded validation

agent/portable-runtime-adapters
  └── PR #26 (draft, based on PR #25)
       ├── provider-neutral AI
       ├── provider-neutral PDF reading
       ├── provider-neutral conversion
       ├── provider-neutral persistence
       ├── host-neutral runtime/entrypoint
       ├── dependency split
       ├── deployment doctor
       └── this updated dossier

agent/add-access-gate
  └── PR #18 (draft, based on older correctness branch; rebase required)
```

### Recommended merge sequence

1. Keep PR #25 draft until its external activation gates are satisfied, or merge only if the team deliberately wants disabled scaffolding in `main` and accepts the review burden.
2. Merge or rebase PR #25 first.
3. Rebase PR #26 onto the resulting `main` and run the entire suite.
4. Merge PR #26 only after current-provider regression tests and deployment diagnostics pass in the target environment.
5. Rebase PR #18 only if the shared-password approach is still desired, configure the secret first, then merge. Prefer SSO instead.

Do not merge PR #26 directly while it is stacked on an unmerged PR #25 unless the full combined diff is intentionally reviewed as one unit.

---

## 3. Updated corrections to the original handoff

The earlier dossier was highly useful but several facts have changed or have now been resolved.

| Earlier issue or uncertainty | Current state |
|---|---|
| Non-RRH administrators greeted as David | **Fixed on `main`** by PR #16 with a neutral greeting. |
| Stale attachments after contract/site/inclusion/exclusion edits | **Fixed on `main`** with deterministic document fingerprints and regeneration blocking. PR #25 independently revalidates the signature before Smartsheet handoff. |
| Unknown facilities silently default to RRH | **Fixed on `main`**; contract/site must be confirmed explicitly. |
| Unity Specialty unreachable | **Fixed on `main`**; it is selectable. Cost code remains manual until mapping is confirmed. |
| Shared output filenames could collide | **Fixed on `main`** with unique internal filenames and 24-hour cleanup. |
| README was stale | **Rewritten on `main`** and further expanded in PR #25/#26. |
| No committed tests or CI | **Fixed on `main`**; pytest and GitHub Actions are present. PR #25 and #26 add extensive coverage. |
| Legacy FastAPI/SendGrid code shipped unused | **Removed from `main`** by PR #17, along with unused dependencies and compose service. |
| TIFF/BMP accepted but unsupported; HEIC omitted | **Fixed on `main`** by PR #19. Unsupported containers are converted to PNG in memory; original bytes are preserved. |
| AI JSON parsing not schema-validated | **Fixed on `main`** by PR #24. |
| Smartsheet PR #15 used fuzzy mapping and had no durable duplicate prevention | **PR #15 closed unmerged**; superseded by PR #25. |
| Smartsheet had only API/manual planning | PR #25 now explicitly supports **manual, URL-prefill, and API** routes independently. |
| Smartsheet ambiguous writes could duplicate rows | PR #25 introduces leases, `uncertain` state, full submission keys, and reconciliation. |
| Application tightly coupled to Anthropic/PyMuPDF/LibreOffice/Render paths | PR #26 introduces provider and runtime abstractions. |
| `/test1` was inferred as a hidden storage default | PR #26 makes runtime paths explicit; Render may still configure `/test1`, but modules no longer infer the platform from it. |
| Container port fixed at 8501 | PR #26 adds a host-neutral entrypoint honoring `PORT`, `EPC_PORT`, and `EPC_HOST`. |
| Template branding question | Text audit found no RRH/facility terms in body/table text. Legal applicability and non-text branding remain unconfirmed. |
| Authentication absent | Still unresolved in production. PR #18 is an unmerged interim password gate; SSO is preferred. |

---

## 4. Business-process narrative

### 4.1 Before the application

A vendor sends a quote for work or equipment at an ENFRA-managed site. A user manually:

1. Reads the quote.
2. Determines whether it is a standard MSAPO or Equipment-only PO.
3. Identifies the contract and site.
4. Determines work category and cost code.
5. Identifies the applicable asset, if any.
6. Transcribes scope, inclusions, exclusions, tax, contact, and pricing.
7. Fills the MSAPO template for standard POs.
8. Converts the document to PDF.
9. Builds an email in the administrator’s required format.
10. Attaches the vendor quote and MSAPO files.
11. Sends the email.
12. Re-enters similar information into future systems as required.

The repetitive and risky work is retyping, routing, asset selection, cost-code selection, document consistency, and attachment consistency.

### 4.2 Current production workflow

1. Choose Standard MSAPO or Equipment-only PO.
2. Upload or paste the quote.
3. Extract text:
   - local PDF text layer when usable;
   - image normalization for unsupported containers;
   - AI native-document or page-image OCR fallback for scans.
4. Analyze the quote with the configured current AI model.
5. Validate the response schema before constructing application objects.
6. Review/edit extracted values.
7. Select/confirm contract and site.
8. Select/confirm work category and cost code.
9. Resolve a conservative asset selection.
10. Select approved inclusions/exclusions.
11. Generate MSAPO DOCX/PDF for standard POs.
12. Create Outlook or Apple Mail send flow.
13. Send manually.
14. Explicitly confirm “I sent it” to record contract-scoped learning.

### 4.3 Intended future Smartsheet workflow

The final process is unknown. PR #25 supports three independent possibilities.

#### Route A — manual copy/paste

The application:

- reuses the verified final PO snapshot;
- presents values in configured form order;
- provides one-tap copy controls;
- tracks progress without storing PO values in browser storage;
- gives safely grouped downloads for the quote and MSAPO files;
- opens the final Smartsheet form.

No API token is required.

#### Route B — exact-label URL prefill

The application:

- uses only administrator-configured exact visible form labels;
- uses exact configured option translations;
- preserves unrelated query parameters;
- replaces mapped duplicates;
- enforces a URL-length ceiling;
- reports skipped fields;
- blocks when required fields are missing.

Files still must be attached manually because a URL cannot carry them.

#### Route C — direct API

The application:

- validates exact column IDs, titles, types, options, and writability;
- converts values to strict field types;
- creates one row;
- uploads attachments;
- records durable idempotency state;
- reconciles ambiguous writes;
- resumes partial attachment uploads safely.

The API path requires a dedicated submission-key column and durable storage.

### 4.4 What remains unknown about the business process

- Does Smartsheet replace the email or supplement it?
- Who owns the final form and sheet?
- What fields are required?
- Which fields are editable after submission?
- Is there an approval stage?
- Does a changed PO update a row or create an amendment?
- Are multiple assets allowed?
- Are multiple file attachments accepted?
- Is the form limited to authenticated ENFRA users?
- Is a service account permitted?
- Who confirms cost-code and asset correctness?

These are process-owner decisions, not code assumptions.

---

## 5. Chronological project history

### Phase 1 — initial MSAPO generator, February 2026

The repository began as a Streamlit application for turning a vendor quote into an MSAPO Scope of Work.

Initial capabilities included:

- Anthropic quote analysis;
- DOCX template modification;
- PDF conversion;
- Outlook email draft generation;
- experimental FastAPI/SendGrid inbound-email scaffolding.

The early README and repository name remained tied to this phase long after the product evolved.

### Phase 2 — early production fixes, June–July 2026

#### PR #1 — model retirement

The configured Anthropic model returned 404. The model ID was updated in code, `render.yaml`, and docs.

Operational lesson: the Render dashboard can override the blueprint. A code/config change may appear ineffective until both are checked.

#### PR #2 — exhibit table cleanup

The real template contained a prechecked/predated first exhibit row. The generator now clears it dynamically rather than editing the controlled template file.

#### PR #3 — Debbie to David

The RRH administrator was changed from Debbie to David.

#### PR #4 — Apple mobile workflow

An Apple Mail share/copy workflow was added because `.eml` does not reliably open as an editable draft on iOS.

### Phase 3 — redesign into Email Process Control, July 2026

#### PR #5 — major product redesign

The application became Email Process Control:

- auto-analysis;
- collapsed scope preview;
- no standalone file-download step;
- RRH site, cost-code, asset, pricing, and EPO rules;
- iPad detection;
- Apple/Outlook send panel;
- wider UI.

#### PR #6 — asset registry and auto-analysis fixes

The RRH registry was expanded and asset labels became human readable. The final reconciled RRH total later became 246 assets.

#### PR #7 — scanned-PDF OCR

Image-only PDFs previously produced no text and no action. AI document/page OCR fallback was added.

#### PR #8 — extraction caching and owner-locked PDFs

OCR was running on every Streamlit rerun and could produce nondeterministic text, resetting later steps. Extraction became content-hash cached. Owner-locked PDFs are normalized in memory for analysis while the original remains unchanged.

#### PR #9 — mobile memory leak and generic contracts

Client-side Blob URLs were created repeatedly and not revoked, matching the reported iPad crash. Lazy creation and cleanup were added.

The application also expanded to 36 non-RRH contracts with contract/site/asset routing and generic cost-code/recipient fields.

#### PR #10 — rejected non-RRH document gating

A proposal to skip MSAPO generation outside RRH was rejected by Evan and closed unmerged. This remains a critical non-regression rule.

#### PR #11 — contract-scoped learning

SQLite-based learning was added for administrators, contacts, and vendor representatives, with strict contract isolation and explicit user confirmation.

#### PR #12 — Outlook Web corruption and filename fix

Quoted-printable HTML was corrupted by Outlook Web when imported from `.eml`. The HTML body changed to base64 transfer encoding.

A hardcoded site-name bug in filenames was also fixed.

#### PR #13 — generic contract recognition and filenames

Non-RRH facility recognition and contract-aware filenames were added.

#### PR #14 — conservative asset selection

The application previously selected the first asset when no match existed, often an air separator. The default became no applicable asset. AI asset hints must resolve to real site assets.

### Phase 4 — original Smartsheet scaffold, July 24–25

#### PR #15 — closed superseded draft

The first Smartsheet draft offered API submission and manual assistance, but used fuzzy column-title aliases and lacked durable idempotency. It was never merged and was closed after PR #25 replaced it.

### Phase 5 — latest correctness takeover, July 27–28

#### PR #16 — merged correctness pass

This pass addressed the highest-priority live issues:

- neutral greeting;
- stale-document prevention;
- explicit unknown contract/site state;
- corrected facility written into the document;
- unique generated filenames;
- generated-file cleanup;
- normalized duplicate generic sites;
- hidden `(unspecified site)` buckets;
- Unity Specialty selectable;
- generic work-category prefill;
- pricing arithmetic warning;
- generic hero/analyzer copy;
- current README;
- committed pytest suite;
- GitHub Actions.

A text audit found no RRH/facility terms in body/table text of the template.

#### PR #17 — merged legacy cleanup

Removed:

- `app/webhook.py`;
- `app/email_handler.py`;
- `run_api.py`;
- FastAPI;
- Uvicorn;
- python-multipart;
- SendGrid;
- obsolete compose/config documentation.

The production Streamlit flow was unchanged.

#### PR #18 — unmerged interim access gate

Adds a shared password and fail-closed behavior. It remains unmerged for the reasons described above.

#### PR #19 — merged image normalization

Added:

- HEIC/HEIF/HIF support;
- TIFF/TIF support;
- BMP support;
- EXIF orientation;
- multi-frame handling;
- frame-count and size limits;
- in-memory PNG conversion;
- original-byte preservation.

#### PR #24 — merged AI response validation

Added a dedicated schema parser that:

- accepts plain or fenced JSON objects;
- rejects malformed, empty, array, trailing-text, and invalid-type responses;
- validates enums and assumption sections;
- supplies safe defaults;
- bounds the short description;
- ignores unknown extra keys safely.

### Phase 6 — Smartsheet production preparation, PR #25

PR #25 was built from scratch rather than merging PR #15.

Major additions:

- `app/po_context.py`;
- `app/smartsheet.py`;
- `app/smartsheet_store.py`;
- `app/smartsheet_ui.py`;
- `pages/2_Smartsheet_PO.py`;
- Smartsheet environment configuration;
- failure-mode documentation;
- API and store tests;
- exact schema validation;
- durable duplicate prevention;
- uncertain-write recovery;
- manual and URL routes.

The first iterations exposed additional problems that were fixed before the branch was considered green:

- active attachment workers were not fully excluded after row creation;
- ambiguous row creation could have been retried;
- corrupted attachment history could have been treated as empty;
- source session state could attach a previous file;
- manual progress could carry between POs;
- core fields could diverge between form and MSAPO;
- fuzzy mappings were unsafe;
- cell truncation was possible;
- strict types were not enforced;
- live tokens needed host restrictions;
- local idempotency loss needed remote reconciliation.

### Phase 7 — portability and provider abstraction, PR #26

PR #26 addressed the risk that ENFRA could require a different:

- AI provider;
- PDF parser/OCR system;
- PDF converter;
- database;
- hosting platform;
- path layout;
- dependency policy.

Provider-neutral contracts and deployment diagnostics were introduced without changing the existing UI’s public calls.

The branch also found and fixed portability-specific defects:

- enterprise AI 400 responses could be retried/mislabeled;
- custom factories might not receive environment configuration;
- native PDF input could be attempted on providers without support;
- a provider failure could trigger unnecessary paid fallback;
- OCR requests were unbounded;
- LibreOffice conversions could conflict or accept stale files;
- Gotenberg could return HTML with HTTP 200;
- read-only images could fail due to repository-relative writable paths;
- live idempotency could use temporary storage;
- container port was hardcoded;
- adapter outputs were insufficiently validated.

---

## 6. Production architecture on `main`

```text
Browser
  │
  ▼
Render Docker service
  └── streamlit run run_web.py
        └── app.web_ui.main()
             ├── app.ocr
             │    ├── PyMuPDF text extraction
             │    ├── image normalization
             │    └── Anthropic OCR fallback
             ├── app.quote_analyzer
             │    ├── Anthropic Messages API
             │    └── app.analysis_schema validation
             ├── app.contracts / app.data.contracts.json
             ├── app.config / app.assets
             ├── app.document_generator
             ├── app.pdf_converter
             ├── app.eml_builder
             └── app.memory (SQLite)
```

### Runtime characteristics

- Single Streamlit service.
- Python 3.12 Docker image.
- LibreOffice installed in the default container.
- Persistent learning database configured through `EPC_DATA_DIR`.
- Generated documents stored in unique files and cleaned after 24 hours.
- No server-side email send.
- No production FastAPI service.
- No application-level authentication on `main`.

---

## 7. Target architecture with PR #25 and PR #26

```text
Browser / Streamlit UI
  │
  ├── Current Email Process Control page
  └── Future Smartsheet PO Handoff page
        │
        ▼
Business/application layer
  ├── quote review and routing
  ├── conservative asset logic
  ├── MSAPO generation
  ├── email composition
  ├── verified PO context
  └── Smartsheet route selection
        │
        ├── AIProvider
        │    ├── Anthropic
        │    ├── OpenAI Chat-compatible HTTP
        │    └── custom factory
        │
        ├── PDFReader
        │    ├── PyMuPDF
        │    └── custom factory
        │
        ├── PDFConverter
        │    ├── LibreOffice
        │    ├── Gotenberg
        │    ├── docx2pdf
        │    ├── none
        │    └── custom factory
        │
        ├── MemoryBackend
        │    ├── SQLite
        │    ├── disabled
        │    └── custom factory
        │
        ├── SubmissionStore
        │    ├── durable SQLite
        │    └── custom managed store
        │
        └── RuntimeSettings
             ├── template path
             ├── persistent data path
             ├── work path
             ├── output path
             ├── host
             └── port
```

The goal is not to abstract business rules. Contract routing, tax handling, asset safety, document consistency, and Smartsheet semantics remain application-owned. Only infrastructure-sensitive behavior is replaceable.

---

## 8. Module-by-module guide

### Production and core application

| File | Status | Responsibility and cautions |
|---|---|---|
| `run_web.py` | Current | Existing Streamlit entrypoint. PR #26 adds `app.entrypoint` for host-neutral launch. |
| `app/web_ui.py` | Current, fragile | Large orchestration/UI module. Streamlit reruns on every interaction. Preserve hash/signature state carefully. Still a refactor candidate. |
| `app/quote_analyzer.py` | Current | Owns business prompt, price stripping, and `QuoteAnalysis` construction. PR #26 delegates model calls to `AIProvider`. |
| `app/analysis_schema.py` | Current | Validates AI JSON. Do not bypass this for replacement providers. |
| `app/ocr.py` | Current | Owns extraction strategy and image normalization. PR #26 delegates PDF reading and AI calls. |
| `app/document_generator.py` | Current | Opens the real template, clears exhibit row, verifies sentinel, appends reviewed sections. |
| `app/pdf_converter.py` | Current and expanded in PR #26 | Main currently supports existing backends; PR #26 formalizes converter contracts and validates output signatures. |
| `app/eml_builder.py` | Current | Produces HTML/plain drafts and `.eml`. HTML uses base64 transfer encoding. |
| `app/contracts.py` | Current | Generic contract/site/asset data and matching. |
| `app/data/contracts.json` | Current | 36 non-RRH contracts, 106 site keys, 11,368 asset rows at last audit. |
| `app/config.py` | Current | RRH facilities, category rules, cost-code derivation, constants. |
| `app/assets.py` | Current | Curated RRH assets. Moving data out of code remains a future improvement. |
| `app/memory.py` | Current and expanded in PR #26 | Contract-isolated learning. PR #26 adds backend selection. |

### Smartsheet layer in PR #25

| File | Responsibility |
|---|---|
| `app/po_context.py` | Reconstructs a verified, immutable-enough PO snapshot from current Streamlit state; validates analysis/quote/document relationships. |
| `app/smartsheet.py` | Configuration, manual rows, exact prefill, strict API cells, live schema validation, row creation, attachment upload, reconciliation. |
| `app/smartsheet_store.py` | Durable idempotency, leases, row IDs, attachment fingerprints, partial/uncertain states, cleanup, reconciliation. |
| `app/smartsheet_ui.py` | Mobile-friendly manual copy assistant. Stores only progress indexes in local storage. |
| `pages/2_Smartsheet_PO.py` | Separate handoff page. Locks source-controlled fields and leaves future-only decisions editable. |
| `docs/FAILURE_MODES_AND_CONTROLS.md` | Detailed failure register, activation gates, and incident runbooks. |

### Portability layer in PR #26

| File | Responsibility |
|---|---|
| `app/adapter_loader.py` | Loads trusted `package.module:factory` adapters and validates contracts. Environment configuration only; never user input. |
| `app/ai_provider.py` | Provider-neutral request model and built-in AI providers. |
| `app/pdf_reader.py` | Provider-neutral PDF read/render contracts and PyMuPDF implementation. |
| `app/runtime.py` | Runtime settings and path/host/port resolution. |
| `app/entrypoint.py` | Portable Streamlit launcher honoring platform-assigned ports. |
| `app/doctor.py` | Predeployment diagnostics, including JSON output. |
| `docs/PORTABILITY.md` | Provider, packaging, deployment, and migration guide. |
| `docs/NEXT_LLM_SMARTSHEET_AND_PORTABILITY_HANDOFF.md` | Transition-specific continuity document. |
| `tests/test_portability.py` | Adapter and runtime contract tests. |
| `requirements-core.txt` | Provider-neutral dependencies. |
| `requirements-default-adapters.txt` | Current Anthropic/PyMuPDF/HEIC dependencies. |

---

## 9. Business-rule specification

### 9.1 Standard MSAPO

- Used when the vendor performs site work.
- Applies to all contracts.
- Requires quote plus generated DOCX; PDF is included when conversion succeeds.
- Includes asset when applicable.
- Subject uses `MSA PO`.
- Document must match current contract, site, inclusions, and exclusions.

### 9.2 Equipment-only PO

- Used when equipment is delivered by a third party and the vendor does not visit the site.
- Skips MSAPO generation.
- Attaches original quote only.
- Uses `EPO` subject.
- Asset field is omitted in the Smartsheet context.
- Uses a different bullet/field order.

### 9.3 Contract selection

- RRH is a dedicated contract path.
- Generic contracts come from `contracts.json`.
- Unknown recognition must not silently choose RRH.
- Contract choice controls site list, assets, cost-code behavior, recipient, filename, and learning scope.

### 9.4 Site selection

- RRH uses curated short labels and configured rules.
- Generic contracts use exported site keys after normalization.
- `(unspecified site)` buckets are hidden from normal selection.
- Case-only duplicate site keys are normalized.
- Large site asset lists remain a UX concern.

### 9.5 Work category and cost code

- RRH uses site-restricted categories and derived Appendix-A-style cost codes.
- Unity Specialty is selectable but requires manual cost code until mapping is confirmed.
- Generic contracts use editable fields; analyzer category can prefill.
- Do not invent generic cost-code algorithms without contract-specific authority.

### 9.6 Asset selection

- A wrong asset is worse than no asset.
- AI may return a specific tag reference only.
- The tag must resolve to a real asset under the selected contract/site.
- Leading-zero variants may normalize.
- Default is `None Applicable`.
- One asset only is currently supported.

### 9.7 Pricing

- If subtotal and tax are separately itemized, include them with total.
- Otherwise include total only.
- Main warns when subtotal + tax differs from total.
- PR #25 blocks invalid amount formats and checks cell-size limits.
- The application does not determine purchasing approval thresholds.

### 9.8 Tax

- `included`, `excluded`, or `unclear`.
- Tax status and notes are separate from the scope.
- Price strings are stripped from scope/inclusion/exclusion prose.
- Unclear tax requires review.

### 9.9 Original file preservation

- The vendor file’s original bytes are preserved for attachment.
- Analysis may use normalized image frames or an in-memory decrypted PDF.
- Normalized/decrypted analysis bytes must not replace the original attachment.

### 9.10 Contract learning

- Strictly contract scoped.
- Administrators and contact pairs surface after five recorded uses.
- Vendor reps can surface immediately when the vendor is recognized.
- Recording occurs only after explicit user confirmation.
- There is no current management/delete UI.

---

## 10. Correctness and reliability changes merged into `main`

### 10.1 Neutral email greeting

Every email draft now uses a neutral greeting unless explicitly supplied. Non-RRH administrators are no longer addressed as David.

### 10.2 Stale-document protection

A deterministic signature includes:

- analysis identity;
- contract;
- site;
- selected inclusions;
- selected exclusions.

If any of these changes after generation, the old document is blocked until regeneration.

### 10.3 Explicit unknown routing

Unrecognized quotes require contract/site selection. They no longer inherit RRH routing, cost codes, or recipient by default.

### 10.4 Corrected facility in document

The selected/canonical facility, not only the model’s raw extraction, is passed into document generation.

### 10.5 Concurrency-safe generated files

Each generation receives a unique on-disk filename. Files older than 24 hours are cleaned up.

This reduces cross-session overwrite and unbounded growth risk, but the application should still use ephemeral work storage and remain single-instance unless storage architecture is revisited.

### 10.6 Generic data cleanup

- Case-only site duplicates normalized.
- `(unspecified site)` hidden.
- Unity Specialty selectable.
- Generic work category prefilled.

### 10.7 Current tests and CI

A committed pytest suite and GitHub Actions workflow now run on pull requests and `main` pushes. JUnit artifacts are uploaded in later hardening branches.

### 10.8 Image-format safety

Unsupported image containers are converted to PNG for analysis, with:

- EXIF orientation;
- frame ordering;
- frame count limit;
- size checks;
- original-byte preservation.

### 10.9 AI response schema safety

Malformed or type-invalid AI output produces a clear application error instead of reaching the dataclass constructor.

### 10.10 Legacy removal

The unsupported inbound email server and its dependencies are gone. Do not restore them without a new product decision and current architecture.

---

## 11. Smartsheet implementation in PR #25

### 11.1 Configuration model

All routes are independent and disabled until configured.

Key variables include:

```text
SMARTSHEET_FORM_URL
SMARTSHEET_FORM_ORDER
SMARTSHEET_FORM_REQUIRED_FIELDS
SMARTSHEET_URL_PREFILL_ENABLED
SMARTSHEET_PREFILL_MAX_URL_LENGTH
SMARTSHEET_FORM_FIELD_MAP_JSON
SMARTSHEET_FORM_VALUE_MAP_JSON
SMARTSHEET_API_MODE
SMARTSHEET_API_TOKEN
SMARTSHEET_SHEET_ID
SMARTSHEET_COLUMN_SPECS_JSON
SMARTSHEET_REQUIRED_FIELDS
SMARTSHEET_ROW_POSITION
```

### 11.2 Verified PO context

`POContext` protects against stale or mismatched session state.

It verifies:

- analysis token versus quote text;
- upload hash versus extracted text;
- pasted text versus previous upload;
- current contract and site;
- approved inclusions/exclusions;
- current document signature;
- pricing arithmetic;
- expected standard/EPO attachments.

It creates a deterministic context ID that namespaces the handoff page.

### 11.3 Locked versus editable fields

The handoff page locks fields already controlled by the source workflow:

- order type;
- contract;
- site;
- work category;
- cost code;
- asset;
- vendor;
- vendor contact;
- administrator;
- description;
- reviewed scope;
- subtotal;
- tax;
- total;
- tax status.

Future-only fields remain editable:

- requester;
- facility address when needed;
- O&M relationship;
- billing method;
- customer PO;
- estimated dates;
- customer representative;
- technician requirement;
- copy preference;
- additional instructions.

This prevents the form from being “corrected” independently of the attached MSAPO.

### 11.4 Manual route

- Requires a verified HTTPS Smartsheet form URL.
- Uses configured order.
- Blocks on source and required-field problems.
- Copies values one at a time or as a list.
- Auto-advances.
- Stores only completed indexes in local storage.
- Progress key includes exact labels and values.
- Provides grouped safe filenames.

### 11.5 URL-prefill route

- Requires explicit enable flag.
- Requires exact label mapping.
- Supports exact option translation.
- Replaces existing mapped parameters.
- Preserves unrelated query parameters.
- Enforces configurable maximum URL length.
- Reports skipped values.
- Does not imply attachments are transferred.

### 11.6 API route

API modes:

```text
disabled
dry_run
live
```

Live readiness requires:

- token;
- sheet ID;
- explicit column specifications;
- exact title/type for every mapped column;
- required-field list;
- dedicated `submission_key` column;
- durable submission store.

### 11.7 Strict cell handling

- Amounts become numeric values.
- Dates become ISO dates.
- Checkboxes become booleans.
- Contact columns require valid email.
- Picklists require exact option matches.
- Cells use strict mode.
- Values over 4,000 characters are blocked.

### 11.8 Schema drift handling

Before writing, the API path checks:

- column ID exists;
- title matches exactly;
- type matches exactly;
- expected options still exist;
- column is not locked;
- column is not formula/system generated.

Any drift blocks the write.

### 11.9 Idempotency and concurrency

The submission key hashes:

- populated logical fields;
- attachment names;
- attachment byte hashes.

The store records:

- status;
- row ID;
- attached fingerprints;
- last error;
- update time;
- lease token;
- lease expiration;
- attempts.

Only the lease owner may update a claimed submission.

### 11.10 Ambiguous row creation

If a row-creation response is uncertain due to timeout/network/server behavior:

- status becomes `uncertain`;
- automatic retry is blocked;
- user is told not to resubmit;
- reconciliation searches for the full submission key;
- the exact key cell is verified;
- one exact row can be adopted;
- zero rows means wait and retry search, not create another;
- multiple rows require administrator intervention.

### 11.11 Attachment recovery

Each remote attachment name includes a deterministic content fingerprint.

If upload response is lost:

1. List remote row attachments.
2. Check exact deterministic name.
3. Record success if present.
4. Otherwise leave partial and permit safe resume.

### 11.12 Persistence behavior

Corrupt or unavailable duplicate-prevention state blocks API submission. There is no in-memory fallback for live mode.

SQLite is acceptable only on a durable, single-instance deployment. A multi-instance host requires a custom transactional store.

---

## 12. Failure-mode work and incident recovery

The full register is in `docs/FAILURE_MODES_AND_CONTROLS.md`. Major categories include:

### Quote and source state

- unreadable new upload with old analysis;
- pasted text with stale uploaded file;
- quote/analysis fingerprint mismatch;
- malformed AI output;
- invented asset;
- unknown facility;
- pricing mismatch;
- cell truncation.

### Documents and attachments

- changed routing after generation;
- cross-session file collision;
- empty/duplicate/oversized attachment;
- unsafe filename;
- lost upload response;
- corrupt attachment history;
- PDF conversion failure.

### Streamlit/manual workflow

- widget value leakage between quotes;
- manual progress leakage;
- clipboard incompatibility;
- form value diverging from MSAPO;
- opening a form from an invalid source package;
- form label/order drift.

### URL prefill

- wrong guessed parameter;
- duplicate parameters;
- excessive URL length;
- option mismatch;
- user assuming files were included;
- required form fields missing.

### API

- repurposed column ID;
- duplicate logical mappings;
- typo in configured field;
- deleted option;
- locked/formula/system column;
- wrong data type;
- missing required field;
- missing durable key;
- token sent to wrong host.

### Concurrency/idempotency

- double click;
- concurrent attachment worker;
- crashed worker;
- ambiguous row creation;
- row created but local ID not recorded;
- lost local DB;
- changed PO generating a new key;
- unbounded history.

### Operations/security

- public URL;
- excessive token permissions;
- dashboard/blueprint drift;
- absent/full/corrupt disk;
- multiple instances;
- Smartsheet outage/rate limit;
- sensitive logging;
- template legal applicability;
- real-device differences;
- final PO schema differing from example.

Incident runbooks cover uncertain writes, partial attachments, schema drift, form prefill failure, idempotency database loss, and post-submission correction.

---

## 13. Portability implementation in PR #26

### 13.1 Design boundary

Infrastructure can change. Business behavior cannot silently change with it.

Provider adapters must not own:

- contract routing;
- cost-code rules;
- asset validation;
- tax interpretation;
- document signature logic;
- Smartsheet idempotency semantics;
- attachment selection;
- user approval rules.

They provide narrow capabilities only.

### 13.2 AI provider contract

A provider exposes:

- a name;
- capabilities such as text, image, native document;
- `complete(AIRequest) -> str`;
- diagnostics.

`AIRequest` carries:

- operation name;
- system instructions;
- prompt text;
- optional image/document parts;
- output-token ceiling.

Built-ins:

- Anthropic;
- OpenAI Chat Completions-compatible HTTP endpoint;
- custom trusted adapter.

### 13.3 AI safety changes

- Provider is loaded lazily.
- Replacement endpoints must be explicit.
- Non-transient 4xx errors are not retried.
- Authentication/quota/network failures are classified inside the adapter.
- Input size is bounded and rejected rather than truncated.
- Native PDF input is attempted only with advertised capability.
- A failed primary request does not automatically trigger an unrelated paid fallback.
- AI output still passes through `analysis_schema.py`.

### 13.4 PDF reader contract

A reader provides:

- `extract_text(data) -> PDFReadResult`;
- `render_pages(data, dpi, max_pages, max_pixels_per_page)`;
- diagnostics.

Built-in:

- PyMuPDF.

Custom readers may use:

- another local library;
- a cloud document service;
- an internal OCR platform.

### 13.5 PDF/OCR safety changes

- Return objects validate page count, media type, and non-empty bytes.
- Password-to-open PDFs fail clearly.
- Owner-locked PDFs may normalize in memory.
- Embedded text must meet quality threshold.
- Page count is bounded.
- DPI is configurable.
- Pixels per page are bounded.
- Aggregate rendered bytes are bounded.
- Pages are batched for OCR.
- Empty render results fail explicitly.
- Images have a size ceiling.

### 13.6 PDF converter contract

A converter provides:

- `convert(docx_path, output_dir) -> Path`;
- diagnostics.

Built-ins:

- LibreOffice;
- Gotenberg;
- docx2pdf;
- none;
- custom.

### 13.7 Conversion hardening

- LibreOffice uses a unique profile per conversion.
- Each conversion gets a unique output directory.
- Stale preexisting PDFs cannot be accepted.
- Output must begin with a PDF signature.
- Gotenberg must return valid PDF bytes, not only HTTP 200.
- Remote Gotenberg requires HTTPS unless an explicit local/test exception exists.
- `none` produces a controlled DOCX-only workflow.

### 13.8 Memory backend

Options:

- SQLite;
- disabled;
- custom.

A custom backend must preserve:

- contract isolation;
- send recording;
- administrator suggestions;
- contact suggestions;
- vendor reps;
- diagnostics.

### 13.9 Submission-store backend

Options:

- durable SQLite;
- custom managed store.

A custom implementation must preserve:

- claim semantics;
- exclusive leases;
- row recording;
- attachment fingerprints;
- final statuses;
- reconciliation;
- cleanup;
- fail-closed behavior.

Do not replace this with an in-memory dictionary or non-transactional cache.

### 13.10 Runtime settings

PR #26 separates:

```text
EPC_TEMPLATE_PATH
EPC_DATA_DIR
EPC_WORK_DIR
EPC_OUTPUT_DIR
EPC_HOST
EPC_PORT
PORT
```

The current Render deployment may still use `/test1`, but application code no longer assumes that path exists.

### 13.11 Host-neutral entrypoint

```bash
python -m app.entrypoint
```

The entrypoint honors the host platform’s assigned port.

This supports Docker/PaaS environments that do not permit a fixed port.

### 13.12 Deployment doctor

```bash
python -m app.doctor
python -m app.doctor --json
```

Checks include:

- template;
- runtime paths;
- writable work/output;
- AI configuration/capabilities;
- PDF reader;
- PDF converter;
- memory backend;
- submission store;
- host/port;
- live Smartsheet persistence requirements.

A passing doctor is necessary but not sufficient. Real end-to-end tests remain required.

### 13.13 Dependency split

- `requirements-core.txt` — provider-neutral application dependencies.
- `requirements-default-adapters.txt` — Anthropic, PyMuPDF, HEIC, and current adapters.
- `requirements.txt` — installs both for backward compatibility.

A replacement environment can install core plus an internal adapter package.

---

## 14. Security, privacy, and governance

### 14.1 Current production authentication

There is no merged application-level authentication on `main`.

The Render URL’s public reachability is unknown from the repository. Treat this as a blocker before wider rollout.

### 14.2 PR #18

The shared-password gate:

- uses constant-time comparison;
- is session based;
- fails closed when the secret is missing;
- has sign-out;
- requires secret configuration before merge.

Limitations:

- no individual identity;
- no roles;
- no central revocation;
- no audit trail;
- shared credential distribution risk.

### 14.3 Preferred future identity

ENFRA SSO or an approved identity provider should protect the application before broad organizational use.

Questions:

- Which users are authorized?
- Do permissions vary by contract?
- Is administrator access separate?
- Is audit logging required?
- Is device compliance required?

### 14.4 AI data governance

Vendor quotes may contain:

- pricing;
- contacts;
- facility addresses;
- asset identifiers;
- work descriptions;
- contractual information.

The current application may send quote text, images, or PDF analysis copies to Anthropic. ENFRA IT is aware of the AI usage through prior governance communication, but formal approval boundaries remain external.

Replacement-provider work should confirm:

- data retention;
- training use;
- geography;
- encryption;
- logging;
- access control;
- incident response;
- contractual protections.

### 14.5 Smartsheet token governance

Use a dedicated least-privilege service account, not a personal token, if API submission is approved.

The account should have access only to the required sheet/workspace.

### 14.6 Logging

Do not log:

- tokens;
- authorization headers;
- full quote text;
- attachment bytes;
- full PO payloads;
- sensitive email addresses beyond operational necessity.

### 14.7 Template governance

Text audit found no RRH/facility wording in ordinary body/table text. This does not establish:

- legal applicability;
- header/footer/image branding;
- contract-specific language requirements;
- version authority.

A business/legal owner must confirm the template.

---

## 15. Deployment and operations

### 15.1 Current Render assumptions

Current configuration has historically included:

- Docker service;
- Starter plan;
- Anthropic key;
- model setting;
- LibreOffice backend;
- `EPC_DATA_DIR=/test1`;
- persistent disk configured in dashboard.

The repository cannot confirm the actual dashboard state.

### 15.2 Dashboard versus blueprint

A Render dashboard environment variable can override `render.yaml`. This caused a real production model-ID fix to appear ineffective.

Every deployment investigation should compare:

- repository config;
- dashboard config;
- runtime diagnostic output.

### 15.3 Persistent disk

Contact learning and live Smartsheet idempotency require persistence.

Verify:

- mount exists;
- path is writable;
- free space;
- backup plan;
- restore plan;
- restart persistence;
- ownership/permissions;
- monitoring.

### 15.4 Single-instance constraint

SQLite on a local disk is a single-instance design.

Before horizontal scaling:

- migrate contact learning;
- migrate Smartsheet submission state;
- use a shared transactional database;
- verify lease semantics under concurrency.

### 15.5 Read-only container support

PR #26 moves writable work/output defaults outside the repository, improving compatibility with immutable images and serverless/container platforms.

### 15.6 Cold starts and timeouts

Potential expensive operations:

- dependency import;
- LibreOffice startup;
- large image normalization;
- page rendering;
- AI OCR;
- AI analysis;
- Smartsheet attachment upload.

No production observability platform is currently integrated.

### 15.7 Backups

At minimum, back up:

- contact-learning database;
- Smartsheet submission database;
- approved template version;
- environment configuration mapping;
- exact Smartsheet column specifications.

Do not back up ephemeral generated files unless required by policy.

---

## 16. Testing dossier

### 16.1 Current committed tests

`main` contains tests for:

- email body and `.eml` behavior;
- neutral greeting;
- document paths;
- contract data normalization;
- Unity Specialty;
- pricing arithmetic;
- stale document signatures;
- image normalization;
- AI schema parsing.

### 16.2 PR #25 tests

Coverage includes:

- default inert configuration;
- unsafe hosts;
- unknown logical fields;
- duplicate column IDs;
- exact prefill replacement;
- option translation;
- URL limits;
- form ordering;
- source-context integrity;
- pasted-text attachment isolation;
- stale document exclusion;
- EPO behavior;
- strict API values;
- live schema drift;
- submission fingerprints;
- active lease exclusion;
- lease expiry;
- partial resume;
- ambiguous creation block;
- local-state recovery;
- corrupt attachment history;
- retention cleanup;
- lost attachment response reconciliation.

### 16.3 PR #26 tests

Coverage includes:

- custom factory loading;
- environment-aware factories;
- provider capability validation;
- enterprise AI error classification;
- input bounds;
- PDF reader result validation;
- OCR limits/batching;
- PDF converter signature validation;
- runtime path defaults;
- host/port behavior;
- live durable-store requirements;
- doctor diagnostics.

### 16.4 Real-system tests still required

- Redacted real text PDF.
- Redacted scanned PDF.
- Redacted owner-locked PDF.
- HEIC photo from a real iPhone.
- Large multi-page quote.
- No-asset quote.
- Exact asset tag with leading-zero normalization.
- RRH parity quote.
- Non-RRH generic quote.
- Real Outlook Web.
- New Outlook.
- Classic Outlook.
- Apple Mail.
- Real iPhone/iPad Safari.
- Final Smartsheet form manual path.
- Final form URL prefill.
- Live sheet schema dry run.
- Controlled API row and all attachments.
- Ambiguous API write recovery.
- Partial attachment recovery.
- Host restart persistence.
- Replacement AI quality.
- Replacement PDF/OCR quality.
- Replacement converter visual fidelity.

### 16.5 CI notification lesson

During early work, temporary self-modifying workflows and repeated intermediate pushes generated many GitHub failure notifications.

Current rule:

- validate locally or in a non-PR branch where possible;
- batch changes;
- open/push one coherent final branch state;
- do not rerun deleted temporary workflows;
- do not use self-deleting patch workflows;
- use normal commits and stable tests;
- upload test artifacts for diagnosis.

This is an operational lesson, not an application feature.

---

## 17. What was learned during the latest takeover

### 17.1 The repository was more mature than its README suggested

The original README significantly understated the multi-contract data and current workflow. The code had 36 non-RRH contracts and more than 11,000 generic asset rows, not a small RRH-only generator.

### 17.2 Correctness defects often came from workflow ordering, not model quality

Examples:

- generating before final contract/site selection;
- keeping old files after UI edits;
- selecting index zero when there was no asset match;
- retaining prior uploaded-file state when pasted text became active;
- allowing form fields to diverge from the attached document.

The solution is deterministic state relationships, not merely “better AI.”

### 17.3 AI should suggest, but code must validate

The AI may extract:

- facility;
- work category;
- asset reference;
- pricing;
- contact;
- scope.

Code must validate:

- response shape;
- enum values;
- asset existence;
- contract/site routing;
- price arithmetic;
- document freshness;
- form/API schema.

### 17.4 Idempotency is not just a hash

A robust write flow requires:

- deterministic key;
- durable storage;
- atomic claim;
- exclusive lease;
- row ID persistence;
- attachment state;
- ambiguous outcome state;
- remote reconciliation;
- cleanup;
- recovery after local loss.

### 17.5 API retries must distinguish reads from writes

Safe GET operations can use bounded retry. Row creation cannot be blindly retried after an uncertain network result.

### 17.6 Exact configuration is safer than fuzzy integration

Fuzzy Smartsheet column aliases were rejected because a plausible match can put a correct value in the wrong field.

The same principle applies to:

- form labels;
- option values;
- provider capabilities;
- adapter contracts;
- conversion output.

### 17.7 Portability requires dependency and behavior contracts

Replacing an SDK import is not enough. A provider swap needs:

- request contract;
- capability declaration;
- error classification;
- diagnostic;
- output validation;
- regression fixtures;
- rollback configuration.

### 17.8 A test pass does not equal integration readiness

PR #25 and PR #26 are draft because external systems are missing, not because the unit tests fail.

### 17.9 Shared local SQLite is not a scalable service database

The current architecture is appropriate for one instance. Scaling without storage migration would break learning and idempotency.

### 17.10 Documentation must label production, prepared, and hypothetical states

Several earlier descriptions blurred merged code, draft PRs, proposed designs, and business assumptions. The updated documentation keeps them separate.

---

## 18. Updated decision log

| ID | Decision | Reason | Current status |
|---|---|---|---|
| D-01 | Streamlit remains the current UI | Existing user workflow and rapid iteration | Current |
| D-02 | Dockerized deployment | Portable baseline | Current |
| D-03 | Standard MSAPO for all contracts | Explicit Evan correction | Inviolable |
| D-04 | EPO skips MSAPO | Separate business case | Current |
| D-05 | Original quote bytes preserved | Evidentiary/correctness requirement | Current |
| D-06 | Unknown route requires confirmation | Wrong RRH route is worse than blank | Current |
| D-07 | No asset by default | Wrong tag is worse than none | Current |
| D-08 | Neutral greeting | Generic administrators must not be called David | Current |
| D-09 | Base64 `.eml` HTML | Outlook Web corruption | Current |
| D-10 | Per-contract learning only | Prevent cross-contract data leakage | Current |
| D-11 | Explicit send confirmation | Client-side send cannot be observed | Current |
| D-12 | Unique generated files + cleanup | Concurrency and disk growth | Current |
| D-13 | Strict AI response validation | API success does not guarantee valid payload | Current |
| D-14 | Remove abandoned webhook | Unsupported/dead surface | Current |
| D-15 | Manual, URL, API Smartsheet routes independent | Final process unknown | PR #25 |
| D-16 | Exact form labels and exact column specs | Fuzzy matches are unsafe | PR #25 |
| D-17 | Strict typed Smartsheet cells | Avoid coercion and silent errors | PR #25 |
| D-18 | Durable full submission key | Reconciliation and duplicate safety | PR #25 |
| D-19 | Atomic expiring leases | Double-click and concurrency safety | PR #25 |
| D-20 | Ambiguous writes become `uncertain` | Blind retry may duplicate | PR #25 |
| D-21 | Source-controlled fields locked on handoff page | Form/document consistency | PR #25 |
| D-22 | AI, PDF, conversion, storage behind adapters | ENFRA may change providers | PR #26 |
| D-23 | Business rules stay outside adapters | Provider swap must not alter behavior | PR #26 |
| D-24 | Dependencies split core/default adapters | Approved-stack portability | PR #26 |
| D-25 | Deployment doctor required | Catch configuration problems before traffic | PR #26 |
| D-26 | Live SQLite requires explicit durable path | Temporary idempotency is unsafe | PR #26 |
| D-27 | Shared password stays unmerged until secret exists | Fail-closed gate could lock out users | PR #18 |
| D-28 | Prefer SSO for broad rollout | Identity, revocation, auditability | External decision |

---

## 19. Rejected, abandoned, superseded, and deferred work

### Rejected

#### RRH-only MSAPO gating

Do not revive PR #10.

#### Fuzzy Smartsheet column matching

Do not restore PR #15’s alias/substring mapping for live writes.

#### Blind retries after ambiguous write

Do not retry row creation when the remote outcome is unknown.

#### In-memory live idempotency

Do not degrade live API duplicate prevention to session/local memory.

### Abandoned

- FastAPI inbound email server.
- SendGrid reply flow.
- Legacy email handler.
- One-time template generator as production behavior.

### Superseded

- Explicit Analyze button → automatic analysis.
- Standalone file-download workflow → email attachments, except deliberate Smartsheet manual downloads.
- Quoted-printable HTML → base64.
- First-asset fallback → no applicable asset.
- PR #15 → PR #25.
- direct vendor SDK coupling → PR #26 adapter contracts.

### Deferred

- ENFRA SSO.
- Multi-asset POs.
- Memory management UI.
- Search/typeahead for 3,000-item asset lists.
- Managed shared database.
- Import/update tooling for contract/asset data.
- Audit/history UI.
- Quote number/date/expiration extraction.
- Amendment/update semantics after submission.
- Observability and metrics.
- Repository rename.
- `web_ui.py` decomposition.
- Contract-specific templates if legal review requires them.

---

## 20. Known issues and residual risks

### Critical/external

1. **Authentication is not merged.** Public reachability unknown.
2. **Template legal applicability is unconfirmed.** Text audit is not legal approval.
3. **Smartsheet final form/sheet do not exist in the repository context.**
4. **No live API test has been completed.**
5. **No approved service account/token is available.**
6. **Persistent disk/backup state is unverified.**
7. **Real Safari and all email clients are not comprehensively tested.**
8. **Replacement-provider governance is unknown.**

### High

9. `web_ui.py` remains large and state-sensitive.
10. Large asset dropdowns are difficult to use.
11. One PO supports one asset only.
12. A changed PO after submission has no defined amendment workflow.
13. Contact learning has no management/delete interface.
14. “I sent it” remains user-asserted, not independently verified.
15. Data exports have no automated refresh pipeline.
16. Single-instance SQLite limits scaling.
17. No centralized monitoring or alerting.
18. AI quality may differ substantially under a replacement provider.
19. A replacement converter may alter document layout.
20. Smartsheet search indexing delay affects reconciliation timing.

### Medium/low

21. Repository name still says `msapo-generator`.
22. Some UI language may still reflect the original workflow.
23. No formal release/versioning process.
24. No structured audit log of generated/submitted POs.
25. No automatic secret-rotation workflow.

---

## 21. Data inventory

### RRH

- 9 selectable sites.
- 246 assets across 7 sites with records.
- Massena and Gouverneur have no assets on file.
- Unity Specialty is now selectable but has no confirmed cost-code mapping.

### Generic contracts

At last detailed audit:

- 36 contracts.
- 106 site keys.
- 11,368 asset rows.

Large examples:

- Tulane: approximately 3,040 assets.
- Hampton: approximately 2,629 assets.
- Conway Hospital: hundreds.
- UNO: hundreds.

### Data-quality concerns

- Source exports can contain case-variant sites.
- Some contracts contained `(unspecified site)` buckets.
- No automated owner/refresh cadence is recorded.
- Asset selection UI needs search/typeahead for very large sets.

---

## 22. Environment-variable reference

### Core/current

```text
ANTHROPIC_API_KEY
ANTHROPIC_MODEL
PDF_BACKEND
EPC_DATA_DIR
```

### Runtime portability

```text
EPC_TEMPLATE_PATH
EPC_DATA_DIR
EPC_WORK_DIR
EPC_OUTPUT_DIR
EPC_HOST
EPC_PORT
PORT
EPC_REQUESTER_NAME
```

### AI portability

```text
EPC_AI_PROVIDER=anthropic|openai_chat_compatible|custom
EPC_AI_API_KEY
EPC_AI_MODEL
EPC_AI_ENDPOINT
EPC_AI_ADAPTER
EPC_AI_MAX_INPUT_CHARS
```

Legacy Anthropic variables remain supported in PR #26 for backward compatibility.

### PDF reader/OCR

```text
EPC_PDF_READER=pymupdf|custom
EPC_PDF_READER_ADAPTER
EPC_PDF_TEXT_MIN_CHARS
EPC_OCR_MAX_PAGES
EPC_OCR_DPI
EPC_OCR_PAGES_PER_BATCH
EPC_OCR_MAX_PIXELS_PER_PAGE
EPC_OCR_MAX_TOTAL_IMAGE_BYTES
```

### PDF conversion

```text
EPC_PDF_CONVERTER=libreoffice|gotenberg|docx2pdf|none|custom
EPC_PDF_CONVERTER_ADAPTER
GOTENBERG_URL
```

### Memory

```text
EPC_MEMORY_BACKEND=sqlite|disabled|custom
EPC_MEMORY_ADAPTER
```

### Submission store

```text
EPC_SUBMISSION_STORE_BACKEND=sqlite|custom
EPC_SUBMISSION_STORE_ADAPTER
```

### Smartsheet form/manual/prefill

```text
SMARTSHEET_FORM_URL
SMARTSHEET_FORM_ORDER
SMARTSHEET_FORM_REQUIRED_FIELDS
SMARTSHEET_URL_PREFILL_ENABLED
SMARTSHEET_PREFILL_MAX_URL_LENGTH
SMARTSHEET_FORM_FIELD_MAP_JSON
SMARTSHEET_FORM_VALUE_MAP_JSON
```

### Smartsheet API

```text
SMARTSHEET_API_MODE=disabled|dry_run|live
SMARTSHEET_API_TOKEN
SMARTSHEET_SHEET_ID
SMARTSHEET_COLUMN_SPECS_JSON
SMARTSHEET_REQUIRED_FIELDS
SMARTSHEET_ROW_POSITION=top|bottom
SMARTSHEET_API_BASE_URL
SMARTSHEET_ALLOW_CUSTOM_API_BASE
```

### Interim password gate

```text
EPC_ACCESS_PASSWORD
```

Never commit real secret values or production mappings.

---

## 23. Activation and migration sequences

### 23.1 Manual Smartsheet route

1. Obtain final form URL.
2. Confirm HTTPS Smartsheet domain.
3. Confirm field order.
4. Confirm required fields.
5. Confirm multi-file behavior.
6. Configure form variables.
7. Test on Windows.
8. Test on real iPad/iPhone Safari.
9. Verify quote and MSAPO attachment selection.
10. Enable for controlled users.

### 23.2 URL-prefill route

1. Complete manual-route setup.
2. Verify the final form accepts query prefilling.
3. Capture exact labels.
4. Capture exact option values.
5. Configure exact mappings.
6. Test short and long scopes.
7. Verify URL-length behavior.
8. Verify files are still attached manually.
9. Enable flag.
10. Retain manual fallback.

### 23.3 API route

1. Confirm API plan/access.
2. Create least-privilege service account.
3. Share only required sheet.
4. Create submission-key text column.
5. Record exact ID/title/type/options.
6. Configure required fields.
7. Verify durable store.
8. Run doctor.
9. Set dry-run.
10. Validate schema.
11. Create controlled test row.
12. Upload every expected file.
13. Test duplicate click.
14. Test partial attachment recovery.
15. Test ambiguous write reconciliation.
16. Verify restart persistence.
17. Approve operational runbook.
18. Set live.

### 23.4 Replacement AI

1. Confirm governance/contract.
2. Build adapter.
3. Add contract tests.
4. Run redacted quote corpus.
5. Compare field accuracy.
6. Compare OCR behavior.
7. Verify error classification.
8. Run doctor.
9. Switch AI only.
10. Retain previous configuration for rollback.

### 23.5 Replacement PDF reader/OCR

1. Build custom reader.
2. Test text PDF.
3. Test scan.
4. Test owner-locked PDF.
5. Test large/multi-page file.
6. Test page/order limits.
7. Compare extracted text.
8. Run doctor.
9. Switch reader only.

### 23.6 Replacement converter

1. Select converter.
2. Test real MSAPO template.
3. Compare page count/layout/fonts/tables.
4. Verify PDF signature.
5. Test concurrent conversions.
6. Test timeout/failure.
7. Run doctor.
8. Switch converter only.

### 23.7 Replacement host

1. Configure host/port.
2. Configure template path.
3. Configure ephemeral work/output.
4. Configure durable data or managed stores.
5. Install core/default/custom dependencies.
6. Run doctor.
7. Start service.
8. Test full quote/email flow.
9. Restart and verify persistence.
10. Test iPad/desktop access.
11. Configure SSO/access.
12. Cut over with rollback.

---

## 24. Immediate next actions

1. Decide whether PR #25 should remain draft until the final Smartsheet exists or be merged as disabled scaffolding after review.
2. Obtain final ENFRA PO form and sheet ownership details.
3. Resolve authentication strategy.
4. Verify Render URL reachability and disk state.
5. Confirm template legal applicability.
6. Prepare a redacted regression fixture set.
7. Test the current production flow on real iPad Safari and all relevant email clients.
8. Add search/typeahead for very large generic asset sets.
9. Define multi-asset and amendment rules.
10. Establish data refresh ownership for contracts/assets/cost codes.

---

## 25. Unanswered questions requiring Evan or ENFRA

1. Does Smartsheet replace email or supplement it?
2. Who owns the final form and destination sheet?
3. What is the go-live date?
4. Can the form accept multiple attachments?
5. Does URL prefilling work on the final form?
6. Is API access approved?
7. Can a dedicated service account be created?
8. What fields/options are required?
9. Should a changed submission update or amend?
10. Can one PO include multiple assets?
11. Who owns asset and cost-code source data?
12. What is the approved data-retention policy?
13. Is the current MSAPO legally valid for every contract?
14. Is the Render service public?
15. Should PR #18 be used, or should work move directly to SSO?
16. Is `/test1` mounted, healthy, and backed up?
17. Are multiple application instances anticipated?
18. Which AI provider is approved long term?
19. Which PDF/OCR/conversion tools are approved?
20. Should the repository/product be renamed?

---

## 26. Exact current state — RAG summary

| Area | Status | Notes |
|---|---|---|
| Core quote-to-email flow | Green | In production code. |
| RRH routing/cost codes/assets | Green | Most exercised; preserve parity. |
| Generic contracts | Yellow | Functional; large dropdowns and data governance remain. |
| OCR/text/image formats | Green/Yellow | Strong current support; large real files need broader fixtures. |
| AI response validation | Green | Merged. |
| Document freshness | Green | Merged fingerprint protection. |
| Generated-file collision | Green | Unique files and cleanup merged. |
| Outlook Web `.eml` | Green | Base64 fix merged. |
| Apple Mail / real Safari | Yellow | Implemented; real-device coverage incomplete. |
| Per-contract learning | Yellow | Works; no management UI; disk state unverified. |
| Authentication | Red | None merged; PR #18 only. |
| Template legal applicability | Red/Unknown | Text audit only. |
| Automated tests/CI | Green | Present and expanded. |
| Smartsheet manual route | Yellow | Implemented in draft; final form unavailable. |
| Smartsheet URL route | Yellow | Implemented in draft; untested final labels. |
| Smartsheet API route | Yellow/Red | Robust draft; no live sheet/token test. |
| Smartsheet idempotency | Green internally / Yellow externally | Strong tested design; durable host not verified. |
| Portability adapters | Green internally / Yellow externally | Contract-tested; replacement systems not available. |
| Host portability | Yellow | Runtime/entrypoint prepared; no alternate-host acceptance. |
| Persistent disk/backups | Unknown | Dashboard access required. |
| Multi-instance scaling | Red | Requires managed/shared storage. |
| Observability | Red | No centralized monitoring. |

---

## 27. Golden non-regression rules

1. Never gate standard MSAPO generation by contract.
2. Never regress RRH while improving generic contracts.
3. Never surface learned data across contracts.
4. Never select an asset only because it is first.
5. Never replace the original quote bytes with analysis-normalized bytes.
6. Never send/submit a stale MSAPO.
7. Never silently default unknown routing to RRH.
8. Never use fuzzy Smartsheet mapping for live writes.
9. Never blindly retry an ambiguous row creation.
10. Never use temporary/in-memory idempotency for live API mode.
11. Never let a form correction diverge from the attached document.
12. Never let an infrastructure adapter own business rules.
13. Never switch multiple infrastructure concerns at once.
14. Never merge a fail-closed access gate before configuring its secret.
15. Never claim a draft or mock-tested integration is production ready.

---

## 28. Compact successor prompt

> You are taking over **Email Process Control** in the private repository `evanroden/msapo-generator`.
>
> `main` contains the current production quote-to-email workflow and the merged correctness, legacy-cleanup, image-normalization, and AI-response-validation work. Draft PR #25 (`agent/smartsheet-three-mode`) adds a disabled-by-default, fail-closed three-route Smartsheet handoff: manual copy/paste, exact-label URL prefill, and explicit-schema API submission. Draft PR #26 (`agent/portable-runtime-adapters`) is stacked on PR #25 and adds replaceable AI, PDF-reader/OCR, PDF-converter, memory, submission-store, runtime-path, host, port, packaging, and deployment-diagnostic interfaces. Draft PR #18 is a separate interim shared-password gate and must not merge until its secret is configured; SSO is preferable.
>
> The product turns a vendor quote into a reviewed PO package. Standard MSAPO documents are generated for **all contracts**. Equipment-only POs skip the MSAPO. RRH has dedicated routing/cost-code/asset behavior. Generic contracts come from `contracts.json`. Data learning is strictly contract isolated. No asset is safer than a guessed asset. Unknown routing requires confirmation. The original quote bytes must remain unchanged. Generated documents must match the current analysis, contract, site, inclusions, and exclusions.
>
> Do not revive PR #10’s RRH-only document gating. Do not revive PR #15’s fuzzy Smartsheet column mapping. Do not blindly retry ambiguous API row creation. Do not use an in-memory idempotency fallback. Do not let replacement infrastructure alter business rules.
>
> Before changing code, read:
>
> 1. `docs/PROJECT_HANDOFF_DOSSIER_2026-07-29.md`
> 2. `docs/NEXT_LLM_SMARTSHEET_AND_PORTABILITY_HANDOFF.md`
> 3. `docs/FAILURE_MODES_AND_CONTROLS.md`
> 4. `docs/PORTABILITY.md`
> 5. current PR #25 and PR #26 metadata/diffs
>
> Verify GitHub state because the branches may have moved. Distinguish production `main`, prepared draft code, and external blockers. Run the full tests, then run `python -m app.doctor` in the exact target environment. Treat the final Smartsheet form, live sheet, credentials, authentication, template legal approval, real-device testing, and replacement-provider approval as external requirements—not assumptions.

---

## Appendix A — essential reading order

1. This dossier.
2. Current README on the branch being changed.
3. `docs/FAILURE_MODES_AND_CONTROLS.md`.
4. `docs/PORTABILITY.md`.
5. `docs/NEXT_LLM_SMARTSHEET_AND_PORTABILITY_HANDOFF.md`.
6. PR #25 body and diff.
7. PR #26 body and diff.
8. Current tests.
9. Current `web_ui.py` state model.
10. Current deployment configuration and external dashboard values.

## Appendix B — first-day checklist for the next LLM

- [ ] Confirm current `main` head.
- [ ] Confirm PR #25 head/base/draft/CI state.
- [ ] Confirm PR #26 head/base/draft/CI state.
- [ ] Confirm whether PR #18 is still wanted.
- [ ] Read the four handoff/reliability/portability documents.
- [ ] Inspect changed files rather than relying only on PR descriptions.
- [ ] Run pytest.
- [ ] Run doctor with current configuration.
- [ ] Do not enable any Smartsheet route.
- [ ] Do not merge a fail-closed auth gate without its secret.
- [ ] Ask which external input is now available: form, sheet, token, host, AI, PDF tool, converter, SSO, or template approval.
- [ ] Change one concern at a time.
- [ ] Keep rollback configuration.
- [ ] Report clearly what is merged, what is draft, what is tested, and what is still unknown.
