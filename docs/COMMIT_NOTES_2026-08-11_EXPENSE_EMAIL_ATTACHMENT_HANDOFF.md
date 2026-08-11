---
document_type: implementation_commit_handoff
repository: evanroden/msapo-generator
branch: main
implementation_commit: 96238d3b68717f709b8b068ba52a981fec7d6868
implementation_commit_subject: Restore attached expense email handoff
base_commit: df308e330c62d666c056dc80a2a222e15227cb01
implementation_tree: 898ad226b19ef470a6d30f99e6a633378466152f
date: 2026-08-11
workflow: expense_reimbursement
change_type: behavior_correction_and_browser_hardening
status: shipped
tests: 272_passed
ci_run: https://github.com/evanroden/msapo-generator/actions/runs/31526452178
---

# Commit notes: attached expense-email handoff

## 1. LLM quick context

This document is the detailed engineering record for implementation commit
`96238d3b68717f709b8b068ba52a981fec7d6868`.

The product owner corrected an inaccurate assumption in the first expense-report
implementation: browser-based email actions in the earlier purchase workflow
already handed generated files to Outlook and iOS. The expense workflow must
reuse that attachment-bearing behavior. It must not make the employee download
the combined PDF and manually attach it during the normal path.

The shipped behavior is:

1. **Outlook for Windows** receives an unsent `.eml` draft containing the
   completed combined PDF as its only attachment.
2. **Outlook on the web** receives the same attachment-bearing `.eml`. If the
   browser downloads rather than opens it, the employee can drag the `.eml`
   onto Outlook on the web's reading pane.
3. **iPhone and iPad** receive the combined PDF as a browser `File` through
   `navigator.share()`. The reviewed email subject and body are passed with it.
4. The Web Share API cannot populate a mail recipient. The component therefore
   copies the reviewed approver email immediately before opening the share
   sheet; if copying fails, it displays the address.
5. The editable Excel report, a direct PDF download, and an attachment-free
   `mailto:` fallback remain inside the collapsed **Other file and email
   options** expander.
6. The application still creates a draft only. It does not send email, approve
   the report, post to JDE, or transmit attachment bytes to an email service.

These are product invariants, not implementation suggestions. A later agent
must preserve them unless the product owner explicitly changes the workflow.

## 2. Why this correction was required

### 2.1 Incorrect behavior before the commit

The immediately preceding expense workflow treated Outlook on the web and
iPhone/iPad as URL-only email destinations:

- Outlook on the web used an
  `https://outlook.office.com/mail/deeplink/compose?...` URL.
- iPhone/iPad used a `mailto:` URL.
- Both routes told the employee to open the collapsed file area, download the
  PDF, return to the draft, and attach the PDF manually.

That behavior was internally consistent but contradicted the product owner's
known working purchase-request behavior. It also introduced several avoidable
failure opportunities:

- the employee could send the draft without the required PDF;
- the wrong local download could be attached;
- mobile users had to switch among the browser, Files, and Mail;
- the primary button's promise differed by platform;
- the most important completion path depended on controls intentionally hidden
  inside a secondary expander.

### 2.2 Authoritative correction

The product owner stated that the browser-created files already attach to the
Outlook and iOS actions in the purchase-order workflow. That statement is the
source-of-truth product decision for this commit.

### 2.3 Additional defect found during implementation

The first correction draft placed the Web Share JavaScript in
`streamlit.components.v1.html`. Streamlit renders that HTML in a `srcdoc`
iframe whose browser origin is opaque (`location.origin == "null"`). The Web
Share permissions-policy default allowlist is `self`. Therefore, an opaque
component iframe is not a reliable context for `navigator.share()` on current
Safari/WebKit implementations even if a desktop mock exposes the API.

The final implementation uses a declared Streamlit custom component served from
the application's own `/component/...` route. Browser inspection confirmed that
the component origin equals the parent application origin. This preserves the
user-gesture call while satisfying the first-party permissions-policy model.

Reference behavior:

- W3C Web Share API: <https://www.w3.org/TR/web-share/>
- WebKit iframe permission explanation:
  <https://webkit.org/blog/13708/allowing-web-share-on-third-party-sites/>
- Microsoft `.eml` handling in Outlook and Outlook on the web:
  <https://support.microsoft.com/en-us/outlook/mail/open-eml-msg-and-oft-files-in-new-outlook-and-outlook-on-the-web>

## 3. Goals and non-goals

### 3.1 Goals

- Make the normal expense-approval action attachment-bearing on every supported
  target.
- Keep the submission artifact limited to the combined PDF. Excel remains an
  optional editable download.
- Default Windows browsers to Outlook and Apple mobile browsers to Web Share.
- Keep all destinations selectable in case browser detection is wrong.
- Preserve the approved recipient, subject, and body generated from reviewed
  report data.
- Fail visibly when direct file sharing is unsupported.
- Retain usable recovery paths without making them compete with the primary
  action.
- Avoid adding an email API, OAuth permission, external JavaScript dependency,
  or server-side send action.
- Preserve public-repository safety.

### 3.2 Non-goals

- Sending the email automatically.
- Attaching the editable Excel workbook to the approval email.
- Populating the iOS Mail `To` field through Web Share; the API has no recipient
  member.
- Changing receipt analysis, reimbursement calculations, workbook generation,
  PDF assembly, signatures, mileage, JDE coding, or approver memory.
- Changing the active purchase-order/Smartsheet workflow.
- Adding Android-specific UX.
- Adding Microsoft Graph, Outlook add-ins, SMTP, SendGrid, or another email
  integration.
- Guaranteeing how every installed share-sheet target maps `title` to an email
  subject; the employee still reviews the draft before sending.

## 4. User-visible behavior matrix

| Selected destination | Primary control | Artifact supplied | Recipient behavior | Recovery behavior |
|---|---|---|---|---|
| Outlook for Windows | Download/open approval `.eml` | Combined PDF embedded as MIME attachment | `.eml` contains reviewed `To` header | If the browser downloads it, open the downloaded `.eml` once |
| Outlook on the web | Download/open approval `.eml` | Same combined PDF embedded as MIME attachment | `.eml` contains reviewed `To` header | Drag downloaded `.eml` onto the Outlook Web reading pane if it does not open automatically |
| Mail on iPhone/iPad | **Open approval email in Mail — PDF attached** | Combined PDF converted to a browser `File` and passed to Web Share | Approver email copied for pasting into `To`; displayed if copy fails | Select Outlook or use collapsed PDF/email fallbacks if Web Share is unavailable |
| Generic fallback | **Open a new email without attachments** inside collapsed expander | No attachment | `mailto:` contains reviewed recipient, subject, and body | Direct PDF download is beside it in the same expander |

The generic fallback must continue to say that it has no attachments. Do not
rename it in a way that implies the PDF is present.

## 5. End-to-end data flow

### 5.1 Shared report inputs

The email handoff begins only after a valid `ExpensePackage` exists. Relevant
fields are:

- `package.basename`: stable generated-file base name;
- `package.pdf_bytes`: completed signed form plus receipt pages;
- `package.workbook_bytes`: editable workbook, not an email attachment;
- `package.total`: reviewed reimbursement total;
- `details.approver_name` and `details.approver_email`: reviewed, account-scoped
  approver identity;
- reviewed employee/account fields used by the subject and body builder.

### 5.2 Subject and body

`app.expense_ui._expense_email_subject_and_body(details, package)` produces the
same reviewed subject and plain-text body for all destinations. Destination
selection must not alter business content.

### 5.3 Outlook path

The Outlook flow is:

```text
ExpensePackage.pdf_bytes
  -> email_attachments_for_package(package)
  -> [("<basename>.pdf", pdf_bytes)]
  -> app.expense_ui._build_expense_eml(...)
  -> app.eml_builder.build_eml(...)
  -> RFC email with X-Unsent: 1 and one MIME PDF attachment
  -> Streamlit download button
  -> Outlook for Windows or Outlook on the web
```

`X-Unsent: 1` requests draft/compose behavior. The `From` header remains blank
so Outlook supplies the signed-in employee. The HTML body is base64 encoded to
avoid quoted-printable corruption previously observed during Outlook Web
`.eml` import.

### 5.4 iOS/iPadOS path

The Apple-mobile flow is:

```text
ExpensePackage.pdf_bytes
  -> email_attachments_for_package(package)
  -> app.expense_ui._ios_mail_share_payload(...)
  -> base64 file record {name, mime, b64}
  -> same-origin Streamlit component render message
  -> atob + Uint8Array + Blob + File
  -> navigator.canShare({files})
  -> employee tap
  -> copy reviewed approver email
  -> navigator.share({files, title, text})
  -> employee selects Mail or Outlook and reviews draft
```

The call to `navigator.share()` remains directly inside the click handler. Do
not place an awaited clipboard operation, network operation, or Streamlit rerun
before it: browsers require transient user activation for Web Share.

## 6. File-by-file implementation map

### 6.1 `app/expense_ui.py`

Changed responsibilities:

- Imports `base64`, `mimetypes`, and `streamlit.components.v1`.
- Declares `_IOS_MAIL_SHARE_FRONTEND` at
  `app/components/expense_ios_mail_share`.
- Declares `_IOS_MAIL_SHARE_COMPONENT` using a filesystem `path`, causing
  Streamlit to serve the component from the app's own origin.
- Renames destination labels so attachment state is explicit:
  - `Outlook for Windows (PDF attached)`
  - `Outlook on the web (PDF attached)`
  - `Mail on iPhone / iPad (PDF attached)`
- Routes both Outlook choices to the existing attachment-bearing `eml_bytes`.
- Replaces the Outlook Web compose URL with the `.eml` action.
- Replaces the primary iOS `mailto:` action with
  `_render_ios_mail_share(...)`.
- Retains `build_mailto_url(...)` only inside the collapsed secondary options.
- Adds `_ios_mail_share_payload(...)`, which serializes attachment name, MIME
  type, and base64 bytes as structured component arguments.
- Updates user messages so no primary route instructs manual attachment.

Important invariant: `_render_generated_package(...)` must call
`email_attachments_for_package(package)` for the iOS action. That helper returns
the PDF only. Do not pass `package.workbook_bytes` unless the product owner
explicitly changes the submission policy.

### 6.2 `app/components/expense_ios_mail_share/index.html`

This new dependency-free frontend performs five jobs:

1. Completes Streamlit's component handshake using
   `streamlit:componentReady` and `streamlit:render` messages.
2. Reconstructs each serialized attachment as a browser `File`.
3. Enables the primary button only if
   `navigator.canShare({files})` returns true.
4. Copies or displays the approver email, then invokes
   `navigator.share({files, title, text})` from the user's tap.
5. Shows a specific fallback message for capability, decoding, or share errors.

Security and isolation controls:

- no external scripts, stylesheets, fonts, analytics, or network requests;
- derives the expected parent origin from Streamlit's `streamlitUrl` query
  parameter;
- ignores messages not sent by `window.parent`;
- rejects a mismatched parent origin when one is known;
- receives user values through structured component arguments rather than
  interpolating them into executable HTML;
- uses `textContent`, not `innerHTML`, for dynamic status text.

Accessibility and touch controls:

- native `<button type="button">`;
- 48-pixel minimum touch height;
- visible disabled state;
- status paragraph uses `role="status"`;
- component iframe receives `tab_index=0`;
- no horizontal overflow at the tested 820-pixel iPad viewport.

### 6.3 `app/eml_builder.py`

- Deletes `build_outlook_web_url(...)` because that URL could prefill content
  but could not carry local attachment bytes.
- Removes the now-unused `urlencode` import.
- Clarifies that Web Share, not `mailto:`, is the primary iOS attachment path.
- Retains `build_mailto_url(...)` only for the explicitly attachment-free
  secondary fallback.

Do not restore `build_outlook_web_url(...)` as the primary Outlook Web action.
Doing so silently reintroduces the missing-attachment defect.

### 6.4 `tests/test_web_ui_app.py`

- Updates platform defaults to the explicit attachment-bearing labels.
- Verifies `_ios_mail_share_payload(...)` preserves recipient, subject, body,
  PDF filename, MIME type, and bytes.
- Verifies the component contains capability detection, Web Share invocation,
  approver-copy behavior, Streamlit handshake, parent checks, and PDF wording.
- Guards against regression to `components.html`, whose opaque origin is not a
  safe Web Share context.
- Verifies Outlook Web exposes an attachment-bearing download action rather
  than a compose URL.
- Verifies the iOS route does not expose a competing primary Streamlit download
  or link button; the custom component owns that action.

### 6.5 `tests/test_eml_builder.py`

- Removes the obsolete Outlook Web compose-URL test and import.
- Existing `.eml` tests continue to cover `X-Unsent`, body encoding, and MIME
  behavior.

### 6.6 Documentation files

- `README.md` now describes attached `.eml` and Web Share behavior and removes
  the inaccurate manual-attachment instruction.
- `docs/EXPENSE_REIMBURSEMENT_WORKFLOW_2026-08-11.md` records the platform
  architecture, first-party component rationale, failure controls, and rendered
  acceptance evidence.
- `docs/ENFRA_IT_AI_API_REVIEW_EMAIL_2026-08-11.md` explicitly separates the
  client-side attachment handoff from AI/API processing. Attachment bytes are
  not sent to the model or to an email service.

## 7. Required invariants for later changes

The following requirements use RFC 2119-style language for clarity:

1. The approval email **MUST** attach the combined submission PDF, not the Excel
   workbook, in the normal Outlook and iOS paths.
2. The Excel workbook **MUST** remain downloadable for optional edits.
3. The application **MUST NOT** send the email automatically.
4. The employee **MUST** retain a review step before sending.
5. Outlook Web **MUST NOT** regress to a compose URL that claims to include a
   local attachment.
6. The generic `mailto:` action **MUST** remain labeled attachment-free.
7. Web Share **MUST** be invoked from a direct user gesture.
8. The iOS share button **MUST** remain disabled when file sharing is not
   supported.
9. A user-cancelled share sheet (`AbortError`) **MUST NOT** be presented as an
   application failure.
10. A non-cancellation share error **MUST** produce visible recovery guidance.
11. Approver name/email memory **MUST** remain scoped to the account and paired
    identity; this commit does not relax memory isolation.
12. Editing report inputs **MUST** continue to invalidate stale generated
    outputs before the approval action is shown.
13. Dynamic report content **MUST NOT** be inserted into executable component
    HTML.
14. Optional integrations **MUST** remain inert until their environment
    configuration exists.
15. No credential, production endpoint, real receipt, or generated report
    **MAY** be committed to the public repository.

## 8. Failure-mode inventory and controls

| Failure mode | Detection | Current control | User recovery |
|---|---|---|---|
| Combined PDF generation fails | `package.pdf_bytes` unavailable / package has PDF error | Attached email action is withheld; Excel remains available | Correct renderer/dependency issue or download Excel for edits, then regenerate |
| `.eml` construction fails | Exception captured during generation | Outlook destinations warn instead of producing a corrupt draft; iOS can still use `package.pdf_bytes` | Select iPhone/iPad share on that device or regenerate |
| Outlook browser downloads instead of opening `.eml` | Browser-native behavior | Caption explains the next action | Open the file in Outlook; for Outlook Web, drag it onto the reading pane |
| Outlook file association points elsewhere | Operating-system behavior | `.eml` remains a standards-based downloadable artifact | Use Open with Outlook or Outlook Web drag/drop |
| `navigator.canShare` absent | Capability check returns false | Share button disables before the employee can invoke it | Select an Outlook route or use collapsed options |
| Browser supports text share but not file share | `navigator.canShare({files})` returns false | Same disabled state; no false attachment claim | Select an Outlook route or use collapsed options |
| Component receives corrupt base64/file data | Decode or `File` construction throws | Component catches error, disables button, and displays recovery text | Regenerate or use an Outlook route |
| Employee closes share sheet | Promise rejects with `AbortError` | No error message replaces the normal instructions | Tap the button again when ready |
| Share sheet fails for another reason | Non-`AbortError` rejection | Visible error directs user to Outlook/collapsed options | Use indicated fallback |
| Clipboard copy denied | `document.execCommand("copy")` returns false or throws | Exact approver email is displayed in status text | Enter the displayed address manually |
| Web Share loses transient activation | Usually `NotAllowedError` | Current code performs only synchronous copy work before `navigator.share()` | Preserve direct click structure; do not await before share |
| Opaque/third-party iframe blocks Web Share | Permission-policy behavior | Component is served from the same origin as the app | Do not replace declared component with `components.html` |
| Device is misdetected | Destination default is wrong | Destination selector remains visible and editable | Choose correct destination |
| Target mail app ignores `title` as subject | Share-target-specific mapping | Body and PDF still pass; employee reviews draft | Enter/correct subject before send |
| Attachment exceeds target mail limit | Existing package size warning | Warning is visible; tool does not silently remove PDF | Reduce receipt packet or use organization-approved large-file process |
| Employee edits inputs after generation | Existing content fingerprint mismatch | Generated actions/downloads are suppressed until regeneration | Regenerate from reviewed values |
| Employee chooses generic email fallback | Explicit attachment-free label | No claim that attachment is present; PDF download is in same expander | Attach downloaded PDF manually only in this fallback path |

## 9. Security and public-repository review

### 9.1 Data boundaries

- The Python process already holds generated PDF bytes in the Streamlit session.
- Outlook `.eml` construction occurs locally in the application process.
- The iOS payload passes from the Streamlit process to a same-origin component
  over Streamlit's component protocol.
- The component reconstructs a `File` in browser memory.
- `navigator.share()` hands that file to the operating-system share sheet.
- No application-controlled email server receives the PDF.
- No attachment data is included in the AI receipt-analysis request by this
  handoff code.

### 9.2 Public-tree controls

The new component is static source code and contains:

- no email addresses;
- no API keys or tokens;
- no Smartsheet identifiers;
- no production endpoints;
- no receipt/report samples;
- no external dependency URLs.

After the component was staged, `tests/test_public_repository_hygiene.py`
passed all three tests, ensuring the new tracked file participated in the scan.

### 9.3 Memory and payload size

Base64 expands the PDF payload by approximately one third and the component
then creates decoded browser objects. This is transient browser memory, not
persistent storage. Do not duplicate the base64 payload into additional DOM
attributes, logs, or session keys. If report-size limits are raised later,
re-test peak memory on iPadOS before shipping.

## 10. Verification evidence

### 10.1 Repository tests

Commands run from the repository root:

```text
python -m pytest -q
272 passed in 23.97s

python -m py_compile app/*.py
silent success

python -m pytest -q tests/test_public_repository_hygiene.py
3 passed

git diff --check
silent success
```

### 10.2 Rendered browser acceptance fixture

An external temporary Puppeteer/Chromium fixture rendered the generated-package
screen against the local Streamlit application. The fixture itself was not
committed to the production repository.

Profiles exercised:

| Browser identity | Viewport | Expected default | Result |
|---|---:|---|---|
| Windows Chrome | 1440×900 | Outlook for Windows, PDF attached | Passed |
| Windows Edge | 1440×900 | Outlook for Windows, PDF attached | Passed |
| iPad Safari identity | 820×1180, touch enabled, DPR 2 | Mail on iPhone/iPad, PDF attached | Passed |

Assertions included:

- exactly one visible primary completion action;
- secondary downloads remained in the closed expander;
- correct destination default for each identity;
- no page or component horizontal overflow;
- primary button retained the approved dark-text/yellow-background treatment;
- 48-pixel iPad touch target;
- component origin exactly matched application origin;
- iPad click invoked the mocked share API from the button;
- share payload contained exactly one nonempty file;
- file name ended in `.pdf`;
- MIME type was `application/pdf`;
- subject contained `expense report`;
- body contained the reviewed reimbursement total.

A second run without mocked Web Share support verified:

- the share button was disabled;
- the status explained that the browser could not share the PDF directly;
- the component remained same-origin;
- Outlook and collapsed recovery paths remained available.

This automated run emulated iPad Safari identity and touch behavior in
Chromium; it was not a physical Safari/WebKit device run. The architecture was
changed specifically to conform to WebKit's documented first-party iframe
permission model, and the product owner reported that the same browser-file
handoff already works in the purchase workflow.

### 10.3 Continuous integration

GitHub Actions run `31526452178` completed successfully for the shipped commit:

<https://github.com/evanroden/msapo-generator/actions/runs/31526452178>

## 11. Acceptance criteria and observed result

| Acceptance criterion | Result |
|---|---|
| Windows Outlook draft contains combined PDF | Passed through existing MIME attachment tests and generated-package path |
| Outlook Web no longer uses attachment-free compose URL | Passed; helper and UI branch removed |
| Outlook Web control provides attached `.eml` | Passed in Streamlit application test |
| iPhone/iPad primary path includes PDF | Passed through payload unit test and rendered invoked-share inspection |
| iPhone/iPad component is first-party | Passed through rendered origin comparison |
| Unsupported file sharing does not falsely claim success | Passed through rendered no-share test |
| Excel remains optional and outside email attachment set | Passed through existing expense package/email tests |
| Secondary controls remain collapsed | Passed in Streamlit and rendered browser tests |
| No new public-repository secret/private artifact | Passed public-tree hygiene suite |
| Existing purchase and expense regressions remain green | Passed full 272-test suite |

## 12. Known limitations

1. Web Share does not define a recipient field. Copying/displaying the approver
   address is intentional.
2. Share targets decide how to map `title` and `text`. Mail and Outlook may
   present them differently across OS versions.
3. `.eml` open/import behavior can be affected by browser download settings,
   Windows file associations, and organizational Outlook policies.
4. Email attachment limits vary. The existing warning does not guarantee that
   every selected mail target will accept a large report.
5. Browser-level iPad acceptance used Chromium with iPad identity because a
   physical iPad automation target was not available in the build environment.
6. The component currently base64-serializes the generated PDF. This is simple
   and compatible but increases transient memory usage.
7. The custom component is expense-specific. A future refactor may share it
   with another workflow only if behavior, attachment policy, and tests remain
   explicit for each caller.

## 13. Safe future changes

### 13.1 Adding another mail target

Before adding a destination, answer all of these in code and tests:

1. Can the target receive local attachment bytes in the primary action?
2. Which exact report artifact is supplied?
3. Can recipient, subject, and body be passed?
4. What happens when the target is unavailable?
5. Does the action still require a user review before send?
6. Does it add credentials, OAuth scopes, or external data transmission?
7. What platform becomes the default, if any?

Never label a URL-only compose action as attachment-bearing.

### 13.2 Refactoring the component

A component refactor is safe only if tests continue to prove:

- same-origin serving or an explicit valid `web-share` iframe permission;
- direct click-to-`navigator.share()` activation;
- `navigator.canShare({files})` gating;
- PDF-only attachment policy;
- exact parent-source/origin validation;
- no executable interpolation of report content;
- disabled/error/cancel states;
- 48-pixel touch target and no iPad overflow.

### 13.3 Replacing `.eml`

A future Graph/Outlook integration could remove the download/import step, but
it is a separate security and product change. It would require explicit
authorization, tenant configuration, scopes, draft-only enforcement, recipient
validation, attachment verification, token storage rules, audit logging, and a
fallback. Do not silently substitute such an integration for this commit.

## 14. Regression triage keywords

Use the following mapping when diagnosing later reports:

| User report | First code area to inspect |
|---|---|
| “PDF missing in Outlook” | `_build_expense_eml`, `email_attachments_for_package`, `build_eml` |
| “Outlook Web opens blank compose” | `_render_generated_package`; verify compose URL was not restored |
| “Share button is gray on iPad” | component `directShareIsAvailable`, iframe origin, PDF payload validity |
| “Tapping share does nothing” | transient activation, `navigator.share` rejection, component origin |
| “Wrong person in To” | reviewed approver fields and account-scoped recall; on iOS verify copied/displayed address |
| “Excel was attached” | `email_attachments_for_package`; must return PDF only |
| “Two main buttons are showing” | `_render_generated_package` destination branch and collapsed expander |
| “iPad page is too wide” | component button CSS, iframe width, global mobile CSS |
| “Component never appears” | Streamlit component handshake and `/component/.../index.html` route |
| “Old report was shared” | generated-content fingerprint invalidation/session state |

## 15. Commit relationship and rollback

The implementation is one fast-forward commit on `main`:

```text
df308e330c62d666c056dc80a2a222e15227cb01
  -> 96238d3b68717f709b8b068ba52a981fec7d6868
```

If rollback is explicitly required, revert the implementation commit with a
new revert commit; do not force-rewrite public `main`. A rollback restores the
manual-attachment defect, so the revert description must state that Outlook Web
and iOS again require manual PDF handling. Preserve this note as historical
context even if implementation changes later.

## 16. Summary for the next coding agent

The normal expense email flow is intentionally attachment-bearing. Outlook uses
an unsent MIME `.eml`; iOS/iPadOS uses a same-origin Web Share component that
constructs and shares the generated PDF as a browser `File`. The Excel file is
optional and never attached. `mailto:` is a collapsed, explicitly
attachment-free fallback. Do not replace these paths with compose URLs, do not
move Web Share back into an opaque `components.html` iframe, and do not add an
awaited operation before `navigator.share()`. Preserve account-scoped approver
memory, stale-output invalidation, public-repository hygiene, and the employee's
final review/send step.
