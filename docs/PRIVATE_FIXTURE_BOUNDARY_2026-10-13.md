# Private authentic fixture boundary and source corrections

Status: inspected October 13, 2026. This note records implementation boundaries,
not authentic acceptance. No authentic reports were uploaded, and no credentials,
authorization settings, disk settings, or service plan were changed.

## Verified starting capabilities

- `app/device_identity.py` creates an anonymous `epc_device_id` cookie. It is
  convenience identity, explicitly not owner authentication.
- `app/monthly_report_ui.py:render_monthly_report_workflow` accepts
  `monthly_qa=isolated` as a navigation choice. `app/monthly_report_testing.py`
  hashes the browser cookie into a separate physical namespace with an ownership
  marker and generation lease. These measures isolate synthetic testers; they do
  not prove that a tester is Evan.
- Repository search found no owner principal, login gate, OIDC configuration,
  server-side owner allowlist, or fixture authorization service in application
  code. `render_section_setup` describes the ordinary saved content as shared in
  the public internal-testing app.
- `render.yaml` configures `EPC_DATA_DIR=/test1` and documents a dashboard-created
  disk. A read-only Render service inspection performed by the coordinating
  agent reported service `srv-d6fi5pldi7vc73eotc00`, disk
  `dsk-d97p5gutrd3s739fmltg`, 1 GB mounted at `/test1`, one instance, and configured
  plan `1c-2g`. This is configuration evidence, not measured free capacity,
  successful redeploy retention, a private-access test, or a revised resource
  acceptance target. The task's 512 MiB/0.5-CPU regression gate remains separate.
- `app/memory.py:_data_dir` scopes memory and report data. Monthly reports,
  snapshots, originals, active journals, directories, capacity, training,
  designs, branding and sources derive from that root. An authentic run should
  reuse these boundaries, with an authenticated owner and independent run ID.
- `app/monthly_report_preview_store.py` separates live and QA stores and checks
  the generation before cache access. `monthly_report_section_preview_ui.py`
  copies worker context and binds only the QA namespace/reset lease inside UI
  fragments, preserving Streamlit's current fragment context. Reset rejects stale
  leases. These protections must remain present for authentic runs.
- `receipt_jobs.start_receipt` rejects external reader work under the existing
  isolated monthly context. Native DOCX fixture imports must retain that rule.

## Operation requiring approval

The current service does not have an approved owner authentication boundary.
A hidden control, report preparer name, random browser cookie or secret URL must
not be promoted into owner access. Do not send authentic bytes to the current QA
route or ordinary importer as a substitute.

The narrow approval to request is:

> Approve fixture-only owner authentication on the existing MSAPO Render
> service, authorization for Evan alone on fixture list/read/upload/replay/
> preview/download operations, and the minimum server secrets required for
> that authentication. Routine report drafting remains unchanged. No new paid
> service, plan change, live-data access grant, or automatic cleanup is included.

The owner must choose the identity provision before deployment. If an approved
OIDC client already exists, use it and an immutable owner subject allowlist; the
registration, callback and secret configuration are security changes requiring
approval. If none exists, a single-owner credential verifier plus a server-side
session-signing secret on this existing service is a smaller alternative, also
requiring explicit approval. Do not create a credential, display one in chat,
store one in Git, or infer the owner's login identity from Prepared by.

Approval of sign-in alone does not authorize rollout of an unprotected file
transport. The concrete implementation must authorize every private operation
server-side, including file uploads and media/download requests, and bind the
request to the owner, fixture/run and generation. Native `st.image`, `st.pdf` or
`st.download_button` URLs must not be assumed private because their controls
were rendered after sign-in. Use an authenticated private transport or a
reviewed first-party session-bound component that does not register authentic
content with anonymous media routes. Test copied URLs from an unauthenticated
second session before accepting the boundary. No fixture data belongs under
static assets, public CI artifacts or logs.

The supported Streamlit authentication documentation distinguishes identity
from resource authorization:
https://docs.streamlit.io/develop/concepts/connections/authentication . The
locked application runtime is Streamlit 1.61.1; implementation must be checked
against that version rather than a newer documentation example.

## Reviewable vault and importer design

1. Keep an immutable vault outside every disposable run subtree, for example
   `/test1/_enfra_private_fixtures_v1/<owner>/<fixture-id>/`. Reject absent mount,
   symlinks, unsafe path segments, traversal, partial/unmarked directories and
   hash mismatches. Never fall back to the live root or repository. Original
   bytes are content-addressed, installed atomically, and never overwritten.
2. Store a versioned private manifest: original hash/size/type, friendly name,
   source contract/sites/month, target contract/sites/month, AUTH scenario,
   owner-confirmed expectations, independently authored expected-content
   manifest and confirmation timestamp. Do not derive source identity or the
   genuinely half-finished report label solely from its filename.
3. Create a fresh owner/run/generation namespace for each scenario. Use the
   existing production importer: `inspect_docx`,
   `analyze_starting_report`, `automatic_section_plans`,
   `build_starting_import`, `imported_draft`, `merge_drafts`, then
   `library.save_report_setup`. The current orchestration lives in
   `app/monthly_report_section_ui.py:render_section_setup`; extract/reuse it
   for both callers instead of constructing a second parser. Include actual
   native-diagram recovery and design decisions. Do not invoke the hardcoded
   `monthly_report_qa_fixture.prepare` or `compare` as an authentic oracle.
4. Select target profile and period explicitly. Populate only owner-approved
   test standing data/design pins inside this namespace. An empty isolated
   namespace must not fall back to a live design, contact directory, capacity
   table or training matrix. Use production inspection/merge decisions and
   surface unresolved questions in the real editor.
5. Propagate owner/run/generation context into workers and periodic callbacks.
   Revalidate it at each file/cache read and write. Keep private previews and
   output delivery scoped and bounded. Logout, loss of authorization or reset
   must prevent old queued work from repopulating or exposing a former run.
6. Record private input/output hashes, import lineage, target, exact code/design
   identities and executed assertions. Test AUTH01–AUTH03 with independent
   expected manifests, unauthenticated rejection, two-session separation,
   repeat import/removal, no external calls, unchanged live data, reset and
   actual supported restart/redeploy retention before promising durability.

Retention proposal for owner approval: retain immutable originals and confirmed
manifests until Evan explicitly approves permanent purge. A visible Run reset
removes only that disposable run and invalidates its generation. It never
removes the vault, historical records or original Library files. No automatic
age-based purge or hidden abandonment TTL is included. Disk quotas and admission
must be checked before accepting uploads; a full vault must reject new uploads
without deleting existing work.

## Implemented independent source correction slice

`app/monthly_report_source_details.py` supplies explicit metadata correction
without editing source bytes, classifications, source text, page inclusion,
page-review receipts, or exclusions. `render_source_details` in
`app/monthly_report_upload_ui.py` provides a nullable Source date control, an
exact selected-report facility selector and **Save corrected details**. Unknown
values stay unknown. Foreign/unmatched source identities can remain explicitly
unresolved instead of defaulting to the first target site.

The helper runs for text/table sources before their former early return, for
image/page review, the batch tools and structured Activity/Capital/Proposal
uploads. Forms edit pending values separately from canonical source records;
opening or changing controls alone does not resolve warnings. Submission
updates the same `SourceContent` cache and source/report fingerprints consumed
by existing persistence, preview and preflight. A newer correction from another
view refreshes the stale form and rejects that stale submission. An old async
reader page result retains current date/site metadata.

This slice does not claim to implement explicit historical-retention decisions,
source item exclusion semantics, all hard-blocker recovery, authenticated
fixture uploads, authentic output proof or owner acceptance. Date/site
corrections still need actual source evidence; saving a chosen value is not
independent verification that the source supports it. Existing page safety and
unsupported-content gates remain in force.

Focused tests use only synthetic text/PDF fixtures. The final commit's test
command and observed results belong in the completion ledger; these tests do
not prove browser pointer/touch behavior, Safari, authentic source correctness
or durable Render storage.


## Focused execution record

On this source-correction branch, using the locked Streamlit 1.61.1 environment:

```sh
ANTHROPIC_API_KEY=test-key-not-used python -m pytest -q \
  tests/test_monthly_report_source_details.py \
  tests/test_monthly_report_section_uploads.py \
  tests/test_monthly_report_structured_upload_ui.py \
  tests/test_monthly_report_water_auto_include.py \
  tests/test_monthly_report_damaged_source_recovery.py
```

Observed result: **26 passed**. The marker key is the repository's existing CI
value; the reader test replaces network work with a controlled Future. No
external reader was called. This set checks explicit submit, unknown/foreign
identity, stale form rejection, shared canonical views, native text and structured
source editing, original bytes, metadata fingerprint/preflight recomputation,
unique source anchors, Water inclusion and recovery protections.

Development outcomes retained: first collection failed because the new test
used a nonexistent test draft helper (corrected to the production synthetic
fixture helper); the initial new/source-section subset then passed 15 tests.
The first broader invocation omitted the CI test-key environment and produced
24 passes plus the existing async-reader test failure because its reader was
not enabled. Running with the repository's CI environment produced the 26-test
pass above. These are development results, not deployed evidence.
