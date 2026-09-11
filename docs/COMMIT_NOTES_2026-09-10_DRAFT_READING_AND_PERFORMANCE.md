---
document_type: implementation_handoff
base_commit: 226b12ed17d5381ec584d53b47c98a50b6775d0e
date: 2026-09-10
follow_up_date: 2026-09-11
status: prepared_for_authorized_publication
---

# Draft preservation, complete document reading, and interactive performance

## Scope and authority

Implements the six findings and four performance opportunities from the September
10 review, plus two correctness fixes confirmed during the September 11 follow-up.
The owner authorized the additional test/improvement pass and committing and
pushing the tested changes to `main` for internal testing. This is the pre-push
engineering handoff; final commit and CI evidence accompany the publication result.
Authentication and public-request rate limiting remain explicitly out of scope.

Purchase classification, catalog choices, financial formulas, original attachment
bytes, the official document templates, and human approval/submission requirements
remain unchanged. The existing database migration is reused, not replaced.

## Findings to changes

| Finding | Root cause | Implemented control |
|---|---|---|
| PO edits/source lost on workflow switching | Widget cleanup removed values; initialization restored analyzer defaults or cleared the active quote | Active-quote scalar input mirror, source-mode/text restoration, retained-upload availability flag and explicit removal control |
| Scanned quote pages omitted behind a native cover | Document-wide 20-character shortcut | Page-level assessment, ordered OCR of contiguous scan runs, refusal when those pages remain unreadable |
| TIFF receipt pages omitted | First-page preview reused as the analysis payload | Validate/normalize every frame; enforce the combined vision payload budget |
| Clearing mileage date crashed | Formatting `None` as a date | Separate missing-date validation, continued editable form; report-date clearing is also guarded |
| Oversized receipt batch required a full reset | Budget return preceded individual removal controls | Lightweight filename/size/removal controls remain available above that return |
| Model failures caused nine HTTP attempts and terminal sleep | Three application attempts multiplied by SDK retries | Disable SDK retries, share bounded retry policy, no last-attempt sleep, close clients after use |
| Incomplete model output accepted as a complete reading | Only response text was checked; valid partial JSON/OCR could pass | Require a normal completion signal before consuming any text; reject token-limit, refusal, and other incomplete responses without another transport/modality attempt |
| Entertainment suggestion never reached the expense selector | The initial Miscellaneous value made the section appear already answered | Apply the suggestion once to the untouched default; an explicit operator-choice flag survives pending jobs and workflow switching |

## Durable PO draft

`workflow_state.preserve_po_draft` runs before the workflow branch. It records only
scalar inputs belonging to the active analysis token, plus the source mode and
pasted quote. `restore_po_draft` runs before PO widgets and uses `setdefault`, so
a deliberate live blank or correction wins over the snapshot.

The existing explicit Object Account/Agreement Type override mirror remains in
charge of those selectors. The new mirror supplements it; it does not reintroduce
value-comparison inference for operator intent.

File-uploader widgets cannot be programmatically restored. A retained source uses
the existing original bytes and extraction cache when `po_upload_available` is
true. Uploader change callbacks distinguish an explicit user removal from a widget
that disappeared because Expense was selected. The retained-source UI provides its
own removal button. Choosing a different source mode remains explicit.

This is session durability, not persistent draft storage across a server restart
or a fresh browser session. Receipt bytes and PO source bytes are not newly written
to the account-memory database.

## Background receipt state machine

Only content preparation runs on the Streamlit thread. Image/PDF decoding,
dimension/page-count checks, and normalization are never run by network workers.
`receipt_jobs.start_receipt` acquires capacity before preparation and submits only
the network/response-normalization phase.

| State/event | Behavior |
|---|---|
| New receipt, capacity available | Prepare locally; start a network job; render editable blank/prefilled fields |
| Both global slots occupied | Leave the receipt queued in its existing session record; do not add executor backlog |
| Job running | One-second fragment polling; users can edit the form or stop automatic reading |
| Job completes | Publish on the UI thread only if the receipt is still active; fill unedited blanks |
| Job fails | Store a sticky per-receipt error and retain manual-entry fields and explicit retry |
| User stops/removes/resets | Cancel where possible, drop the pending reference, and never publish late results |
| Pending job exceeds the UI budget | Discard its eventual result and permit manual completion |

Two process-wide network slots bound actual concurrency; there is no unbounded
executor queue. The pool never accesses `st.session_state`. An already-running
HTTP request cannot be forcibly cancelled by `Future.cancel()`; its HTTP timeout
still applies, it releases capacity on completion, and its discarded result cannot
restore a removed receipt or overwrite a new report.

Manual merchant, purpose and amount values entered while reading is pending are
covered by AppTest. Itemized receipt results do not overwrite an unrelated manual
amount on first arrival. UI tests that exercise completed receipt rendering now
use deterministic completed futures; dedicated tests cover pending and concurrent
jobs, stopping, and late-result rejection.

The section selector separately records explicit edits. A late Entertainment
suggestion can replace the untouched Miscellaneous default and expose its required
contact field. Selecting another section and returning to Miscellaneous remains an
explicit choice, including across Expense → PO → Expense. Additional split lines
retain their independent, editable section choices.

## Retry and extraction policy

`api_retry.py` owns retry scheduling. Clients explicitly set `max_retries=0`.
Connection errors, HTTP 429, and server errors are retried up to three transport
attempts, with 3- and 6-second backoffs. There is no sleep after the last attempt.
Both malformed-response attempts share the same operation deadline.

| Setting | Default | Accepted range |
|---|---|---|
| `EPC_API_TIMEOUT_SECONDS` | 60 seconds | 10–120 seconds |
| `EPC_ANALYSIS_BUDGET_SECONDS` | 120 seconds | 30–300 seconds |

Invalid/non-finite/out-of-range configuration falls back to the defaults. The
request timeout cannot exceed the operation budget. The remaining deadline bounds
each new attempt's timeout; connection timeout is at most five seconds.

These are HTTP phase timeouts and a retry-scheduling budget, not a promise of hard
process interruption at an exact wall-clock instant. The UI additionally abandons
over-budget pending receipt jobs when polled. Defaults allow longer quote output
than a very short timeout while eliminating the old 600-second client default.

For PDFs, native pages remain local and free. Pages with a large raster covering
at least half the page, or insufficient native text plus image/vector content, go
through OCR. Contiguous scanned runs are grouped to avoid one request per page.
Results are joined in original document order. Image-rich native pages may be
OCR'd conservatively; the coverage heuristic is not a mathematical guarantee of
document completeness. Original quote attachments are unchanged.

Document-to-image OCR fallback is limited to representation/size failures. It does
not repeat authentication, rate-limit, or outage failures as a second modality.
Blank OCR output cannot be hidden behind native cover-page text.

All three model consumers also check the response completion signal. A response
ending at the output-token limit can contain plausible OCR or even valid JSON, so
successful parsing alone cannot prove it describes the complete source. Only a
normal end-of-turn or configured stop-sequence completion is accepted. Other
completion reasons and empty text raise `IncompleteResponseError`; this is not a
representation failure and cannot trigger PDF-to-image fallback. Mock HTTP tests
cover complete, token-limited and refusal responses for quote, receipt and OCR
paths and assert one request for each. This intentionally exposes an incomplete
reading instead of silently analyzing or submitting a partial document.

## Performance and invalidation

### Immutable content identities

`ContentDigests` is session-owned and bounded to 64 MiB/128 entries. Cache entries
retain the exact immutable byte object, not just its Python ID; this prevents ID
reuse from returning another file's digest. Mutable inputs are never cached.
Inactive byte objects are pruned. No digest cache is shared across users.

Upload comparisons, duplicate detection, UI validation, and expense signatures use
the same digest cache. Backend workbook validation still independently hashes its
input by default. No caller-supplied digest is accepted as proof of file content.

Local microbenchmark: seven runs over an unchanged 60 MiB set measured approximately
225.9 ms median for the prior equivalent repeated digest work and 0.011 ms for the
warm cached upload pipeline. This isolates upload bookkeeping, not whole-page or
production latency. Cold/new uploads still must be hashed and decoded.

### Document reuse

PO generation reuses `scope_pdf_bytes` only when `scope_pdf_signature` equals the
current document signature. Changing requester/handoff-only fields refreshes the
context/link without another LibreOffice invocation. Vendor, scope, facility,
inclusion/exclusion, or other signature-bearing changes still regenerate. Tests
assert both reuse and rebuild cases; the stale-download gate remains intact.

### Database initialization

Each database gets initialization/migration checks once per process, path, file
device/inode, and SQLite schema version. A bounded registry plus lock prevents
repeated DDL on ordinary lookups. External DDL or database replacement invalidates
the record. Failed initialization is not cached as success. SQLite connections are
still short-lived and never shared across threads. Existing migration and
account-isolation tests remain applicable.

## Verification and deployment boundary

Regression coverage is in `tests/test_review_remediation_2026_09_10.py`, with
existing analyzer/UI mocks updated for the new network-phase boundary. The suite
includes actual SDK + mock HTTP transport checks proving three requests rather
than nine, without paid API calls.

Verification commands:

The pre-follow-up baseline passed **523 tests, with 3 expected skips** and no
deselections. The follow-up reproduced eight failures in twelve new cases before
the two fixes; all twelve now pass. The affected analyzer/draft/remediation suite
passes **101 tests**. The dedicated remediation file now contributes 38 cases.
The final full local suite passed **535 tests with 3 expected skips** in 14.31
seconds; no tests were deselected. Compilation, changed-file Ruff E9/F checks,
`pip check`, and `git diff --check` passed. Remote CI evidence is recorded with
publication because the renderer-equipped run starts after the push.

```sh
python -m pytest -q
python -m compileall -q app pages scripts run_web.py
python -m pip check
ruff check --select E9,F <changed Python files>
git diff --check
```

The local environment lacks LibreOffice Writer/Calc import filters; two renderer
tests and the CI-only assertion are expected skips. A fresh locked environment
resolved the previous review's PyArrow import crash, and the expense email/share
test no longer needs exclusion. On resuming the September 11 session the local
launcher and PyArrow installation needed repair; reinstalling the same locked
PyArrow version restored the full run without changing project dependencies.
Publication must verify the remote Git tree and the repository's renderer-equipped
CI. CI does not prove live Render behavior: a deployed-version claim also requires
a live workflow-switch/background-reading smoke test. Render workspace selection
is separate from the authorized GitHub publication and must not block the push.

## Rollback and follow-up

There is no new persistent schema or credential requirement. Reverting these code
changes restores the former behavior; a restart removes the new process-local
initialization registry and workers. Active drafts remain session-only and should
be completed before a deployment restart.

Do not remove signature validation to improve speed, move PDF APIs into worker
threads, cache mutable receipt inputs, share draft caches globally, or restore SDK
retries on top of application retries. Those changes would reverse the controls
this remediation establishes.
