# Unified RRH review, ENFRA brand, and browser hardening

**Date:** 2026-08-09  
**Status:** current implementation and release notes; corrected 2026-08-10  
**Audience:** ENFRA RRH operators, maintainers, reviewers, and future coding agents  
**Builds on:**
[`STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md`](STREAMLINED_RRH_PO_WORKFLOW_HANDOFF_2026-08-08.md)
and
[`RRH_STREAMLINING_AND_HARDENING_2026-08-08.md`](RRH_STREAMLINING_AND_HARDENING_2026-08-08.md)

This document is authoritative for the current three-step page, exception-only
questions, ENFRA visual treatment, browser behavior, and Smartsheet handoff.
The underlying approved routing matrix and full-asset-code policy remain unchanged.

## 1. Result

The normal RRH path is now:

1. **Provide the vendor quote.** Upload the original quote or paste its text.
2. **Review and complete the request.** The tool shows a compact summary and
   asks only questions it could not answer. Values it already supplied remain
   in a collapsed correction panel.
3. **Generate files and open Smartsheet.** One button creates the original-quote
   attachment, branded Scope/Inclusions/Exclusions PDF, and prefilled Smartsheet
   link.

The former extracted-work and PO-detail steps are one review step. There is no
tax confirmation checkbox, requester-forget button, separate document button,
separate Smartsheet button, or normal-path copy/paste worksheet.

## 2. Step 2 placement rules

Field placement is based on whether the tool has a safe usable value, not on a
fixed list of always-visible controls.

| State | Placement | Behavior |
|---|---|---|
| Missing or invalid required value | Visible under **Needed from you** | Generation remains disabled |
| Ambiguous asset at a configured site | Visible explicit asset/No asset choice | A placeholder can never be exported |
| Missing vendor representative name | Visible under **Needed from you** | Generation remains disabled |
| Missing or invalid vendor representative email | Visible under **Needed from you** | Generation remains disabled |
| AI/deterministic value already available | **Change a value the tool already filled** expander | Remains editable without cluttering the normal path |
| Blank Additional Information note | Not rendered | One deliberate note toggle can expose it |
| Requester / Asset Manager | Always visible | Device-and-account memory normally prepopulates it |

Questions are sticky for the life of the analyzed quote. If the operator fills
an initially blank amount and commits the input, it stays in the visible review
area instead of jumping into the collapsed correction panel. New questions can
appear as dependencies become known—for example, choosing a site can reveal
that its asset match is ambiguous.

The collapsed correction panel contains only values the tool guessed or
defaulted. Blank unresolved boxes are never stranded there.

## 3. What the tool supplies automatically

| Decision | Primary source | Deterministic safety boundary |
|---|---|---|
| ENFRA account and site | Facility text plus configured account/site catalog | Unknown or non-unique routing stays visible |
| Work category and cost code | Analyzer category plus site mapping | Missing mapping is never invented |
| New PO vs. change order | Quote language | Change order requires Original PO Number |
| How work is performed | Analyzer route guess | Negation-aware labor/rental/Group A/material fallback |
| Object Account and Agreement Type | Canonical route-and-amount matrix | Operator cannot manually create an unsupported pairing |
| Job number | Exact account-filtered Smartsheet catalog; RRH O&M default | Free text is rejected; an exact quoted identifier may select one unique option |
| Specific asset | Quote clue plus selected-site asset registry | Only a unique configured UID is selected |
| Vendor, contact, final total, description | Structured quote extraction | Required gaps are visible and block generation |
| Requester / Asset Manager | Current browser plus exact account memory | Stored only after a verified package |

The three job options beginning `Unity` belong to Unity Health System in
Arkansas. Rochester-area Unity Hospital and Unity Specialty Hospital remain RRH
sites and use RRH-prefixed job values. See
[`JOB_NUMBER_CATALOG_AND_UNITY_DISAMBIGUATION_2026-08-10.md`](JOB_NUMBER_CATALOG_AND_UNITY_DISAMBIGUATION_2026-08-10.md).

### Vendor representative memory

Vendor representative name and email are required workflow fields. The tool
uses the current quote first. When either value is absent, it looks up the
most-used, most-recent verified name/email pair for the exact account and
normalized vendor. Case, punctuation, whitespace, and legal suffix differences
such as `Inc.` do not prevent a match; a merely similar company name does.

The remembered pair is seeded only into blank values and remains editable in
the correction panel. Each successfully generated package records one
idempotent vendor-contact event. Regenerating the same package does not inflate
the count, and correcting the representative moves that package's event to the
corrected pair. Legacy vendor history remains readable. Contact memory never
crosses account boundaries.

The active asset field exports the complete configured asset UID, including all
letters, prefixes, and separators. It does not shorten the UID to the unknown
five- or six-digit code mentioned in earlier feedback.

## 4. Amount, tax, description, and notes

### Description of Work

The UI limits the short description to 20 characters. The context builder
truncates it again, and Smartsheet validation rejects any later value above the
limit. The full work description remains in the supporting PDF.

### Tax

There is no confirmation checkbox. A prominent Safety Yellow alert appears
unless the quote analysis finds tax included:

- **Tax excluded:** warns that the quote explicitly excludes tax and asks the
  operator to make the PO/CO amount all-inclusive.
- **Tax unclear:** states that no tax was found and asks the operator to verify
  whether it applies.
- **Tax included:** no extra alert is shown.

The alert is advisory and accessible (`role="alert"`). The hard gate is the
final PO/CO amount: it must be a conventional positive currency value on every
purchase route. Additional Information remains blank unless the operator adds
a reviewer-relevant note; tax wording is not copied there.

## 5. Brand-aligned alpha treatment

The supplied ENFRA brand guide is applied without adding the logo or presenting
the alpha workflow as an official ENFRA application. The visible page kicker is
the neutral `PURCHASE ORDER WORKFLOW`, and the PDF running header is the neutral
`PURCHASE ORDER SUPPORT`. The browser title is also neutral.

| Brand token | Value | Use |
|---|---|---|
| Ocean Steel | `#092B24` | Hero, headings, summaries, primary structure |
| Blue Steel | `#557F7F` | Secondary text, borders, PDF running label |
| Iced Steel | `#D3E7E0` | Page wash, field backgrounds, facility banner |
| Concrete | `#D3CCC4` | Neutral borders and dividers |
| Safety Yellow | `#D6EF4B` | Primary actions, step emphasis, focus, tax warning |
| Dark Iron | `#000000` | Body text |

Arial is the approved system fallback and avoids a render-blocking external-font
dependency. The same palette is used in the generated PDF: Safety Yellow top
rule, Blue Steel running label/page number, and Ocean Steel section headings.
No ENFRA name, logo file, logo approximation, or unapproved font is embedded in
those visible top-level brand positions during alpha.

## 6. Smartsheet and attachments

### New-tab behavior

The primary handoff uses Streamlit's native external-link button. It renders an
anchor with `target="_blank"`, so supported browsers open the form in a new tab.
The custom iframe is retained only inside the collapsed manual troubleshooting
fallback.

The handoff reminds the operator that:

- Smartsheet should have been opened or signed into within the last few hours;
- if prefilling fails, sign back in, return to the generator, and use the same
  button again;
- the link fills fields but does not submit the form; and
- the original quote and Scope/Inclusions/Exclusions PDF must both be uploaded
  near the end of the form.

On iPhone or iPad, iOS may hand the normal HTTPS Smartsheet link to the installed,
signed-in Smartsheet app. The application does not promise or force this: no
documented Smartsheet app-only URL scheme was found, and universal-link routing
is controlled by iOS, the installed app, prior user choices, and Smartsheet.

### Can the generated files be dragged directly into Smartsheet?

Not reliably from one browser tab to another. A generated in-memory browser
object is not a normal operating-system file, and cross-origin/cross-tab drag
payloads are restricted differently by Chromium and WebKit. Chrome's current
Downloads bubble is also not a dependable drag source. Treating this as the
primary path would create a browser-specific failure mode.

The reliable current shortcuts are:

- **Windows Chrome/Edge:** save both files, open the Downloads folder in File
  Explorer, select both files, and drag them together onto Smartsheet's
  attachment box.
- **iPhone/iPad:** use the Smartsheet attachment picker and select both files
  from Files.

The reliable future way to remove manual attachment handling is an authenticated
Smartsheet API flow that creates or reconciles a row, receives the row ID, and
attaches both byte streams. The repository already has guarded row/attachment
code, but production activation still requires identity, authorization, exact
column specifications, a least-privilege token, a submission-key column, and a
controlled acceptance test.

## 7. Browser hardening and verification boundary

### Automated application tests

The locally available Python suite has **148 passing tests**. It includes a real Streamlit AppTest
quick path that loads synthetic quote data, enters the requester, generates both
downloads, and verifies the encoded native Smartsheet link without submitting
anything. A second AppTest supplies an intentionally incomplete analysis and
verifies that unresolved blank fields are visible, remain stable after input,
and are absent from the collapsed correction panel.

### Rendered Chromium matrix

An actual headless Chromium 149 binary rendered and exercised these profiles:

| Profile | Viewport/input | Result |
|---|---|---|
| Windows Chrome | 1440×900, Chrome UA | Passed |
| Windows Edge | 1440×900, Edge UA | Passed |
| iPhone-sized | 390×844, touch, mobile Safari UA | Passed responsive/touch checks in Chromium |
| iPad-sized | 820×1180, touch, mobile Safari UA | Passed responsive/touch checks in Chromium |

Every profile completed the same synthetic interaction and verified:

- no application page exceptions;
- no horizontal overflow;
- one enabled final generation action;
- exactly two download controls;
- a Smartsheet anchor with `target="_blank"`;
- a 46-pixel primary target; and
- 16-pixel form text on touch profiles to prevent iOS focus zoom.

The 2026-08-10 correction reran all four profiles on Chromium 149 and also
verified zero expander border widths, no expander shadow, no optional wording
on required contact fields, both required representative labels, and no page
errors or horizontal overflow.

A separate browser test downloaded both artifacts and verified non-empty quote
and PDF files. It safely intercepted the Smartsheet URL, clicked the handoff,
and confirmed that a separate page opened with the expected prefilled URL.

### What still needs physical-device acceptance

Chromium viewport emulation is not WebKit. Before declaring a broad production
rollout complete, run the synthetic checklist on:

1. a current iPhone in Safari;
2. a current iPad in Safari;
3. the installed Smartsheet iOS/iPadOS app while signed in;
4. current Google Chrome on an ENFRA-managed Windows computer; and
5. current Microsoft Edge on an ENFRA-managed Windows computer.

Do not submit the synthetic form. Confirm only layout, both downloads, new-tab
or expected app handoff, prefilled values, and attachment selection.

## 8. Failure modes found and controls

| ID | Severity | Failure mode | Control |
|---|---|---|---|
| UBR-01 | High | Blank unresolved fields could remain hidden with guessed fields | Pure review classifier places every gap visibly |
| UBR-02 | Medium | A completed visible field could jump into the collapsed panel after rerun | Per-quote sticky question placement |
| UBR-03 | Critical | Ambiguous asset could silently become no asset or leak a placeholder | Explicit visible choice, generation block, export normalization |
| UBR-04 | High | No visible tax cue when the quote did not mention tax | Prominent accessible Safety Yellow alert |
| UBR-05 | Medium | Blank Additional Information added noise to every request | Omitted until its deliberate note toggle is opened |
| UBR-06 | Medium | Invalid total produced two overlapping messages and double punctuation | One normalized amount instruction |
| UBR-07 | High | A generic iframe/link implementation could fail to open a stable new tab | Native `st.link_button` plus target regression and browser test |
| UBR-08 | High | Operator could assume URL prefilling also uploads or submits | Explicit non-submit/non-attach wording and two-file reminder |
| UBR-09 | Medium | Chrome Downloads bubble drag behavior is inconsistent | File Explorer drag guidance; no direct-drag promise |
| UBR-10 | Medium | iOS input text remained 14px and could trigger focus zoom | Coarse-pointer 16px form-control rule found by rendered test |
| UBR-11 | High | A hidden test path could load real customer data or accidentally submit | The owner-requested discreet control loads only a static synthetic quote, calls no AI service, and never submits |
| UBR-12 | Medium | External brand fonts could block or vary rendering | Approved Arial fallback with no font-network dependency |
| UBR-13 | High | A current catalog could remove an asset still stored in an old session | Sanitize asset state against fresh options before rendering |
| UBR-14 | Critical | Required value could be skipped by URL length/mapping but link still shown | Existing required-encoded-field gate withholds the link |
| UBR-15 | Critical | A field edit could leave old files/link visible | Existing PDF signature and context ID require regeneration |
| UBR-16 | High | Missing vendor representative fields were mislabeled optional | Both fields are required, visible when unresolved, and block generation |
| UBR-17 | Medium | Custom and native expander borders created doubled mobile edges | Compact native expanders plus removal of the custom outer border |
| UBR-18 | High | Vendor history was stored but the active UI neither recalled nor updated it | Account/vendor lookup during review plus idempotent recording after verified generation |

## 9. Residual risks

| Risk | Current mitigation | Remaining dependency |
|---|---|---|
| Plausible but wrong AI guess | Visible vendor/site/amount cards, route/account/asset summary, correction panel | Confidence calibration and operator review |
| Smartsheet label or option drift | Exact field mappings, required encoding, hidden manual fallback | External form-owner change notification or schema health check |
| Stale Smartsheet login | Recent-login and retry instructions | Smartsheet authentication behavior |
| iOS app does not claim the link | HTTPS link still opens in a browser tab | iOS universal-link state and Smartsheet app |
| Files omitted at final submission | Two labeled files and repeated upload reminder | Smartsheet form cannot receive attachments by custom URL |
| Shared browser remembers another user | Requester stays visible/editable; memory scoped to device+account | Browser cookie is not personal authentication |
| Incomplete cost-code catalog | Missing code remains visible and blocks generation | Product owner will supply remaining codes later |
| WebKit-only rendering issue | Conservative CSS, safe-area support, touch sizing | Physical iPhone/iPad Safari acceptance |

## 10. Further streamlining roadmap

The next improvements should remove repeated decisions without hiding material
uncertainty.

### Priority 1 — Import the complete site/cost-code catalog

**Operator effect:** account, site, work category, and cost code disappear from
the normal path whenever the quote gives a unique site/category match.

**Implementation:** use one validated registry keyed by account, site, and work
category. Preserve codes as text, reject duplicates/blanks, and produce an
add/change/remove report before deployment. Do not let a fuzzy site name select
a code across accounts.

**Safety tests:** every supplied row, duplicate keys, leading zeroes, renamed
sites, unknown categories, and stale sessions after catalog replacement.

### Priority 2 — Add calibrated field confidence

**Operator effect:** the page asks only about low-confidence account, site,
route, request type, amount, or asset choices instead of treating every valid
guess equally.

**Implementation:** make the analyzer return a confidence value and short
evidence for each material decision. Calibrate thresholds against a saved,
sanitized quote set. Confidence must decide visibility only; deterministic
routing, amount, asset-registry, and export rules remain authoritative.

**Safety tests:** measure false-hide rate, not just extraction accuracy. A
plausible wrong field hidden from the user is worse than a visible blank.

### Priority 3 — Extend account-manager convenience for shared devices

**Operator effect:** a shared RRH tablet can show a compact recent-manager
selector instead of always using only the last person.

**Implementation:** retain at most three verified names for the exact
device/account pair, ordered by recent successful packages. Keep requester
visible and editable. Do not create a company-wide employee directory from
anonymous device memory.

**Safety tests:** account isolation, browser isolation, correction of the same
package, storage failure, name length, and multiple users on one device.

### Delivered 2026-08-10 — Reuse verified recurring vendor details

**Operator effect:** a missing vendor contact can be supplied from prior verified
requests for the same normalized vendor and account.

**Implementation:** quote data wins, memory fills only missing values, exact
account isolation is enforced, the remembered source is disclosed, legal vendor
suffixes are normalized conservatively, and package events are idempotent.

**Remaining enhancement:** when a vendor has several active representatives,
show a compact ranked selector instead of silently taking only the leading pair.

### Priority 5 — Learn asset preference carefully

**Operator effect:** recurring work on the same device/account/site can rank a
previously confirmed asset higher when the quote provides a compatible clue.

**Implementation:** memory may break a close score only when the current quote
supports the same equipment tag/name. It must never override an exact quote
match, select across sites, or manufacture an asset when no clue exists.

### Priority 6 — Replace form-and-upload with authenticated Smartsheet submission

**Operator effect:** one final button creates the row and attaches both files;
there is no recent-login, download, upload, or manual Submit step.

**Implementation gates:** user authentication, account authorization,
least-privilege token, exact live column schema, dedicated submission key,
persistent idempotency leases, dry-run checks, attachment reconciliation, and a
one-account pilot. Reuse the existing fail-closed API adapter.

This produces the largest time reduction but also creates a remote financial
record, so it must follow—not precede—the identity and acceptance controls.

### Priority 7 — Add privacy-preserving correction telemetry

**Operator effect:** future releases improve the guesses that RRH users actually
correct most often.

**Implementation:** record only field name, whether a guess was changed, broad
account/site key, and analyzer version. Do not store quote text, prices, contact
data, asset IDs, or before/after values in telemetry. Review aggregate correction
rates before changing confidence thresholds.

### Priority 8 — Add a Smartsheet schema health check

**Operator effect:** maintainers learn that a field label or dropdown changed
before operators receive blank prefills.

**Implementation:** a non-writing scheduled check can validate the configured
form URL and, if authorized metadata is available, exact fields/options. Alert
on drift and keep the current required-field gate. Never use production row
creation as a health check.

## 11. Files changed in this release

- `app/web_ui.py` — unified review step, exception-only placement, sticky
  questions, brand-aligned alpha UI, touch/responsive rules, and a static
  synthetic workflow check containing no customer data.
- `app/workflow_review.py` — pure gap, email, tax, and sticky-placement rules.
- `app/memory.py` — account/vendor representative recall and idempotent learning.
- `app/po_context.py` — required representative warnings and stable memory event ID.
- `app/smartsheet.py` — representative fields added to required form prefills.
- `app/smartsheet_ui.py` — native new-tab link.
- `app/smartsheet_inline.py` — simplified two-file/new-tab handoff and platform
  attachment guidance.
- `app/po_rules.py` — unresolved asset placeholder cannot export.
- `app/scope_pdf.py` — brand-aligned supporting PDF with a neutral alpha header.
- `.streamlit/config.toml` — brand-guide theme palette.
- `.env.example` — non-secret deployment examples only; no synthetic-test
  setting is required because the built-in sample is static and local.
- tests — pure rule, AppTest, URL, PDF, brand, responsive, and handoff regressions.

## 12. Commit notes

Recommended commit grouping:

### Commit 1 — Unify RRH review and apply ENFRA brand

- combine extracted-work review and PO confirmation into one Step 2;
- keep only unresolved questions visible;
- retain completed exception fields in place across reruns;
- omit blank optional fields until requested;
- add prominent nonblocking tax alert;
- preserve full configured Asset IDs and the 20-character export cap;
- apply the approved ENFRA palette and Arial fallback to page and PDF; and
- provide the owner-requested discreet static test trigger without customer
  data, an AI request, or automatic submission.

### Commit 2 — Harden browser and Smartsheet handoff

- replace the primary custom link with a native new-tab control;
- clarify recent-login, retry, non-submit, non-attach, and two-file upload steps;
- use File Explorer/Files attachment guidance instead of unreliable browser-tab
  drag claims;
- add safe-area, mobile stacking, touch target, and iOS input-size controls;
- add sticky-question, tax, asset-placeholder, full AppTest, and browser-contract
  regressions; and
- record the rendered Chromium matrix and remaining physical-device acceptance.

### Commit 3 — Require and recall vendor representatives; repair mobile expanders

- make vendor representative name and email required instead of optional;
- keep unresolved representative fields visible and generation-blocking;
- fill missing representative data from verified account/vendor history;
- record one correction-safe, idempotent memory event per generated package;
- retain legacy vendor-contact history and enforce account isolation;
- remove the combined optional-contact/note toggle while retaining the genuinely
  optional Additional Information toggle;
- remove misleading optional wording from the scope review disclosure; and
- use compact native expanders and remove the duplicated custom mobile border.

### Commit 4 — Neutralize alpha-facing product labels

- replace the top-of-page `ENFRA WORKFLOW` kicker with the neutral
  `PURCHASE ORDER WORKFLOW` label;
- replace the generated PDF's `ENFRA | PURCHASE ORDER SUPPORT` running header
  with `PURCHASE ORDER SUPPORT`;
- keep the supplied palette, Arial fallback, hierarchy, and layout unchanged;
- retain operational ENFRA references where they identify actual account data,
  policies, configuration, or implementation ownership rather than product
  branding; and
- add regressions proving the visible alpha headers remain neutral while the
  approved visual tokens remain applied.
