# Smartsheet custom-URL prefill successor handoff — 2026-08-06


## Production follow-up: form opened but every value remained blank

### User-visible evidence

After production commit `2ad2f4da827b8a6a077033d69f68a16e223ab4ca`
made the generated custom URL reachable, a real-device test produced a more
specific result: the purple link opened the correct Smartsheet PO form, but no
field was populated. This distinguishes the incident from the earlier bare-link
and Streamlit-state failures. The prepared EPC values existed, the custom-URL
route was enabled, and navigation reached the intended form; the receiving form
rejected the serialized query payload.

### Root cause

`build_prefilled_form_url` used Python's default `urllib.parse.urlencode`
behavior. That behavior delegates to `quote_plus`, which serializes every space
as a literal `+`. For example, it emitted:

`REQUEST+TYPE=PO&JOB+NUMBER=RRH-695400022-O%26M`

Smartsheet's documented custom-form syntax uses RFC 3986 percent escapes for
spaces, such as:

`REQUEST%20TYPE=PO&JOB%20NUMBER=RRH-695400022-O%26M`

The exact field names and values were logically correct, but the wire
representation was not compatible with the live form. This affected nearly
every production key because most labels contain spaces. Smartsheet treated the
custom URL as an ordinary form open and presented blank inputs.

The official reference used for this correction is:

https://help.smartsheet.com/articles/2478871-url-query-string-form-default-values

### Why the previous tests passed

The PR #31 tests immediately called `parse_qs` on the generated URL and compared
the decoded dictionary with the expected labels and values. Form-style query
decoding deliberately treats `+` and `%20` as the same space character.
Consequently, the test erased the very distinction that mattered to Smartsheet
before making its assertions.

This is an interoperability-test gap: semantic round-trip tests alone are
insufficient when an external receiver requires a narrower on-the-wire syntax.

### Correction

The builder now centralizes serialization in `_encode_prefill_query` and calls:

`urlencode(query_items, doseq=True, quote_via=quote)`

The same encoder is used both while checking each candidate against the
configured URL-length ceiling and while producing the final link. This prevents
candidate/final length drift and guarantees that labels and values use `%20`
for spaces. Reserved data characters continue to be escaped, including:

- `&` in `O&M` as `%26`
- `/` in `SITE NUMBER / LOCATION` as `%2F`
- `?` in `DISPATCH WO TO SERVICE CENTER?` as `%3F`
- `#` in scope text as `%23`

No form labels, business values, environment variables, or routing controls are
changed by this correction.

### Regression boundary

Tests now inspect the raw query string before decoding it. They require:

1. no literal `+` anywhere in the generated prefill query;
2. `%20` in every label and value containing spaces;
3. exact escaping of the RRH `O&M` job number;
4. exact escaping of the slash and question mark in live labels;
5. exact escaping of ampersands and hashes in representative values; and
6. the existing semantic `parse_qs` round-trip assertions.

A future change that restores `quote_plus` will therefore fail even though the
decoded Python dictionary still looks correct.

### Preserved product and safety behavior

This repair does not alter any established boundary:

- Request Type remains locked to `PO`.
- Dispatch remains locked to `NA`.
- RRH defaults to `RRH-695400022-O&M`.
- The email backup remains beside the Smartsheet route.
- Attachments remain download-and-upload because a custom URL cannot carry them.
- Opening the URL never submits a row.
- Direct Smartsheet API row creation remains disabled.
- Requester learning remains browser scoped with the three-distinct-PO rule.
- Exact-label mapping, cell limits, URL limits, and Copy fallbacks remain active.

### Deployment and acceptance sequence

After CI passes, merge and allow Render to deploy the exact merge commit. Confirm
the root page and health endpoint start cleanly. Then perform a non-submitting
real-device check with a newly prepared PO:

1. confirm the EPC page reports populated fields ready to prefill;
2. tap **Open prefilled Smartsheet form**;
3. confirm at minimum Request Type, Requester, Job Number, Site, Amount, Vendor,
   Description, and Dispatch are populated;
4. verify the dropdown values match exact options;
5. do not submit the test form;
6. return to EPC and confirm attachment downloads and **Use email backup** remain
   available.

If the form still opens blank, capture the visible destination URL before making
another code change. The next branches to distinguish are query loss during
mobile-app/auth redirection, a form-label change, and a receiver URL-length
limit. Do not guess among those conditions, enable API submission, or remove the
email fallback.

## Purpose and authority

This document records the production correction that changes Email Process
Control's inline Smartsheet handoff from a plain form link plus manual copying to
an exact-label custom URL that prefills the reviewed PO values.

It is intentionally detailed so a future maintainer or LLM can reconstruct the
business intent, safety boundaries, configuration, failure behavior, tests,
deployment order, and acceptance procedure without relying on chat history.

The user explicitly required:

1. **Open Smartsheet Form must autofill automatically through the custom URL.**
2. The existing email action must remain beside Smartsheet as a backup.
3. The application is PO-only for now, so Request Type remains exactly `PO`.
4. Work-order service-center routing is out of scope, so Dispatch remains exactly
   `NA`.
5. RRH's normal job number remains `RRH-695400022-O&M`.
6. Requester learning remains device/browser scoped with the existing
   three-distinct-PO threshold.
7. A signed-in Smartsheet browser session may be used for acceptance, but it is
   temporary and must not be treated as application configuration or a stored
   credential.

## Incident that prompted this correction

Production commit `f320b99d78e12cc83f48ea2860ef8c6707bfa043` fixed a
mobile Streamlit session-loss failure by keeping the Smartsheet handoff inline
on the same root page and retaining the email route beside it. That correction
made the reviewed PO values, attachment downloads, and exact-label copy helper
visible.

However, the purple **Open Smartsheet form** control still received
`config.form_url`, the bare form URL:

`https://app.smartsheet.com/b/form/019e8e6717c471628f9a02280a892100`

Consequently, Smartsheet opened a blank form. The copy controls were technically
available in the original tab, but the user reasonably expected the action to
carry the prepared PO information. The URL builder already existed in
`app/smartsheet.py`; it was not connected to the inline production route and
its Render feature gate remained false.

This correction wires the existing fail-closed builder into the actual inline
handoff and enables its verified exact-label mapping in deployment
configuration.

## Supported route after this correction

The visible production sequence is:

1. Analyze and review a quote.
2. Generate the correct MSAPO package, or preserve quote-only behavior for an
   Equipment-only PO.
3. Choose either adjacent action:
   - **Prepare Smartsheet submission** (primary)
   - **Use email backup**
4. In the Smartsheet route, confirm Requester, Job number, Site/Location, Object
   account, and optional Additional Information.
5. Download the verified attachment package.
6. Tap **Open prefilled Smartsheet form**.
7. Review the values Smartsheet populated.
8. If Smartsheet leaves a field blank, return to Email Process Control and use
   that field's existing Copy button.
9. Upload the files downloaded in step 5.
10. Submit only after human review.

Opening the custom URL does **not** create a row and does **not** submit the form.

## Exact custom-URL mapping

Smartsheet query-string keys must be the exact visible form labels. No fuzzy,
case-insensitive, or guessed label matching is allowed.

| Logical field | Exact form query key | Typical value/source |
|---|---|---|
| `request_type` | `REQUEST TYPE` | Locked `PO` |
| `requester_name` | `REQUESTER` | Confirmed user/browser memory |
| `job_number` | `JOB NUMBER` | Exact selected option; RRH defaults to `RRH-695400022-O&M` |
| `site_location` | `SITE NUMBER / LOCATION` | Reviewed exact Smartsheet wording |
| `cost_code` | `COST CODE` | Reviewed EPC cost code |
| `object_account` | `OBJECT ACCOUNT` | Exact selected option |
| `agreement_type` | `AGREEMENT TYPE FOR PO` | Reviewed MSAPO/EPO mapping |
| `original_po_number` | `ORIGIONAL PO NUMBER` | Normally blank; live misspelling is intentional |
| `total` | `PO/CO AMOUNT` | Validated PO amount |
| `vendor` | `VENDOR NAME` | Reviewed quote extraction |
| `contact_name` | `VENDOR CONTACT NAME` | Reviewed quote/contact value |
| `contact_email` | `VENDOR CONTACT EMAIL` | Validated reviewed email |
| `description_of_work` | `DESCRIPTION OF WORK` | Reviewed scope, max 4,000 characters |
| `asset_id` | `ASSET ID` | Registry-verified UID or blank |
| `dispatch_service_center` | `DISPATCH WO TO SERVICE CENTER?` | Locked `NA` |
| `instructions` | `ADDITIONAL INFORMATION IF NEEDED` | Optional reviewed note |

The source-controlled map is written explicitly in `render.yaml` and
`.env.example` as `SMARTSHEET_FORM_FIELD_MAP_JSON`. Future form-label changes
must update this map and tests together. Do not “helpfully” correct
`ORIGIONAL PO NUMBER` unless the live form label and sheet column have first
been changed and verified.

The “Send me a copy of my responses” control is deliberately not added to the
custom URL. Smartsheet's documented response-copy query parameter (`ECA`) needs
the submitter's email address, while this workflow remembers only the requester's
name. The former EPC boolean checkbox could not supply that email and its Copy
value was not actionable, so the handoff now tells the user to choose the option
inside Smartsheet if needed. Do not pass a vendor contact email or guess a
requester email to automate this control.

## URL construction behavior

`app.smartsheet.build_prefilled_form_url` remains the only URL builder. It:

- validates that the base URL is HTTPS on a Smartsheet domain;
- requires `SMARTSHEET_URL_PREFILL_ENABLED=true`;
- requires an explicit logical-field-to-exact-label map;
- follows the configured, deterministic form-field order;
- percent-encodes labels and values with the standard query-string encoder;
- preserves unrelated query parameters already on the base URL;
- replaces any old value for a mapped form label;
- skips empty values;
- skips any individual cell above Smartsheet's 4,000-character cell limit;
- respects `SMARTSHEET_PREFILL_MAX_URL_LENGTH` (7,000 in production);
- reports exactly which logical fields were included or skipped;
- never receives, hashes, serializes, or appends attachment bytes.

The live inline route now passes `prefilled.url` to the purple form control.
Passing `config.form_url` from that route is guarded by a regression test.

If URL construction is disabled or misconfigured, the production route displays
an error and directs the user to the adjacent email backup. It does not silently
open the empty base form and recreate this incident.

If the URL length limit or an absent exact mapping prevents one populated field
from being included, the form may still open with all safely included values.
The UI lists the omitted field labels and retains every Copy button beneath the
link. This is an explicit partial-prefill fallback, not silent data loss.

## Attachment boundary

Smartsheet custom URLs carry text/default form values only. They cannot upload
the quote, DOCX, or PDF.

Therefore:

- attachment download buttons remain above the form action;
- the original vendor quote bytes remain unchanged;
- standard PO packages continue to offer quote + DOCX + PDF;
- Equipment-only POs continue to offer the unchanged quote only;
- the user uploads those files to the Smartsheet form manually;
- attachment bytes or filenames must never be placed in query parameters;
- direct API attachment writes remain disabled.

Do not remove the attachment instructions merely because form fields now
prefill.

## Privacy and browser behavior

A custom URL necessarily places the prepared values in the user's address bar
and browser history while the form is open. This is an explicit product choice
requested for the browser handoff. The link remains a user-initiated action and
is not logged by the application as a URL.

The anchor now includes all of:

- `target="_blank"`
- `rel="noopener noreferrer"`
- `referrerpolicy="no-referrer"`

These attributes isolate the new tab and suppress sending the EPC page as a
referrer. They do not erase Smartsheet's own URL from the user's browser
history.

Never log the generated custom URL, expose it in server diagnostics, analytics,
or exception messages, or reuse it across PO contexts.

The Smartsheet acceptance login is entered only in Cloud Browser by the user.
Credentials must never be pasted into chat, committed, copied into Render
variables, or stored by this application. The temporary browser session is for
a non-submitting acceptance check only.

## Email fallback is non-negotiable

`app/web_ui.py` continues to render **Prepare Smartsheet submission** and
**Use email backup** in adjacent columns. This change does not alter that file
or the email-building path.

The backup must remain available when:

- Smartsheet authentication expires;
- Smartsheet is unavailable;
- custom URL configuration fails closed;
- a form option or label changes;
- an operator needs the established email workflow.

Email contents, attachments, client-side delivery, and “I sent it” learning
behavior are unchanged.

## Files changed

### `app/smartsheet_inline.py`

- Imports and calls `prefill_enabled` and
  `build_prefilled_form_url`.
- Replaces language claiming that values are not automatic.
- Uses a prefilled-form heading and ordered instructions.
- Fails loudly if the deployment gate or exact map is absent.
- Derives fallback rows from the builder's included-field record.
- Passes `prefilled.url`, never the base form URL, to the handoff component.
- Keeps download buttons and all mapped-field Copy controls.
- Removes the non-actionable response-copy boolean and directs that choice to
  the real Smartsheet form, where the requester can provide the proper email.
- States clearly that opening the URL does not submit or carry attachments.

### `app/smartsheet_ui.py`

- Adds an optional `link_label` argument without breaking legacy callers.
- Lets the inline route label the action **Open prefilled Smartsheet form ↗**.
- Adds explicit no-referrer behavior.
- Leaves copy progress, reset behavior, clipboard fallbacks, and responsive
  sizing unchanged.

### `render.yaml`

- Sets `SMARTSHEET_URL_PREFILL_ENABLED` to `"true"`.
- Adds the complete exact-label `SMARTSHEET_FORM_FIELD_MAP_JSON`.
- Leaves `SMARTSHEET_API_MODE=disabled`.

### `.env.example`

- Mirrors the production exact-label configuration.
- Describes URL prefill as verified and API writes as independently disabled.

### Tests

- Require the inline route to invoke the builder and pass `prefilled.url`.
- Prohibit regression to `config.form_url or ""` in the inline route.
- Require the prefilled link label and no-referrer controls.
- Require the Render blueprint to enable prefill and contain every exact label.
- Build a synthetic complete RRH-style PO with ampersands, apostrophes,
  currency punctuation, email syntax, and an asset ID.
- Parse the generated query string and require every populated field to
  round-trip exactly.
- Require attachments not to appear in the URL.
- Retain the existing regression that email and Smartsheet actions remain
  side-by-side.

## Deployment order

1. Publish the feature branch and open a pull request.
2. Run the full GitHub Actions suite.
3. Inspect the diff and retain direct API mode as disabled.
4. Merge with the detailed successor record in the squash commit message.
5. Wait for Render's auto-deploy of the merged commit.
6. Only after the code deploy is available, update the Render dashboard values:
   - `SMARTSHEET_FORM_FIELD_MAP_JSON` = the exact full JSON map in
     `render.yaml`
   - `SMARTSHEET_URL_PREFILL_ENABLED=true`
7. Allow the environment update to create/restart the production deployment.
8. Verify service health and absence of new error logs.
9. Run the non-submitting acceptance check below.
10. Keep the email fallback visible throughout.

The dashboard update is required because Render dashboard variables may
override repository blueprint values. A green repository diff alone does not
prove the production runtime gate is enabled.

## Live acceptance procedure

Use only synthetic, redacted, or otherwise approved values. Never submit the
test form.

1. Open production Email Process Control.
2. Analyze a safe test quote and generate its package.
3. Confirm both delivery buttons appear beside each other.
4. Select **Prepare Smartsheet submission**.
5. Confirm the handoff remains on the root Streamlit page.
6. Fill Requester and confirm:
   - Request Type is locked to `PO`;
   - Dispatch is locked to `NA`;
   - RRH defaults to `RRH-695400022-O&M`;
   - exact site, cost code, object account, and agreement type are visible;
   - attachment downloads are present.
7. Tap **Open prefilled Smartsheet form**.
8. If Smartsheet requires authentication, the user signs in directly in Cloud
   Browser.
9. Confirm each mapped field displays the expected synthetic value.
10. Pay special attention to encoded characters:
    - the ampersand in `O&M`;
    - slashes in labels;
    - `#`, `&`, apostrophes, currency symbols, commas, and email `@`.
11. Confirm no row is submitted.
12. Return to EPC, switch to **Use email backup**, and confirm the existing email
    panel and attachments remain available.
13. Check Render health/logs after the browser flow.

A browser-emulated pass does not replace one final real iPhone/iPad check, but
it is sufficient to validate the custom URL mapping before asking the user to
repeat the original workflow.

## Rollback

If production form prefilling is wrong:

1. Keep the deployed code and set
   `SMARTSHEET_URL_PREFILL_ENABLED=false` in Render.
2. The inline route will fail loudly and the email backup remains usable.
3. Correct only the exact field/value map after inspecting the live form.
4. Re-enable and retest without submitting.
5. Do not switch to direct API submission as a workaround.

If the code itself causes an unrelated failure, roll Render back to
`f320b99d78e12cc83f48ea2860ef8c6707bfa043` and leave the URL-prefill flag
false.

## Out of scope

This correction does not:

- submit the form automatically;
- write a Smartsheet row through the API;
- upload files through the API;
- implement WO or change-order workflows;
- change the PO-only `PO` and `NA` rules;
- change requester-learning thresholds;
- change quote analysis or document generation;
- change email contents or sending behavior;
- prove that future renamed labels/options will continue working.

Any future direct API route must continue through the existing disabled →
dry-run → live gates and preserve durable idempotency, exact column IDs/types,
remote reconciliation, and attachment recovery rules.
