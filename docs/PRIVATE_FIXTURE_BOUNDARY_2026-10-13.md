# Fixture boundary history and source corrections

**Current access decision: shared, anonymous fixtures.** At15:36UTC on October13, Evan explicitly declined authentication and requested a hidden fixture area for coworkers and agents. The previous owner-only proposal below is historical and superseded; **no authentication approval is pending**. The current design and unfinished implementation are documented in [Shared fixture testing](SHARED_FIXTURE_TESTING_2026-10-13.md).

No authentic reports have been uploaded. No credentials, authorization settings, disk settings or service plan were changed. Hidden navigation is discoverable and does not make originals, metadata, replay or downloads private. Anyone who finds the shared route can access its fixtures by design. Actual fixture bytes and screenshots must still stay out of public Git/build/static assets/CI/logs.

## Superseded owner-only proposal — historical record

Before15:36 the requested feature required owner-only server authorization on list/read/upload/download/replay, private media transport and unauthorized-access rejection. Repository inspection found no approved owner principal, OIDC configuration or owner verifier. A proposed fixture-only login on the existing Render service would have needed a new credential/security decision; none was implemented or enabled. Evan subsequently declined that proposal. Do not continue asking for its approval or relabel its unexecuted checks as passes.

The disconnected `app/monthly_report_fixture_vault.py` primitive was implemented at15:10 with **40 passing synthetic tests**. It rechecks an injected server verifier for protected operations, maintains immutable native DOCX originals/hash and independently confirmed source/target/scenario manifests, and uses atomic/fsynced storage with descriptor-by-descriptor path validation. Tests cover owner isolation, quota/free-space admission, revocation and local restart/reopen. An `AuthorizedOwner` value alone is not proof of identity. No live authentication adapter was installed.

`VaultListing` separately reports interrupted uploads: committed fixtures remain readable; retained safe bytes count toward quota; unrecognized pending content blocks new admission without deletion. Replay copies are separate from original fixtures. These byte-integrity/storage tests are retained; they neither authenticate anonymous shared users nor establish Render redeploy retention. The new shared facade declares its anonymous audience explicitly and keeps distinct storage markers instead of constructing a fictitious authenticated owner.

| Former requirement | Current disposition |
| --- | --- |
| Only Evan can access originals, replay, previews and downloads | Superseded by the explicit shared-access choice |
| Anonymous requests/copied URLs must be rejected | Superseded for this shared route; anonymous availability is intentional |
| New owner credentials or identity provider | Not requested; no approval pending |
| Immutable originals/hash, explicit target/scenario and independent expectations | Retained |
| Production importer, isolated disposable runs, exact generation/reset leases and no live fallback | Retained; integrated evidence still required |
| No real files in Git/build/static assets/CI/logs | Retained; sharing inside the app does not authorize development-channel publication |
| No fixture purge or automatic expiry | Retained; run reset does not delete shared originals |

## Verified starting capabilities and limits

- `app/device_identity.py` provides an anonymous browser cookie. The existing `monthly_qa=isolated` path uses a physically separate namespace, ownership marker and reset generation. The new `monthly_qa=fixtures` path derives a different run token from that same browser cookie. This separates workspaces and is **not authentication**.
- Read-only Render inspection reported service `srv-d6fi5pldi7vc73eotc00`, disk `dsk-d97p5gutrd3s739fmltg`, **1GB at `/test1`**, one instance and configured plan `1c-2g`. This is configuration evidence, not measured free capacity, actual restart/redeploy retention or a changed resource target. The **512MiB/0.5CPU** regression gate remains.
- `app/memory.py:_data_dir` scopes reports, journals/history, originals, directories, thermal/training, designs/artwork and sources. Authentic fixture replay must reuse this boundary with exact source/target identity and an independent run generation; an empty test namespace must never fall back to live records.
- The preview store checks QA generation before cache access. Worker context and only the QA namespace/reset lease are propagated into periodic fragments, preserving the framework fragment identity. Stale jobs/callbacks cannot repopulate a reset namespace. These safeguards remain required in the shared route.
- Isolated monthly context rejects external receipt-reader work. Native DOCX fixture inspection must not add external calls, credentials, paid allowances, Smartsheet submissions, email or sharing actions.

The original source-correction implementation and its focused development outcomes follow. They are independent of the changed access policy and remain bounded evidence.

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
source item exclusion semantics, all hard-blocker recovery, a completed shared fixture route, authentic output proof or owner acceptance. Date/site
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
