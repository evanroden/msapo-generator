# MSAPO external integrations — Azure App Service preparation

**Status: PREPARATION / NO LIVE SUBMISSIONS.** Source main SHA: 57c5cd87e3e441dfea3cddbc666248f8e469d986 (2026-11-11). Reference: A01's draft migration manifest, PR #849. The enterprise destination, real URLs, service accounts and named approvers are not available in this public repository; do not invent them, print their values, or treat this document as infrastructure/provisioning authorization.

## Existing behavior to preserve

- **PO browser form:** app/smartsheet_inline.py shows two downloads: the original vendor quote and the completed MSAPO PDF. The user opens a HTTPS Smartsheet form with exact-label URL-prefilled values, uploads both files and manually submits. Opening the link neither attaches a file nor submits a row. Manual URL, prefill and direct API are independent routes. Checked-in render.yaml sets SMARTSHEET_API_MODE=disabled, SMARTSHEET_URL_PREFILL_ENABLED=true and SMARTSHEET_ALLOW_CUSTOM_API_BASE=false. Render dashboard overrides are unverified, and Azure must not silently activate the REST API.
- **Direct REST API (inactive):** app/smartsheet.py permits disabled, dry_run, live; live pins the API host to api.smartsheet.com and requires an exact sheet, typed column IDs/title/type/options, required-field set and a dedicated submission_key column. GET uses three bounded attempts on 429/5xx/transport failures; POST creates and attachments are not retried blindly. Requests use a 60-second timeout and attachment preflight permits at most 30 MiB per file. A lost row response is uncertain and requires exact submission-key reconciliation, never a fuzzy search hit. Remote 64-bit row IDs remain strings.
- **Submission persistence:** app/smartsheet_store.py maintains submission fingerprints, lease ownership, original row ID and attachment fingerprints in smartsheet_submissions.db beneath EPC_DATA_DIR. Preserve this store, including failed, complete, partial, creating and uncertain statuses, atomically with migration; an empty replacement database or a rollback snapshot could create duplicate purchase orders. The existing 365-day pruning of complete/failed rows is not permanent external uniqueness. P03/P09 persistence owner must prove restore/reopen, shared-worker locking, recovery and retention; a mounted path alone is insufficient.
- **Expense:** app/config.py maps the selected contract/account to its approved director via EXPENSE_ACCOUNT_DIRECTORS_JSON; expense_ui.py addresses the unsent approval email To the director and Cc to the filer's manager, suppressing self/duplicate Cc. Do not restore the obsolete administrator route or trust remembered browser recipients as authorization. The combined PDF is the only email attachment. The editable XLSX remains a separate download; do not attach it. Outlook desktop/web download the RFC 2822 .eml with X-Unsent: 1. The same-origin iPhone/iPad component uses Web Share (navigator.canShare and navigator.share) with user activation; To is copied/displayed and Cc is displayed for manual completion. mailto: is attachment-free. The app neither sends an email nor posts to JDE. PDF attachments above 18 MiB raw trigger a warning rather than silent replacement.
- **PDF:** local LibreOffice is the deployed renderer. Optional GOTENBERG_URL in pdf_converter.py and expense_report.py is only used if PDF_BACKEND=gotenberg. Do not enable this network conversion or introduce a fallback during migration. Its current 120-second conversion budget and XLSX-only recovery must remain.

## Configuration inventory

D = development, S = staging, P = production. Each destination must be approved independently for S/P. Secret = credential, restricted = sensitive destination/recipients/mapping, nonsecret = operational toggle. Settings contain no actual values here.

| Setting | Purpose | Environment | Accountable owner | Classification |
|---|---|---|---|---|
| SMARTSHEET_FORM_URL | Browser HTTPS form, exact form ID | S/P, synthetic D | Purchasing / form owner | Restricted |
| SMARTSHEET_URL_PREFILL_ENABLED | Enables URL data fill when verified map exists | D/S/P | Purchasing | Nonsecret |
| SMARTSHEET_FORM_FIELD_MAP_JSON | Logical field to exact visible form label | S/P | Form owner | Restricted |
| SMARTSHEET_FORM_VALUE_MAP_JSON | Optional display-dropdown value translation | S/P | Form owner | Restricted |
| SMARTSHEET_FORM_ORDER | Ordered form fields | D/S/P | PO product | Nonsecret |
| SMARTSHEET_FORM_REQUIRED_FIELDS | Required browser-form fields | S/P | Form owner | Restricted |
| SMARTSHEET_PREFILL_MAX_URL_LENGTH | URL budget; 7000 checked-in | D/S/P | PO product | Nonsecret |
| SMARTSHEET_API_MODE | disabled / dry_run / separately approved live | D/S/P | Purchasing + security | Nonsecret, critical |
| SMARTSHEET_API_TOKEN | Optional bearer credential, unused if disabled | Approved API only | Secret custodian | Secret |
| SMARTSHEET_SHEET_ID | Exact API destination, not the form ID | Approved API only | Sheet owner | Restricted |
| SMARTSHEET_COLUMN_SPECS_JSON | Exact column IDs, names/types/options, submission_key | Approved API only | Sheet owner | Restricted |
| SMARTSHEET_REQUIRED_FIELDS | Required API fields, distinct from form requirements | Approved API only | Sheet owner | Restricted |
| SMARTSHEET_ROW_POSITION | Row top/bottom selection | D/S/P | Purchasing | Nonsecret |
| SMARTSHEET_API_BASE_URL | HTTPS pinned official API or isolated fake | D/S/P | Security/network | Nonsecret/restricted fake |
| SMARTSHEET_ALLOW_CUSTOM_API_BASE | False in production; only nonlive fake | D/S/P | Security/QA | Nonsecret, critical |
| EXPENSE_ACCOUNT_DIRECTORS_JSON | Contract to director name/email, current routing authority | S/P, synthetic D | Expense owner + IAM | Restricted PII |
| PDF_BACKEND | Retain libreoffice | D/S/P | App/platform | Nonsecret |
| GOTENBERG_URL | Unused optional network conversion endpoint | Only if later approved | Platform/security | Restricted |
| EPC_DATA_DIR | Includes submission DB and original sources | S/P | Persistence A03/A09 | Restricted |
| EPC_SQLITE_JOURNAL_MODE | Optional SQLite journal override; not a safety proof | D/S/P | DBA | Nonsecret |
| ANTHROPIC_API_KEY | Existing OCR/model service credential | Separately approved S/P | AI governance | Secret |
| ANTHROPIC_MODEL | Existing model, not an Azure model substitution | D/S/P | AI governance | Nonsecret |
| EPC_API_TIMEOUT_SECONDS, EPC_ANALYSIS_BUDGET_SECONDS | Existing bounded AI attempt budget | D/S/P | AI/app | Nonsecret |
| APP_GIT_COMMIT, PUBLIC_SITE_ORIGIN | Build stamp / approved authenticated browser origin | Build and env | CI/platform | Nonsecret/restricted origin |
| HTTPS_PROXY, HTTP_PROXY, NO_PROXY | Optional corporate outbound proxy/bypass | Per env if needed | Network/security | Restricted |
| REQUESTS_CA_BUNDLE, SSL_CERT_FILE | Optional approved CA trust-bundle paths | Per env if needed | Platform/security | Restricted |
| RRH_APPROVER_NAME, RRH_APPROVER_EMAIL | Retired and ignored; remove stale settings | None | Expense owner | Obsolete |

**No real names, addresses, IDs or keys belong in templates.** The supplied env and Azure appsettings templates intentionally leave Smartsheet form/mapping unconfigured and API mode disabled; they are not drop-in production settings. For production, preserve the *approved effective* existing form and labels rather than letting blank template values wipe working configuration. Read current Render dashboard values through a restricted procedure, never through CI logs or the public repository.

## Outbound dependency matrix

| Caller / traffic | Destination, direction and policy | Payload / failure behavior |
|---|---|---|
| Server: quote/receipt/Monthly OCR and model SDK | Anthropic API over HTTPS, normally api.anthropic.com:443; **provider approval remains separate** | Quote text, image/PDF receipts and report text; existing API key/model, bounded retry policy, no silent provider switch. Validate exact SDK region/endpoints and retention with AI governance. |
| Browser: PO link | app.smartsheet.com HTTPS and the actual approved form/SSO redirects; **browser egress, not App Service egress** | URL prefill may carry sensitive PO fields. Required missing values or URL overflow withholds link. Opening is not a submission. |
| Server: Smartsheet REST, currently disabled | api.smartsheet.com:443, HTTPS /2.0; official live token must never be redirected to custom test hosts | Typed cells, original quote/PDF and exact submission key. 60s HTTP timeout; GET bounded retries, never automatically replay POST. Ambiguous failures block, require reconciliation. |
| Server: PDF renderer | Local LibreOffice, **no external host** | XLSX/Word and receipts with 120s conversion limit; expense retains XLSX on error. |
| Optional server renderer, inactive | GOTENBERG_URL /forms/libreoffice/convert (default localhost:3000), only when separately approved | Full document is sent to converter; never enable automatically. |
| Browser: Outlook desktop/web | Same-origin .eml download; Outlook user imports and manually sends via their enterprise mail client | Unsent message and PDF only, no server-to-server mail. |
| Browser: iOS Mail/Outlook | Same-origin Streamlit component + OS Web Share, with user gesture and files permission | PDF file + body; show To/Cc and require employee confirmation. No server-side email. |
| Browser: fallback | mailto: URL | Subject/body and recipients only; attachment-free. |
| App Service platform | ACR pull, Key Vault, approved DB/object store and Streamlit same-origin WebSocket/downloads | Managed identity/service connectivity defined by platform and persistence owners; no invented service FQDNs. |
| JDE / SMTP / Microsoft Graph | **No active write destination** | Not part of this migration. |

**Network approval record:** For each actual external dependency record FQDN:port, direction (Azure server vs corporate browser), environment, DNS/private-zone and resolver, VNet egress and route, HTTPS proxy credentials policy, NO_PROXY exceptions, custom root-CA installation/trust, TLS interception decision, token audience/identity, owner and permission expiry. Verify CA handling for requests and httpx/Anthropic SDK, proxy/WAF timeouts longer than required work, DNS resolution, WebSocket upgrades, 512 MiB upload proxy limits, streaming downloads and session reconnect. No credential or prefill URL may be logged. Smartsheet POST 429/5xx/timeouts may occur **after** the remote row exists; never treat them as safe resend signals. For iOS Web Share HTTPS and web-share permissions policy must allow the same-origin component, and share() must be called with transient user activation.

## Key Vault and environment-specific configuration

- Development: synthetic files/recipients, no real Smartsheet destination or token, API disabled or isolated fake dry_run, no customer data.
- Staging: independent, explicitly approved **test form** and exact labels. A dedicated scratch API sheet and least-privilege token are OPTIONAL and require a separate API test authorization; normal application remains disabled. Never copy production data into staging.
- Production: approved form ID and exact labels from current workflow, director map per contract, direct API disabled unless a later distinct release authorizes live. Preserve the manually reviewed/sent email and attachment behavior.
- For credentials and sensitive directory/form configuration use distinct per-environment Azure Key Vault secrets with App Service Key Vault reference syntax and managed-identity least privilege. Keep values, target IDs, directors and rotation evidence in restricted ENFRA records. App settings and deployment exports must not appear in public workflow logs.
- Rotation: confirm owner and approved scope; issue replacement provider token; test nonwriting readiness in isolated staging; create new Key Vault version and refresh the App Service reference; prove runtime sees replacement without outputting it; revoke old token after an approved overlap. For directory changes validate account aliases/To/Cc and policy before activation. **Do not retry creating/uncertain PO submissions as a side effect of rotation.**
- Persistence: freeze external writes and snapshot both application and submission state at the same business cutover point; preserve leases, remote IDs and attachment hashes. Restore to isolated store, reopen twice, compare counts/checksums and prove an already submitted payload is not treated as new. Fail closed if storage semantics are unverified. A03/A09 own the store adapter and restore acceptance.

## Focused repairs, current PR heads and tests

- **#847** (head 27cd1fab30bcb27218d0932eeb91ff3445c0e536): pending fix to persist a durable 'creating' intent before non-idempotent row POST, blocking a second create after crash/lease expiry. Source main still has this defect. Do not manually duplicate the repair; P20 must integrate.
- **#830** (head 6e34b26b8e8e87d8fd22f5f5033928db6869f57a): fake two-attachment partial retry across store reopen, exact-key reconciliation and 64-bit row IDs.
- **#841** (head 0f2bb37e14d0281410c8d1f924b0ab0ae927d0b9): original-upload quote byte/hash proof and blocking reupload/switch-to-paste remedy when stale.
- Existing tests: tests/test_smartsheet_config.py, tests/test_smartsheet_api.py, tests/test_po_context.py, tests/test_expense_report.py and tests/test_web_ui_app.py. These PRs are open/draft and **not on main**, therefore do not claim their tests are already in a released build. Recheck heads/comments/checks with P20 before merge.
- This branch adds a **read-only migration safety checker**, no network/SMTP/Graph/client submissions. Local focused test command: python -m pytest -q tests/test_azure_external_integrations_check.py. Eight synthetic tests passed locally (2026-11-11); CI at the branch head and joined repair PRs are distinct pending evidence. Test cases: disabled/dry_run, live fail-closed, fake API base not live, unsafe form domain, missing labels, director map, no network renderer/mail, redacted output, duplicate appsettings and production missing form. The checker rejects live activation during preparation by design.

**After P20 joins repairs, rerun focused provider fakes**: (1) disabled/dry_run and POST count zero; (2) exact typed cells/one row ID; (3) first attachment succeeds, second fails, store reopen resumes only missing attachment; (4) network loss after POST and exact-key reconciliation (fuzzy match rejected); (5) crash during row creation, expired lease and zero duplicate creates; (6) corrupt/missing/readonly store fails closed; (7) byte-identical original uploaded quote and stale upload blocked; (8) director To/Cc, PDF-only EML, no SMTP/Graph; (9) PDF connection/timeout saves XLSX, prevents empty-attachment draft; (10) managed desktop, Outlook Web and physical iOS/Web Share/Entra sessions, two tabs and mobile downloads. Run all required release checks at the immutable integrated SHA, not the preparation baseline.

## Real acceptance — deferred, no submissions now

**Smartsheet form:** test destination must be supplied in restricted record: ENFRA-approved staging form URL, exact account/form owner, test organization/SSO account, exact required choices, receiver and cleanup authorization. Do not use a production form. Fictitious logical sample: request_type=PO, requester_name=Synthetic Tester, job_number=TEST-ONLY, site_location=TEST-SITE, vendor=Example Vendor, total=1.00, object_account=5511-SUBCONTRACTOR, agreement_type=03 - MSAPO (SERVICE), description_of_work=Azure handoff acceptance only, plus test-approved required values. Pair synthetic-quote.pdf and synthetic-msapo.pdf with known SHA-256. Observe values after prefill **without** submitting during preparation. After separate approval, expected side effect is exactly one **test-only** form record with two exact attachments. Reconcile and document receiver record ID/checksums; remove the scratch record only if approved, otherwise mark and expire it. These invented example values are not guaranteed to satisfy a real form until its schema is approved.

**Smartsheet API, only if separately authorized later:** restricted test destination must provide the approved scratch sheet ID, exact column specs including submission_key, test token owner/scope and controlled acceptance window. Example HTTP shape is one strict-typed-cell row to POST /2.0/sheets/{scratch_id}/rows, and two multipart POSTs to /rows/{returned_row_id}/attachments. The submission_key is the application's deterministic SHA-256 of normalized fields and original filename/byte hashes; never invent a numeric ID for an actual sheet. Expected side effects: exactly one scratch row with matching key, two attachments and zero duplicates after restore/retry. For uncertain outcomes do read-only exact-key verification first; a search miss is **not** retry permission. Record minimal redacted row/checksum evidence and approved scratch-row cleanup. Main migration runtime stays disabled.

**Expense/browser:** separately approved synthetic director and manager identities for staging; generate PDF, XLSX and unsent .eml, verify exact To/Cc, PDF checksum, absence of XLSX from attachment, no email sent. Validate Outlook desktop open, Outlook Web reading-pane .eml import, corporate Edge/Chrome attachment download policy, same-origin web-share component and iPhone/iPad Mail/Outlook, Entra reauthentication and WebSocket reconnect. A real email test needs distinct approval and a designated test-only mailbox; no such email is part of this preparation.

**A10 acceptance evidence bundle:** final source SHA + image digest, redacted setting names and FQDN policies, approved exact test destination IDs in restricted record, synthetic payload/file hashes, fake provider call counts, before/after/reopened store and remote exact-key proof, downloaded PDF/.eml hashes and recipients, physical device record, no business submissions and scratch-record cleanup status.

**Ownership note:** The user calls identity A05 and persistence A03/A09; A01's **proposed, unassigned** mapping calls identity A04 and storage A05. Resolve numbering with the migration coordinator; route by IAM, DBA/storage and QA function until formally assigned. P20 owns functional repair integration and A10 owns authenticated acceptance. This PR contains no runtime product, storage, authentication or deployment changes.
