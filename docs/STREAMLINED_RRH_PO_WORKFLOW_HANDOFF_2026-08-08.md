# Streamlined ENFRA RRH PO workflow and implementation handoff

**Status:** authoritative business policy; current UI supplement dated 2026-08-09  
**Policy date:** 2026-08-08  
**Primary audience:** future maintainers, reviewers, and AI coding agents  
**Applies to:** quote analysis, RRH PO classification, asset selection, requester memory, the two-file package, and Smartsheet custom-URL prefilling  
**Supersedes:** the business rules and operator flow in the 2026-08-06 PO workflow handoff wherever they conflict with this document

> **Current reliability supplement:**
> [`RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md`](RRH_UNIFIED_REVIEW_BRAND_BROWSER_HARDENING_2026-08-09.md)
> preserves these business rules while defining the current three-step UI,
> exception-only questions, ENFRA brand, browser behavior, and Smartsheet handoff.

Read this file before changing any PO route, Object Account, Agreement Type,
asset behavior, requester behavior, attachment, or Smartsheet field mapping.
The older documents remain useful incident history, especially for the `%20`
Smartsheet URL encoding correction, but they are no longer the source of truth
for the current operator experience.

## 1. Why this revision exists

Ashley reviewed the previous tool and corrected several business assumptions.
The product owner also asked for a substantially simpler workflow for people on
the ENFRA RRH account who may not know PO terminology or be comfortable with
technical tools.

The implementation uses the following supplied evidence:

- Ashley's annotated follow-up screenshots;
- live Smartsheet dropdown screenshots for Object Account and Agreement Type;
- the live Smartsheet form, inspected without submitting a request;
- the supplied `EQUIPMENT LIST - EQPO GROUP A` document; and
- the product owner's explicit overrides in the 2026-08-08 request.

No real Smartsheet request was submitted while validating the form.

## 2. Product-owner decisions that override earlier notes

These are non-negotiable unless the product owner changes them later:

1. Continue exporting the complete configured asset code at every site.
   Ashley referenced a five- or six-digit asset/JDE code, but no trusted mapping
   was supplied and the product owner does not know which code she meant. Do not
   strip prefixes, keep only digits, invent a mapping, or shorten the registry UID.
2. Description of Work is capped at 20 characters during export. The full scope
   belongs in the generated Scope/Inclusions/Exclusions PDF.
3. A change order must include the original PO number. A new PO must leave that
   field blank.
4. Delivery method does not decide Equipment versus Materials.
5. The user does not confirm tax with a checkbox.
6. Additional Information does not automatically state that tax is included.
7. There is no Forget requester button in the operator flow.
8. There is one final action, not separate document-generation and Smartsheet
   preparation actions.
9. Cost-code expansion for all sites is future work. Do not invent missing cost
   codes in this revision.

## 3. Operator outcome

The user should be able to upload a quote, accept mostly correct suggestions,
make only necessary corrections, and press one final button. The page then
shows exactly two downloads and one prefilled Smartsheet link.

The active page has three steps in the same order the operator uses them:

1. **Provide the vendor quote.** Upload the original file or paste the text.
2. **Review and complete the request.** Check the summary, answer only unresolved
   questions, and optionally correct AI/defaulted details or scope selections.
3. **Generate both files and the Smartsheet link.** One action creates the scope
   PDF, verifies the package, and reveals the downloads and link.

There is no separate Prepare Smartsheet button, email route, tax
confirmation checkbox, or Forget requester action.

## 4. Step 2 field order and defaults

The main screen asks for or shows fields in this order:

1. Contract/account.
2. Site, work category, and cost code.
3. Request type: New purchase order or Change order.
4. Original PO number, only when Change order is selected.
5. Requester / Asset Manager name.
6. Job number. RRH defaults to `RRH-695400022-O&M`.
7. How the work or purchase will be handled.
8. Specific site asset.
9. Final PO/CO amount including every fee and tax.
10. Vendor name.
11. Vendor contact name and email.
12. Short Description of Work, capped at 20 characters.
13. Optional Additional Information.

The classification result is then shown in plain language. Internal fields that
normally do not need attention are not duplicated as editable copy/paste inputs.

## 5. Request type and Original PO Number

The active tool supports these request types:

- `PO`
- `CHANGE ORDER`

The live form contains other options, but they are outside this PO preparation
workflow and are not offered by the application.

Rules:

| Request type | Original PO Number |
|---|---|
| `PO` | Forced blank and omitted from the URL, even if stale session state contains a value |
| `CHANGE ORDER` | Required and exported under the exact label `ORIGINAL PO NUMBER` |

The historical spelling `ORIGIONAL PO NUMBER` is not the current live form
label and must not be restored to active mappings.

## 6. Canonical classification policy

Labor and rentals take precedence. When neither applies, the supplied Group A
list decides Equipment; everything else is Materials.

| Internal route | Operator meaning | Object Account | Agreement Type |
|---|---|---|---|
| `onsite_labor` | Vendor performs labor/service onsite | `5511-SUBCONTRACTOR` | `03 - MSAPO (SERVICE)` |
| `onsite_rental` | Onsite rental service, such as a rental chiller or scissor lift | `5411-OUTSIDE RENTALS` | `03 - MRAPO (RENTAL)` |
| `equipment_purchase` | Buying a complete approved Group A equipment item with no vendor labor/rental | `5302-EQUIPMENT` | `OR - EQUIPMENT PO` |
| `materials_purchase` | Buying parts, supplies, consumables, or any non-Group-A item with no vendor labor/rental | `5301-MATERIALS` | Below `$25,000`: `ON - STANDARD PO UNDER $25K`; `$25,000` and above: `OR - STANDARD PO OVER $25K` |

The `$25,000` boundary is exact and conservative: `$24,999.99` is Under; exactly
`$25,000.00` is Over.

Who drives the item to the site is irrelevant to Equipment versus Materials.
A drop-off is not labor. Third-party shipping is not automatically Equipment.

## 7. Approved Group A equipment list

The source list is represented in `app/equipment_policy.py` and is embedded in
the AI prompt. It is the only approved no-labor Equipment list for this revision.

### Mechanical Equipment

- Air Handling Units (AHUs) / Rooftop Units (RTUs)
- Chillers
- Boilers
- Cooling Towers
- Heat Exchangers
- Pumps: chilled water, condenser water, and heating water
- VFDs for major equipment
- Terminal Units

### Electrical Equipment

- Generators
- Solar Panels
- Switchgear / Distribution Panels
- Transformers
- Uninterruptible Power Supply (UPS) Systems
- Automatic Transfer Switches (ATS)
- Motor Control Centers (MCCs)
- Power Monitoring or Load Shedding Equipment

### Building Automation / Controls

- BMS central servers and control panels
- Control valve assemblies linked to major mechanical systems
- Networked sensors for performance monitoring

### EaaS and Energy Infrastructure

- Battery Energy Storage Systems (BESS)
- Linear Generators
- Microgrid Control Systems
- Combined Heat and Power (CHP) Units
- Thermal Energy Storage Tanks
- Central Plant Optimization Controllers
- Inverter Systems for solar/battery integration
- Packaged Energy Systems / Modular Energy Plants

### Other Large or Custom Equipment

- Custom packaged mechanical skids, such as pre-piped pump or boiler skids
- Pre-fabricated pumping or heating stations
- Equipment requiring factory startup or commissioning support
- Long-lead equipment
- Owner-furnished, contractor-installed equipment

Loose gaskets, belts, filters, bearings, seals, chemicals, refrigerant,
consumables, and repair kits remain Materials even when they are used on a
Group A asset. Vendor labor still takes precedence when the quote includes both
equipment/parts and onsite work.

## 8. AI suggestions and deterministic controls

The analyzer must make a best-supported suggestion for:

- contract/site;
- work category;
- request type;
- original PO number for a clear change order;
- how the work/purchase is handled;
- a useful asset reference;
- vendor and contact details;
- all-in total; and
- a 20-character short description.

The operator may correct suggestions before generation. The UI no longer starts
the work-route dropdown at an empty placeholder.

If the model does not return a valid work route, `infer_purchase_route` supplies
a reviewable fallback. It looks for rental, labor/service, Group A equipment,
and finally Materials in that precedence order.

Asset selection uses a separate safety boundary:

1. The model may return a tag, model, or plain-English equipment clue.
2. Only assets configured for the chosen account and site are candidates.
3. Exact existing matchers run first.
4. A deterministic scorer uses the full UID, tag, equipment name, service area,
   and unit number.
5. The tool selects only a unique best match.
6. A tie or weak result becomes No asset applies; the tool never invents an ID
   or silently selects the first registry row.
7. The complete configured UID is exported unchanged when an asset is selected.

## 9. Requester / Asset Manager memory

The requester is entered before the final action. After the first verified
package, the app remembers the most recently used requester/asset manager for
that exact browser and ENFRA account.

Memory scope is `(anonymous device, account)`, not global:

- RRH memory never becomes the default for Tulane or another account.
- One browser's name never becomes another browser's default.
- A shared device can naturally adopt the latest successfully used person on
  that account without a separate Forget button.
- Re-rendering the Streamlit page does not inflate usage.
- Correcting the name for the same context moves the event instead of counting
  it twice.

The browser cookie contains only a random opaque token. The server hashes that
token before storing it. Requester name, quote, vendor, amount, and asset data
are not placed in the cookie. Blocked cookies disable only this convenience.

The older three-use requester tables remain readable for compatibility, but
the active UI neither consults them nor exposes their Forget action.

## 10. Description, amount, tax, and Additional Information

### Description of Work

- The operator control uses `max_chars=20`.
- Model output is truncated to 20 characters during normalization.
- `build_po_context` truncates again during export as the final safety boundary.
- Smartsheet validation rejects any downstream value over 20 characters.
- The complete scope remains in the generated PDF and internal reviewed scope.

The export is a maximum of 20 characters. It is not padded with meaningless
spaces when a shorter accurate description is available.

### Amount and tax

`PO/CO AMOUNT` is the final payable amount including stated tax, freight,
delivery, surcharges, and other fees. The prior tax-confirmation checkbox is
removed. Arithmetic validation still warns when separately extracted subtotal
plus tax does not equal the total.

### Additional Information

Additional Information is blank by default and contains only an operator-entered
note. The analyzer's `tax_note` and phrases such as “quote includes tax” are not
copied into this field.

## 11. Exact live dropdown options represented in code

### Object Account

- `NA`
- `5301-MATERIALS`
- `5490-OTHER`
- `5511-SUBCONTRACTOR`
- `5302-EQUIPMENT`
- `5411-OUTSIDE RENTALS`

### Agreement Type for PO

- `NA`
- `03 - MSAPO (SERVICE)`
- `03 - MRAPO (RENTAL)`
- `03 - CSAPO (CONSTRUCTION)`
- `ON - STANDARD PO UNDER $25K`
- `OR - STANDARD PO OVER $25K`
- `OR - EQUIPMENT PO`

The application represents the complete observed option sets for validation,
but its classification policy selects only the four approved outcomes in the
matrix above. It does not automatically choose `NA`, `5490-OTHER`, or CSAPO.

## 12. Smartsheet field rules

| Logical field | Exact visible label | Active behavior |
|---|---|---|
| `request_type` | `REQUEST TYPE` | `PO` or `CHANGE ORDER` |
| `requester_name` | `REQUESTER` | Current requester/asset manager |
| `job_number` | `JOB NUMBER` | RRH default or reviewed choice |
| `site_location` | `SITE NUMBER / LOCATION` | Reviewed site |
| `cost_code` | `COST CODE` | Existing configured or operator-supplied code |
| `object_account` | `OBJECT ACCOUNT` | Derived from the canonical matrix |
| `agreement_type` | `AGREEMENT TYPE FOR PO` | Derived from the canonical matrix |
| `original_po_number` | `ORIGINAL PO NUMBER` | Required for change order; omitted for PO |
| `total` | `PO/CO AMOUNT` | Final all-in amount |
| `vendor` | `VENDOR NAME` | AI-suggested, operator-correctable |
| `contact_name` | `VENDOR CONTACT NAME` | Suggested, optional correction |
| `contact_email` | `VENDOR CONTACT EMAIL` | Suggested, optional correction |
| `description_of_work` | `DESCRIPTION OF WORK` | Hard-capped at 20 characters |
| `asset_id` | `ASSET ID` | Complete selected registry UID |
| `dispatch_service_center` | `DISPATCH WO TO SERVICE CENTER?` | Always `NA` for this application |
| `instructions` | `ADDITIONAL INFORMATION IF NEEDED` | Blank unless user adds a note |

These fields always remain blank and are omitted from custom URLs and API cells:

- `LEAVE REQUEST COMPLETED`
- `PO #`
- `WORK ORDER #`

Original PO Number is not in that always-blank set because it is active for
change orders.

## 13. One-button package state machine

The final button performs one local, reversible preparation action:

1. Build the Scope/Inclusions/Exclusions PDF from the currently reviewed data.
2. Store its document signature.
3. Rebuild the complete PO context from current controls.
4. Verify source fingerprint, classification, required fields, PDF signature,
   and exactly two attachments.
5. Record device+account requester memory only for a ready context.
6. Display the two download buttons and prefilled link for that exact context ID.

The button does not submit Smartsheet or upload a file. If any PO detail changes,
the context ID changes and the user is told to press the same button again. If
contract, site, Inclusions, or Exclusions change, the PDF signature also becomes
stale and is rebuilt.

## 14. Two-file handoff and operator reminders

Every route produces exactly:

1. the unchanged original uploaded quote, or a TXT snapshot when the user pasted
   quote text; and
2. one Scope/Inclusions/Exclusions PDF.

After generation, the screen explicitly reminds the user to:

- download both files;
- upload both files near the end of the Smartsheet form;
- have Smartsheet opened or signed into in the same browser within the last few
  hours; and
- if the first link attempt opens without values, sign back into Smartsheet,
  return to the tool, and use the same link again.

Custom-URL parameters cannot carry local file bytes and never submit the form.

The long copy/paste field list is hidden by default inside the collapsed
`Troubleshooting: show manual field values` expander. It is available only when
the prefilled link fails after the user refreshes their Smartsheet session.

## 15. Source files changed in this revision

- `app/equipment_policy.py`: exact Group A policy and conservative fallback matcher.
- `app/asset_guess.py`: unique-best registry asset suggestion.
- `app/quote_analyzer.py`: expanded route, asset, and change-order extraction prompt.
- `app/analysis_schema.py`: validates the new guesses and 20-character description.
- `app/po_rules.py`: Ashley's route matrix and full asset-code preservation.
- `app/memory.py`: anonymous device+account requester/asset-manager memory.
- `app/web_ui.py`: three-step interaction, exception-only questions, suggestion defaults, and one final action.
- `app/po_context.py`: change-order, 20-character, requester/job, full asset, and
  Additional Information export rules.
- `app/smartsheet.py`: exact dropdowns, exact Original PO label, conditional
  original-PO behavior, and full asset validation.
- `app/smartsheet_inline.py`: two downloads, login/upload reminders, and hidden
  manual fallback.
- `app/smartsheet_ui.py`: simple primary prefilled-form link.
- `.env.example` and `render.yaml`: exact active field mapping.

## 16. Regression coverage

The suite covers:

- all four classification routes and the exact `$25,000` boundary;
- Group A versus loose-parts classification;
- fallback route guesses that do not depend on delivery method;
- full asset-code preservation;
- unique-best asset guessing and ambiguity rejection;
- model schema validation for route, asset, request type, and original PO;
- 20-character normalization and export truncation;
- PO versus Change Order Original PO behavior;
- Additional Information remaining independent of tax notes;
- device+account memory isolation, idempotency, and correction;
- exact dropdown values and exact live form label spelling;
- URL `%20` wire encoding;
- exactly two files;
- one final generation action;
- removal of obsolete tax/forget/separate-submit controls; and
- recent-login, retry, upload, and hidden-troubleshooting reminders.

Local acceptance result for this revision: **92 tests passed**.

## 17. Deployment and rollback notes

Production configuration must include this exact mapping:

```json
"original_po_number": "ORIGINAL PO NUMBER"
```

`SMARTSHEET_API_MODE` remains `disabled`. This revision uses only the
non-submitting custom-URL handoff.

After deployment, verify with synthetic data only:

1. The screen has three steps and one final button.
2. An RRH quote suggests account/site, O&M job, work route, and a unique asset.
3. New PO omits Original PO Number.
4. Change Order requires and prefills Original PO Number.
5. Description of Work in the URL is no more than 20 characters.
6. Full asset UID, including letters and separators, appears in the URL.
7. Two downloads and both reminders are visible.
8. Manual fields are collapsed.
9. Opening the link prefills but does not submit the live form.

Rollback should revert the application commit and restore the prior Render
field-map value together. Do not roll back only one side of the field label
mapping. A rollback reintroduces superseded business behavior, so use it only
for an operational outage and keep API mode disabled.

## 18. Deferred work

- Add the complete approved cost-code catalog for every site when supplied by
  the product owner.
- Add a trusted JDE-to-full-asset mapping only if a verified source and explicit
  product-owner instruction are later provided. Until then, complete configured
  asset UIDs remain authoritative.
- Direct Smartsheet API submission remains a separate, gated project.

## 19. Commit-note template

Suggested squash title:

```text
Streamline RRH PO generation and apply Ashley's routing corrections
```

Suggested body:

```text
- replace delivery-based routing with labor/rental/Group-A/materials policy
- add AI route, request-type, original-PO, and unique asset suggestions
- preserve complete configured asset IDs and cap Description of Work at 20 chars
- support change-order Original PO Number under the exact live form label
- remember requester/asset manager by anonymous device and account after one package
- remove tax confirmation and requester-forget controls
- combine document preparation and Smartsheet handoff into one final action
- hide manual copy fields behind troubleshooting and add login/upload reminders
- update exact Smartsheet dropdown/schema mappings and add successor handoff
- add regression coverage for the new policy and three-step UX
```
