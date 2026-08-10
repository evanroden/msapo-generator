# RRH Streamlining and Reliability Hardening

**Date:** 2026-08-08
**Scope:** second-pass usability and failure-mode hardening after the Ashley
workflow correction
**Parent specification:**
[`STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md`](STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md)

> **Current UI and release supplement:**
> [`RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md`](RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md)
> supersedes this document's step count, field-placement behavior, test count,
> brand notes, and browser/Smartsheet attachment guidance.

## 1. Outcome

The normal RRH operator path is now:

1. Upload the quote.
2. Glance at the extracted vendor, site, and total.
3. Enter or confirm the requester name. The browser/account memory normally
   supplies it after the first completed package.
4. Read one compact summary of the tool's choices.
5. Press **Generate both files and Smartsheet link**.
6. Download both files, open the prefilled form, and upload both files near the
   end of Smartsheet.

The full account, site, request type, job number, work route, asset, total,
vendor, vendor contact, 20-character description, and Additional Information
controls remain available inside **Review or change the tool's selections**.
For a complete, high-confidence RRH extraction, that section is collapsed. It
opens automatically when a critical guess is missing, invalid, or needs manual
data.

This changes the experience from reviewing approximately a dozen controls on
every request to entering one name and confirming one summary for the common
case. It does not remove the operator's ability to correct any exported value.

## 2. What the tool now decides automatically

| Decision | Automatic source | When the review section opens |
|---|---|---|
| Account and site | Facility extraction plus configured account/site registry | No unique account/site match |
| Work category and cost code | Model category plus the verified RRH site mapping | Category is missing or the site/category has no configured code |
| New PO vs. Change Order | Quote language | Change Order lacks an Original PO Number |
| Job number | RRH O&M default | Non-RRH account or missing job value |
| Fulfillment route | Model guess; deterministic fallback | Model did not return a supported route |
| Object Account and Agreement Type | Canonical deterministic route matrix | Amount/route cannot be validated |
| Specific asset | Unique match in the selected site's registry | No unique match is allowed to remain “No asset” |
| PO/CO amount | Extracted final all-in total | Missing, malformed, zero, or negative |
| Vendor and vendor representative | Quote extraction, then verified account/vendor memory | Any value missing or email malformed |
| Description of Work | Quote extraction | Missing; export is always capped at 20 characters |
| Requester / Asset Manager | Anonymous browser + exact ENFRA account memory | First use, blocked cookie, or new account |

The final summary exposes the generated request type, account, site, category,
cost code, route, Object Account, Agreement Type, full Asset ID, and amount.
This is the quick correctness check before generation.

## 3. Failure modes found and fixed

### HF-01 — Inactive pasted text could override a new upload

- **Severity:** Critical
- **Prior behavior:** both tab bodies executed on every Streamlit rerun. A stale
  paste box appeared later in the script and could silently become the active
  quote even while the user was looking at the upload tab.
- **Fix:** replace the tabs with one explicit quote-source selector and resolve
  exactly one active source. The inactive source can retain data but cannot
  override the selected source.
- **Additional control:** `quote_source` is stored in the verified PO context.
  Pasted text always produces a TXT snapshot, even if an older uploaded file has
  identical extracted text.
- **Coverage:** `tests/test_workflow_state.py` and `tests/test_po_context.py`.

### HF-02 — An unreadable replacement file could leave the prior quote visible

- **Severity:** Critical
- **Prior behavior:** extraction failure set an empty extracted-text value, but
  the old analysis object remained in session state and the page continued below
  the uploader.
- **Fix:** an empty or failed active source removes the old analysis, fingerprints,
  generated context, and PDF. The page returns at Step 1 instead of displaying a
  stale Step 2–4 workflow.
- **Coverage:** source-state clearing regression.

### HF-03 — File-reading failure was cached as though extraction succeeded

- **Severity:** High
- **Prior behavior:** the uploaded file hash was stored after success or failure.
  Re-uploading the same file could never retry extraction during that session.
- **Fix:** success and error hashes are separate. A failed hash pauses automatic
  retries and exposes **Try reading this file again**. A successful retry alone
  becomes the extraction cache.

### HF-04 — Model failure could retry on every unrelated rerun

- **Severity:** High
- **Prior behavior:** a failed model response did not get a failure fingerprint,
  so Streamlit could call the model again whenever the script reran.
- **Fix:** cache the failed quote signature and expose one explicit
  **Try analyzing this quote again** action. Changing the source naturally uses a
  new signature.

### HF-05 — Oversized quote files were accepted despite Smartsheet's limit

- **Severity:** High
- **Prior behavior:** the uploader advertised a 200 MB default, while a file over
  30 MB cannot become a Smartsheet attachment. The app could spend time reading
  and analyzing a file that would later be blocked.
- **Fix:** Streamlit 1.61 is the minimum runtime and the quote widget enforces a
  30 MB per-file limit before extraction. Extracted or pasted text above 500,000
  characters is blocked before a model call.

### HF-06 — Zero, negative, or malformed amounts could pass some routes

- **Severity:** Critical
- **Prior behavior:** labor, rental, and equipment classification did not parse
  the total. The Smartsheet number parser also accepted zero and negative values;
  stripping unsupported characters could turn `1e3` into `13`.
- **Fix:** every route requires a conventional currency value greater than zero.
  The parser accepts currency symbols, commas, optional `USD`, and at most two
  decimals; it rejects repaired or ambiguous values. UI generation is disabled
  until this passes.
- **Coverage:** every route, zero, negative, exponent-like, and excess-decimal
  cases.

### HF-07 — Excluded labor or rental could control fallback routing

- **Severity:** Critical
- **Prior behavior:** keyword fallback interpreted `installation excluded`,
  `labor by others`, or `rental not included` as affirmative labor/rental.
- **Fix:** evaluate each routing keyword within its clause and ignore locally
  negated or excluded occurrences, including grouped phrases such as
  `installation and labor excluded`, `rental equipment is excluded`, and
  `installation is not part of the quoted scope`. The model prompt now contains
  the same rule.
- **Coverage:** negated labor, rental, mixed affirmative/negative, equipment, and
  materials examples.

### HF-08 — A parts quote could become Equipment because it named the parent unit

- **Severity:** High
- **Prior behavior:** Group A matching could see `chiller` in `replacement chiller
  gaskets` and treat the quote as a full chiller purchase in some fallback cases.
- **Fix:** detect equipment terms immediately followed by part/kit language.
  Evaluate mixed quotes per purchase phrase so chiller parts cannot hide a
  separately purchased complete boiler. Whole-unit purchase verbs still allow
  a chiller supplied with spare gaskets to remain Equipment.

### HF-09 — An Asset ID could match inside a longer serial number

- **Severity:** Critical
- **Prior behavior:** direct UID matching used substring containment.
- **Fix:** match normalized UIDs only at identifier boundaries. A unique real
  registry match remains required; no asset code is invented.

### HF-10 — Vendor edits did not invalidate the vendor-bearing scope PDF

- **Severity:** High
- **Prior behavior:** the document signature covered quote, contract, site,
  Inclusions, and Exclusions but not the vendor name or final scope text printed
  in the PDF.
- **Fix:** both vendor and scope now participate in the PDF signature. A change
  removes the stale generated result and requires the same generation button
  again.

### HF-11 — A required value could be absent from the generated URL

- **Severity:** Critical
- **Prior behavior:** URL preflight checked whether a required source value was
  populated, not whether it was actually encoded. A missing label mapping or URL
  limit could skip a required field while still exposing the form link.
- **Fix:** required values must be both populated and present in the final encoded
  field set. The link is withheld when any required field, including conditional
  Original PO Number, is not included.

### HF-12 — Stale widget values could fall outside a changed option catalog

- **Severity:** High
- **Prior behavior:** a deployment changing contracts, sites, categories, job
  choices, route values, or request-type values could leave an old Streamlit
  session value that no longer belonged to the widget options.
- **Fix:** sanitize each keyed selection, including the full Asset ID, against
  the current catalog before rendering. Invalid values reset to a
  detected/default value or a blocking placeholder.

### HF-13 — PDF-generation errors terminated the whole page

- **Severity:** Medium
- **Prior behavior:** `st.stop()` prevented the footer and remaining recovery UI
  from rendering after an exception.
- **Fix:** keep the page active, show the error, and allow the operator to retry
  the same final button.

### HF-14 — Runtime warnings forecast iframe failure and masked CORS intent

- **Severity:** Medium
- **Prior behavior:** the handoff and anonymous-device bootstrap used
  `st.components.v1.html`, which Streamlit 1.61 marks for removal. Runtime
  configuration also set CORS off while keeping XSRF protection on, forcing
  Streamlit to override the CORS value at startup.
- **Fix:** use the supported `st.iframe` API for all trusted inline components,
  keep the invisible cookie bootstrap out of keyboard navigation, and explicitly
  align CORS with enabled XSRF protection. Production startup no longer depends
  on an automatic security-setting override.
- **Coverage:** component-source and runtime-configuration regression tests plus
  the synthetic AppTest workflow.

## 4. Additional streamlining opportunities

### A. Add the complete site/cost-code catalog

This is the next low-risk reduction once the promised data is supplied. Store
the complete account → site → work-category → cost-code mapping in one validated
registry. A unique match would make work category and cost code invisible in the
normal flow. Unknown combinations would open the review section rather than
guessing.

Recommended import controls:

1. Require a unique account/site/category key.
2. Reject duplicate keys and blank codes.
3. Preserve leading zeroes as text.
4. Generate a report of added, changed, and removed codes before deployment.
5. Regression-test every supplied row and a sample from each account.

### B. Remember a small account-specific manager roster

The current behavior uses the most recently verified manager for one device and
account. A future version can retain the last three verified names for that same
pair and show a compact selector only when more than one person regularly uses a
shared tablet. Do not build a company-wide directory from this convenience data;
account and device isolation prevents unrelated names from leaking into other
workflows.

### C. Learn recurring vendor contacts and asset choices

The repository already contains contract-scoped vendor-contact learning. It can
be connected to the quick path after adding these controls:

- require an exact normalized vendor and account match;
- prefer quote-extracted contact data over memory;
- surface remembered values only when the quote omits them;
- never use vendor memory across accounts; and
- keep asset memory subordinate to a quote-supported tag and selected site.

This would remove repeated corrections for recurring service vendors without
allowing a remembered contact or asset to override current quote evidence.

### D. Replace the link-and-upload handoff with a guarded API action

This would remove the remaining Smartsheet work: no recent-login prerequisite,
no two downloads, no manual uploads, and no form submit. The existing API adapter
already contains leases, deterministic submission fingerprints, attachment
reconciliation, and ambiguous-write controls, but production remains disabled
because the exact destination column IDs/types, least-privilege token, dedicated
submission-key column, authentication model, and controlled acceptance test have
not been supplied.

Activation sequence:

1. Add user authentication and account authorization.
2. Verify the destination sheet and every column ID/title/type/option.
3. Add the dedicated submission-key column.
4. Run dry-run schema checks.
5. Create one synthetic row and attach two synthetic files.
6. Verify duplicate-click, timeout, partial-attachment, and reconciliation paths.
7. Enable one-account pilot before broader rollout.

Until those gates exist, the prefilled-link route is safer because it never
creates a remote financial record.

### E. Add structured confidence and exception-only review

The current review section opens from deterministic gaps. A later analyzer
schema can return confidence for account/site, route, request type, amount, and
asset clue. Only low-confidence decisions would open their specific field. The
confidence must be calibrated against saved synthetic quotes before hiding more
controls; a plausible wrong answer is more dangerous than a blank one.

### F. Add an end-of-form attachment checklist without another checkbox

The tool already displays the upload reminder. A future Smartsheet form revision
could move the attachment question immediately above Submit and label the two
required files by the exact generated names. This reduces attachment omissions
without adding state or confirmation controls to the generator.

## 5. Residual failure modes

| Residual risk | Current control | Why it remains |
|---|---|---|
| Plausible but wrong model extraction | Visible vendor/site/total cards, compact route/account/asset summary, optional full review | Semantic correctness cannot be proven from schema validation alone |
| Smartsheet form labels/options change | Exact mappings, exact option validation, required-encoded-field gate, hidden manual fallback | The form is managed outside this repository |
| Smartsheet session is stale | Recent-login/retry reminder | URL prefill depends on current browser/Smartsheet behavior |
| Files are not uploaded | Two prominent downloads and upload reminder | URL parameters cannot transmit local files |
| Shared browser remembers the last user | Requester remains visible and editable; memory is device+account scoped | A browser cookie cannot identify a person |
| Persistent disk is unavailable | Workflow continues with a blank requester | Convenience memory is intentionally non-blocking |
| Model service is unavailable | Bounded internal retries plus explicit operator retry | External service availability cannot be eliminated locally |
| Full cost-code coverage is incomplete | Known RRH mapping; missing code opens manual review and blocks generation | Complete account/site data has not yet been provided |
| Public deployment access | No automatic remote submission; quotes stay in the active session except memory metadata | Authentication requirements and identity provider have not been specified |

## 6. Verification

The focused local suite contains **130 passing tests** after this hardening pass.
It covers the Ashley routing matrix, strict amount parsing, negation-aware route
fallback, Group A parts handling, bounded Asset ID matching, source selection,
stale-state clearing, vendor-bearing PDF signatures, required URL inclusion,
20-character export, two-file handoff, device/account memory, and the quick-path
UI contract.

Production acceptance should use only synthetic data and should not submit the
Smartsheet form:

1. Load the synthetic quote.
2. Confirm the detailed override section is collapsed.
3. Enter a synthetic requester and verify the compact summary.
4. Generate and verify exactly two downloads plus one form link.
5. Confirm the PO URL omits Original PO Number.
6. Switch to Change Order, enter a synthetic Original PO Number, regenerate, and
   verify the exact field appears.
7. Reload and confirm requester memory for the same device/account.
8. Confirm no form submission or upload occurs during acceptance.

## 7. Commit notes

Suggested title:

```text
Streamline the RRH quick path and harden quote handoff state
```

Suggested body:

```text
- collapse AI/defaulted PO controls behind exception-only review
- leave requester plus one compact generated summary in the common RRH path
- replace competing upload/paste tabs with one authoritative source selector
- clear stale analysis and package state when an active source fails or disappears
- add bounded file-reading and model-analysis retry controls
- enforce the 30 MB attachment and 500k-character analysis limits up front
- require a positive, strictly parsed total for every classification route
- ignore negated labor/rental language and parent-equipment names in parts quotes
- require bounded full-registry Asset ID matches
- include vendor and scope in the generated-PDF signature
- withhold Smartsheet links that omit any required encoded field
- sanitize stale selectbox state and keep PDF failures recoverable
- replace deprecated iframe calls and align CORS/XSRF runtime settings
- add focused regression coverage and a detailed failure-mode register
```

Runtime-warning follow-up title:

```text
Replace deprecated Streamlit embeds and align CORS protection
```

Runtime-warning follow-up body:

```text
- replace every trusted components.v1 HTML embed with the supported st.iframe API
- keep the invisible device-cookie bootstrap outside keyboard navigation
- preserve scrolling and fixed sizing for the Smartsheet handoff components
- explicitly enable CORS alongside XSRF protection instead of relying on a runtime override
- add regression coverage for embed API removal and contradictory security settings
- rerun the full synthetic three-step package and handoff workflow without submission
```
