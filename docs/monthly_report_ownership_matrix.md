# Monthly Report ownership and carryover policy — draft decision record

This is the bounded #470 design deliverable, at audited main `a1b2aa61aa92c596d424c95dba29be66135f3441`. **It is not a production data migration, deployed feature, or owner approval for any proposal.** Machine-readable fields, individual source-of-truth descriptions, implementation paths, and synthetic examples are in [monthly_report_ownership_matrix.json](monthly_report_ownership_matrix.json).

## Evidence and decision vocabulary

- **explicit_requirement:** The October 26 meeting/intake explicitly rejected unsafe behavior, especially workflow diagrams shared across contracts. Implement it without asserting this audited main already does so.
- **meeting_intent:** The meeting requested reuse but did not settle every storage, identity, authorization, and conflict detail. These parts still require review.
- **existing_implementation:** Verified as source-code behavior on the cited main; neither physical-device acceptance nor blanket contract policy is implied.
- **proposed_policy:** Specific, implementable guardrail offered for the owner's decision. It is not permission for automatic promotion or rewriting history.
- **open_decision:** Do not guess. Use the narrower site-scoped or report-only behavior until the actual contract/owner decision is recorded.

A report is a **pinned version of approved or manually authored information**, not a live pointer that automatically changes when a shared directory, capacity record, Training matrix, vendor list or diagram is edited.

## Ownership matrix

The table summarizes **intended ownership/decision status**, not necessarily deployed storage behavior. `explicit_reuse` means a reviewed, scoped reuse decision; it does not permit background adoption. Every row's exception and source module are in JSON.

| Data/asset | Scope | Decision evidence | Inheritance | Promotion to standing | New month |
| --- | --- | --- | --- | --- | --- |
| enfra_branding | contract | proposed_policy | explicit_reuse | approved_shared_save | reuse_standing |
| client_branding | contract | proposed_policy | explicit_reuse | approved_shared_save | reuse_standing |
| cover_photo | report | existing_implementation | explicit_reuse | approved_shared_save | review_source |
| workflow_business_hours | contract | explicit_requirement | explicit_reuse | review_and_adopt | reuse_standing |
| workflow_after_hours | contract | explicit_requirement | explicit_reuse | review_and_adopt | reuse_standing |
| org_chart | site | proposed_policy | explicit_reuse | approved_shared_save | reuse_standing |
| facility_contacts | contract_site | existing_implementation | explicit_reuse | approved_shared_save | reuse_standing |
| thermal_capacity | unresolved | open_decision | review_before_reuse | decision_required | review_source |
| subcontractor_contacts | contract | meeting_intent | explicit_reuse | approved_shared_save | reuse_standing |
| subcontractor_status | contract_site | proposed_policy | explicit_reuse | approved_shared_save | confirm_current |
| capital_renewal | contract_site | meeting_intent | explicit_reuse | approved_shared_save | carry_context |
| proposals | report | proposed_policy | carry_context_only | approved_shared_save | carry_context |
| issues | report | existing_implementation | carry_context_only | not_applicable | carry_context |
| training_requirements | contract_site | existing_implementation | explicit_reuse | approved_shared_save | reuse_standing |
| training_events | report_month | existing_implementation | never_automatic | not_applicable | reset |
| activity_work_orders | report_month | existing_implementation | never_automatic | not_applicable | reset |
| monthly_attachments | report_month | existing_implementation | never_automatic | not_applicable | review_source |
| source_originals | source_archive | existing_implementation | never_automatic | review_and_adopt | review_source |

## Scope and precedence

1. **Organization and contract:** Brand identities, approved template geometry and contract-specific workflow art may seed a new report only for the same verified contract and permitted sites. A logo is never a cover photograph. A global ENFRA logo rule is a **proposal**, not automatically inferred from saved contract logos.
2. **Contract + site:** Shared directories, future approved subcontractor lists, capital recommendations and reviewed capacity records may be partitioned to named site keys. Shared templates must not erase site exceptions. Aliases require exact or uniquely confirmed membership; a title/filename or similar columns never prove ownership.
3. **Report version:** Every published report stores the selected contents and source/asset references in its own immutable revision history. Report-only correction, omission or clear changes this version's candidate contents; it never silently modifies or deletes standing data.
4. **Report month:** A source dated for September can support *historical* context in October but is not evidence of October work, a completed training session, current PM counts or newly produced report pages. Source dates, incomplete fields and site scope require review.
5. **Unresolved/ambiguous:** No automatic backfill, cross-contract seeding, conversion of unknown status to Completed, or source reclassification. Preserve the original and surface one specific review action.

## Verified code behavior versus pending integration

- **Shared version and history:** `monthly_report_library.save_snapshot` uses an expected revision and appends a saved historical report version. `replace_block` and `save_profile` similarly use revision gates. They do **not** authorize republishing report-only edits as standing defaults.
- **Facility contacts:** `monthly_report_directory` stores confirmed contract-wide and site-specific contacts in versioned records. The report can carry a separately reviewed contact-matrix snapshot. Changing a report contact is not blanket permission to change directory history.
- **Capacity:** `monthly_report_capacity` currently has a **contract storage root with row-level site keys**, revisioned history, source identity, reviewed merge/replace modes and explicit selected-site report copies. This does not settle whether a given contract permits shared versus separately governed site capacity assumptions. **This remains open.**
- **Training:** `monthly_report_training` currently stores a contract-scoped site matrix and report-bound `EVENT_REF` completed sessions; monthly rollover excludes previous completed session tables. The year-specific annual schema in PR #537 is **not** treated as merged at the audit baseline.
- **Workflows:** The audited `monthly_report_workflow_standards` still contains a **global ENFRA standards path and profile discovery**. That conflicts with the newer contract-specific requirement. PR #533 is an independent implementation proposal and must receive its own exact-head CI and deployment verification. This matrix neither rewrites nor blesses the legacy global defaults.
- **Subcontractors and capital:** The meeting expressed contract reuse intent. There is no authorization to copy imported rows into an approved standing vendor/capital master on passive load; PRs #531/#544 cover different bounded source/import issues. The actual promotion UI, contract roster identity and site-exception policy remain to be decided.
- **Proposals and issues:** Current report cards retain source/context and differentiated statuses. Omit does not mean resolve, and a carried status is not a new monthly update.
- **Shared source shelf:** `monthly_report_shared_source_bundles` holds byte-verified reference originals, not a permissioned auto-import or standing-default store.

## Six worked scenarios (invented data only)

Use **Contract A** (Sites A1, A2) and **Contract B** (Sites B1, B2), September and October 2026. No genuine customer values, contact data or pricing are needed.

### workflows_between_contracts

**Actions:** Approve A's business-hours diagram explicitly for A. Create an October A2 report and reuse the approved A diagram. Create an October B1 report without any B-approved diagram.

**Expected boundary:** A2 may reuse the exact A contract version, pinned into its October report. B1 must remain empty/ask for B approval, not inherit A artwork. A September report retains its original version after an A October replacement.

### report_only_contact_correction

**Actions:** Open October A1 report from its approved contact directory. Edit one phone number as report-only. Reopen October A2, September A1, and contract B1 reports.

**Expected boundary:** A1's October report contains the correction only after it is saved. The shared A directory and A2 stay unchanged until explicit master-save with expected revision. September A1 and B1 remain unchanged after all operations.

### vendor_master_promotion

**Actions:** Import vendor trade-band contacts into October A1. Make a report-only vendor correction. Explicitly promote a reviewed A contract roster at expected revision.

**Expected boundary:** Unreviewed imports do not create standing vendors. A2 sees the approved A roster only on intentional reuse, with source/trade identity preserved. A previous A1 version and all contract B records remain pinned and unchanged.

### capacity_site_partition

**Actions:** Review A1 chilled-water capacity from exact original source. Save a contract capacity revision containing A1's explicit site key. Open October A2's capacity panel.

**Expected boundary:** A2 does not inherit A1 numeric values by location guess or schema similarity. Separate A1 steam/chilled-water and plant/units remain distinct. The broader capacity reuse policy remains unresolved pending explicit owner decision.

### history_and_monthly_facts

**Actions:** Complete September A1 training event and work-order table. Create October from saved September report. Inspect October and then reopen September.

**Expected boundary:** September facts/events remain in the September pinned version. October does not call September events/work orders 'completed this month'. Standing approved training requirements remain available without inventing completion.

### capital_proposal_revision

**Actions:** Correct an October A1 capital recommendation as report-only. Import the same original again and encounter a conflicting historic row. Review a Pending and a Declined proposal with source dates.

**Expected boundary:** The intentionally removed or corrected capital row is not silently resurrected. Reimport conflict keeps current report edits and requires explicit review. Pending and Declined statuses stay distinct; other contracts and prior snapshots do not change.

## Approval/promotion decision protocol (proposed)

A promotion request should explicitly show the **scope** (contract and site identities), **current source hash/revision**, proposed standing values with retained original/unknown fields, affected future reports, and a clear **Save shared version** action distinct from report-only Save. Acquire the appropriate contract/site version lock; reject stale expected revisions with a recoverable comparison. Never promote through preview/open/rerun/import alone.

Only *new* or explicitly refreshed reports consume an approved standing revision. Prior DOCX/PDF/snapshot versions remain pinned and restorable. The absence of a saved diagram, rejected attachment, blank cell, Omit choice, or corrupted import is never permission to fill from an unrelated site or contract.

## Non-destructive migration plan — only after individual decisions

1. **Inventory without mutation.** Enumerate saved per-profile blocks, contract directory, capacity/site partitions, training manifests, native designs, workflow standards, approved assets, original file hashes, selected report versions and explicit omissions. Record actual source/tenant and existing version.
2. **Separate legacy global from approved contract values.** In particular, a global outage diagram cannot silently acquire a new contract identity. Quarantine it as a reusable reference candidate; preserve its exact original and origin.
3. **Review and adopt per target scope.** Show origin contract, original/asset digest, suitability/review evidence, target contract/sites, effective period, relevant prior versions and conflicting current values. No approval means no adoption.
4. **Version transactionally.** Copy/refer to immutable validated bytes, write an explicit provenance/decision record under a CAS version check, and retain existing source and history records. A failed/partial save must leave the old head valid.
5. **Roll out without silent backfill.** Default only a newly opened, approved scope; report-only exclusions and authored overrides win. Reopen older snapshots unchanged. Require explicit conflict/replacement actions and preserve independent contract A/B values.
6. **Acceptance before release closure.** Synthetic two-contract/two-site/two-month import, edit, promotion, concurrent save, site switch, omit, rollover and restore; actual source/full Word/PDF output and native narrow/wide served tests. Verify that original file bytes/hashes and previously saved versions are unchanged.

**No step above authorizes a live migration or cleanup in this PR.**

## Decisions still needed

1. **Thermal capacity:** Should each contract approve site-owned capacities only, or specific cross-site/shared contract assumptions? Clarify plant/service and approval authority before allowing anything broader than the current explicit site-key match.
2. **Subcontractor master:** Define reviewer/publisher and whether a trade/contact/status change applies to the whole contract, selected sites, or only one report. Specify last-confirmed status and exact row identity; source table alone is not a standing update.
3. **Capital and proposals:** Determine which reviewed row identities may be contract-master records versus report-month status or source-only history. Never infer Declined from the absence of a pending item.
4. **Brand and org chart scope:** Confirm global ENFRA brand policy separately from client contract logos and site-specific organization charts; do not merge unlike asset roles.
5. **Annual Training:** Review PR #537's year semantics and contracts before using that planned schema to promote historical completion into standing annual status.

These are recorded **open choices**, not blocks on preserving already approved site/report content. Follow-up implementation owners can link their PRs to a single policy row without overlapping one another's source or saved-version work.

## Explicitly out of scope

No UI changes, no owner-authentication changes, no report/master rewrite, no real customer-data access, no automatic contract migration, no data purge, no global style swap, no new monetized service and no production deployment. This design record must be refreshed against actual merged main before implementation; any future behavior inconsistent with a meeting requirement requires another recorded decision.
