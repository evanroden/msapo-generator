# A21 — PO / Expense guardrails across Monthly runtime changes

Refs #270 and #941. This records the **current-main** control paths checked on
2026-11-17, starting at `f0af99567223aea3375f60e671450048be2bf0a0`.
It is a code/isolated-synthetic check, **not** a served browser, private source,
Smartsheet submission or Azure/Render acceptance record.

## First-click paths and existing reuse

| Workflow and first action | Input / cache identity | First user-visible effect | Explicit final action |
| --- | --- | --- | --- |
| PO: select Purchase order; Upload quote or Paste text | Upload source bytes retained in `uploaded_file_bytes`; OCR success/failure pinned by `extract_hash` / `extraction_error_hash` (SHA-256 content). Analyzer success/error pinned by `last_sig` / `analysis_error_signature` (SHA-256 of exact selected text). | Quote extracted/analyzed; review scope, route, contract/site, asset, contact, amount and tax. Route/site choices are session-scoped and correctable. | One `Generate both files and Smartsheet link` action. |
| PO: asset, vendor and site corrections | `po_draft` mirrors primitive widget values keyed to `analysis_token`; `po_context` verifies the quote source and rerenders context identity from reviewed fields and attachments. Device memory is distinct from report state. | Verified asset options filtered by contract/site; vendor/contact proposals remain editable; required missing items block generation. | No external row or email write. |
| PO: complete request | `scope_pdf_signature` pins generated PDF to the document scope; `context_id` namespaces download controls and handoff progress. Configuration is loaded each rerun, not cached across deployments. | Download unchanged original quote and generated MSAPO form PDF; open **prefilled** Smartsheet form in a new tab with exact configured labels. If prefilling skips fields, show an explicit warning/manual-copy fallback. | Operator must upload both files and submit in Smartsheet; checked-in `SMARTSHEET_API_MODE=disabled`. |
| Expense: select Expense reimbursement; upload receipts | Bounded immutable byte mirror `expense_receipt_files`; content SHA-256 identifies each receipt, irrespective of filename; `ContentDigests` is retained only in `st.session_state`, capped at 64 MiB / 128 entries. Receipt reading is asynchronous and session-associated. | Review original receipt photos/PDF pages, OCR-prefilled merchant/date/amount, and manually correct/split lines; duplicates reported and de-duplicated by content. Mileage-only reports require no receipt. | Explicit report generation, never automatic email sending. |
| Expense: review report and generate | Account-specific keys use SHA-256(account)[:10]; `expense_draft_snapshot` mirrors scalar user inputs but excludes uploaded bytes, active reader jobs, package bytes, removed-receipt flags and transient errors. | Review employee, approver, job allocation, amounts and receipt pages. The original receipts remain unchanged. | Explicit `Generate` creates JDE workbook, PDF receipt packet when renderer available, and an approval **draft**; the operator sends it. |

The root `app/web_ui.py::main` is the only workflow selector and purchase
entrypoint. `pages/2_Smartsheet_PO.py` is a bookmark compatibility notice only.
The exact-label and source-count assertions in
`tests/test_smartsheet_handoff_entrypoint.py` must not be relaxed.

## Shared runtime risk and caching decision

Existing PO OCR and quote analysis already reuse results across ordinary
Streamlit reruns **only** for the selected source content. Expense already uses
the session-owned bounded digest cache and per-receipt analysis state. Caching
parsed PDFs, AI results, vendor/contract/contact choices, or widget hydration in
a process-global `st.cache_data` / `st.cache_resource` would risk reusing
private business values across sessions or sites. No process-global cache or
infrastructure-scale increase was introduced.

A future cache optimization requires an actual cold/warm profile and must
include, at minimum: full source digest, operation/version, chosen contract and
site, and explicit session/owner scoping; errors and canceled jobs must never
be reused as successful analyses. Keep originals immutable and never cache a
Smartsheet POST. Existing profile evidence is not sufficient to claim a
user-visible improvement in A21; there is **no A21 latency or memory win claim**.

## Deterministic acceptance controls

`tests/test_po_expense_shared_runtime_guardrails.py` adds a joined synthetic
AppTest: start with a synthetic quote, explicitly generate two files (including
a real locally generated one-page PDF), check original-byte SHA-256, check
the site/vendor/contact/asset values in the exact-label prefilled URL, enter an
Expense name, navigate back to PO, then return to Expense. It asserts retained
bytes/output/field values and no unintended regeneration. The isolated PO
fixture forbids network requests, quote/receipt readers and Smartsheet API
submission; it uses a temporary data directory and checks an outside sentinel.

A separate deterministic test uses **two independent session-state mappings**
with identical receipt bytes and different reviewed names and filenames,
checking duplicate handling, independent content-digest cache instances and
the absence of receipt bytes in the scalar draft mirror. A negative test
replaces original quote bytes without updating their fingerprint and verifies
the package fails closed. It also confirms that an unmapped required contact
cannot be described as prefilled.

The repository's existing `.github/workflows/tests.yml` already runs the full
test suite on **every main push**, including cross-cutting Monthly/runtime
merges, and runs PR affected/full checks. This guardrail enters that existing
suite without adding a separate runner, workflow or hosting expense. Core
nearby suites include `test_smartsheet_handoff_entrypoint.py`,
`test_po_context.py`, `test_po_rules.py`, `test_smartsheet_config.py`,
`test_smartsheet_integration_fake.py`, `test_expense_draft_state.py`,
`test_expense_workspace_isolation.py` and
`test_workflow_return_preservation.py`.

**Evidence levels:** these tests establish isolated functional behavior and a
synthetic PDF page, not a real vendor quote, actual receipt OCR, a native mobile
download, a Smartsheet submission, or served first-paint timing. Full suite
and container/resource checks must be reported for the actual PR head.
