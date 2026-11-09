# Monthly Report ownership and carryover — current mechanisms and decision record

This is the bounded [#470 design deliverable](https://github.com/evanroden/msapo-generator/issues/470), refreshed against main `9cc96e6265fbf0ce40dbacf8d013cdc6b612e549` on 9 November 2026. It is **not a production data migration, runtime configuration, policy signoff or release approval**. The [matching JSON](monthly_report_ownership_matrix.json) is a review artifact, not input to the application.

The earlier [#547](https://github.com/evanroden/msapo-generator/pull/547) / [#581](https://github.com/evanroden/msapo-generator/pull/581) artifacts describe an older main. This version preserves their 18 data/asset categories and six invented scenarios while separating current mechanisms from intended or unresolved policy. No application, stored schema, original, report, standing record, access rule or deployment changes in this work.

## How to read the evidence

The policy table records the narrow rule or proposed boundary for each item. Its **Evidence** cell qualifies that rule; it does not approve every related design choice. Each current-mechanism section states what the audited source actually does, gives exact code/test anchors and records limitations. The row's cited intake supports only the stated requirement; an implementation handoff is not owner policy approval.

- **explicit_requirement:** A cited owner intake explicitly requires the narrow boundary, such as contract-specific workflow diagrams.
- **meeting_intent:** Reuse was requested, but detailed authority, status or promotion semantics remain unsettled.
- **existing_implementation:** Verified current source behavior, not blanket business-policy or served acceptance.
- **proposed_policy:** A review proposal, not an installed action or permission to write.
- **open_decision:** A broader business choice remains unresolved; retain the separately described current behavior.

A saved report can contain draft or unreviewed material. Saving its snapshot preserves work; it does not prove that source, artwork or output approval has passed. The working report, a saved report revision, a profile/library version and a standing registry head are separate things.

Current company master geometry is also distinct from contract procedure artwork: [monthly_report_designs.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_designs.py) pins an installed design digest for a report. Its company-level layout mechanism does not make contract diagrams or client data universal.

## Policy and lifecycle matrix

The table is a decision-status summary. Read it with the current mechanisms below, especially the directory, capacity and Training shared-write exceptions. `decision_required` for thermal capacity concerns **broader sharing policy**, not a new restriction on safe first fill.

| Data/asset | Scope | Evidence | Source of truth | Inheritance | Report override | Standing promotion | Conflict rule | New month |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| enfra_branding | organization | existing_implementation | Reviewed ENFRA entry in the shared logo catalog; report copies are pinned. | eligible_standing_defaults | A report's custom or omitted logo is not replaced by ordinary defaults; changing it does not edit the catalog. | approved_shared_save | standing_cas | retain_pinned |
| client_branding | contract | existing_implementation | Explicit client-contract mapping in the shared logo catalog, copied into the report. | eligible_standing_defaults | A populated or omitted report logo remains pinned; an explicit report replacement does not publish a new catalog mapping. | approved_shared_save | standing_cas | retain_pinned |
| cover_photo | report | existing_implementation | Selected cover_photo block and retained original/asset reference in the report. | explicit_reuse | Use or omit a photograph for this report; leave catalog logos, installed design and historical versions unchanged. | not_applicable | report_cas | retain_pinned |
| workflow_business_hours | contract | explicit_requirement | Versioned procedure pictures explicitly published for the canonical contract. | eligible_standing_defaults | Keep populated or omitted report pages; explicit Use replaces procedure pictures while retaining adjacent notes and tables. | review_and_adopt | standing_cas | retain_pinned |
| workflow_after_hours | contract | explicit_requirement | Versioned procedure pictures explicitly published for the canonical contract. | eligible_standing_defaults | Keep populated or omitted report pages; explicit Use replaces procedure pictures while retaining adjacent notes and tables. | review_and_adopt | standing_cas | retain_pinned |
| org_chart | contract_site | existing_implementation | Versioned contract chart default with optional explicitly published single-site overrides. | eligible_standing_defaults | Explicit report use preserves adjacent notes/tables; report edits do not publish a chart until the separate confirmed action. | approved_shared_save | standing_cas | retain_pinned |
| facility_contacts | contract_site | existing_implementation | Contract directory with contract-wide contacts and explicit site records; separate report copies. | eligible_standing_defaults | Manual/unproved tables and removals stay report-only; qualifying verified Library edits may also update only their bound directory sites. | qualified_automatic_keep | standing_cas | refresh_eligible_copy |
| thermal_capacity | unresolved | open_decision | Current contract capacity history contains source-bound rows with explicit site_keys. | review_before_reuse | Existing manual/Omit report blocks stay pinned; an empty non-Omit block or unchanged pinned copy can refresh after a shared update. | decision_required | standing_cas | retain_pinned |
| subcontractor_contacts | contract | existing_implementation | Explicit, versioned contract-scoped approved subcontractor roster; ordinary report/profile contact tables remain distinct. | review_before_reuse | Report-only edits, exclusions and imported pages never update the approved roster; an explicit, revision-checked publication or Use action is required. | approved_shared_save | standing_cas | carry_context |
| subcontractor_status | contract_site | proposed_policy | Report agreement/status cells and optionally approved site-eligible contract roster rows; no automatic effective-date inference. | carry_context_only | A report-only status correction does not republish the approved roster or create a new service event; explicit roster review/save is separate. | approved_shared_save | standing_cas | confirm_current |
| capital_renewal | contract_site | existing_implementation | Report/profile Capital rows plus merged #684 versioned contract-approved master API and explicit site-selected occurrences. | review_before_reuse | Report-only correction/omission and replay guards remain authoritative; master revisions never overwrite report choices or historical snapshots. | approved_shared_save | standing_cas | carry_context |
| proposals | report | existing_implementation | Report proposal cards/tables with source occurrence, recorded decision and carried period. | carry_context_only | Saved explicit decisions and report omissions remain attributable to that report; they do not publish a shared contract status. | not_applicable | report_cas | carry_context |
| issues | report | existing_implementation | Canonical report issues/followups and their source/evidence references. | carry_context_only | Report visibility/Clear and resolution are distinct; a fresh Updated claim requires the existing current-period confirmation. | not_applicable | report_cas | carry_context |
| training_requirements | contract_site | existing_implementation | Versioned contract/year/site requirements registry, plus each report's pinned matrix reference. | eligible_standing_defaults | A pinned matrix survives rollover; requirements-grid edits/Add requirement/Start YEAR write shared requirements, unlike report-only notes and sessions. | explicit_matrix_edit | standing_cas | retain_pinned |
| training_events | report_month | existing_implementation | Report-bound training:events:v1 rows with dates, participants and hours. | never_automatic | Session edits/clear affect report content, not standing requirements or previously saved monthly sessions. | not_applicable | report_cas | reset |
| activity_work_orders | report_month | existing_implementation | Accepted report source rows/manual work with selected-site and period context. | never_automatic | Corrections and source selections belong to the working report and its saved versions; no automatic standing work-order publication. | not_applicable | report_cas | reset |
| monthly_attachments | report_month | existing_implementation | Selected section/source-page occurrences and reviewed report asset copies. | never_automatic | Page inclusion/caption/Omit changes report output; it does not delete an original or publish it as standing content. | not_applicable | report_cas | review_source |
| source_originals | source_archive | existing_implementation | Hash-verified stored originals and receipts; separate report references and shared reference shelves. | never_automatic | A new replacement has its own identity/review; a report reference or omission never edits bytes under an old source identity. | review_and_adopt | immutable_sha256 | review_source |

### Vocabulary

`eligible_standing_defaults` means an existing narrow first-use/default path, not permission to publish shared data. `explicit_reuse` requires the appropriate deliberate reviewed action. `carry_context_only` preserves historical context without creating new-month facts; `never_automatic` does not authorize automatic new-month inclusion.

`qualified_automatic_keep` describes the existing verified facility-contact edit path. `explicit_matrix_edit` describes shared Training requirements editing, including explicit year transition. `approved_shared_save`, `review_and_adopt` and `decision_required` are read with each row's evidence status; a proposed master has no current save action.

`standing_cas` and `report_cas` are separate expected-revision checks. `proposed_standing_cas` is a future design constraint, not an implemented store. `immutable_sha256` binds original bytes to their recorded digest.

`retain_pinned` does not adopt a newer standing value on rollover. `refresh_eligible_copy` permits the current verified working-copy refresh, not a historical snapshot rewrite. `reset` removes old monthly output, not its historical records or stored originals. `confirm_current` is a proposed status boundary where that row remains proposed.

## Current mechanisms and decision sources

### enfra_branding

**ENFRA brand logo / approved company identity.** The versioned branding catalog is shared. find_logo selects the explicit enfra entry for the company logo, while apply_defaults fills only an eligible empty brand_logo slot and preserves populated, omitted and caller-protected slots. Saving the catalog requires a named, confirmed actor and its current revision. Reports keep selected image bytes/references; catalog replacement does not rewrite their saved history.

**Boundary:** The existing organization-level ENFRA logo is distinct from contract workflow diagrams and contract-mapped client logos.

**Code:** [app/monthly_report_branding.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_branding.py) — `find_logo`, `apply_defaults`, `save_branding`, `restore_branding`.

**Existing synthetic test anchors:** [tests/test_monthly_report_branding.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_branding.py) — `test_versioned_branding_pins_saved_report_and_restores_without_erasing_history`, `test_empty_brand_and_client_defaults_and_explicit_omit`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration.

- The meeting intake does not define a new publishing-role model. This record neither expands catalog access nor generalizes its global scope to report content.

**Open choices:** Any new organizational publishing authority or cross-organization branding policy needs a separate decision; current named/confirmed writes remain unchanged.

### client_branding

**Client logo and contract terminology.** find_logo selects a client logo only when the report contract is listed in that catalog entry. apply_defaults fills an eligible empty client_logo slot, verifies its bytes and reuses the saved artwork review; it does not approve an already pinned custom image. Catalog changes use a separate confirmed revisioned save, and old report snapshots retain their selected copies.

**Boundary:** Catalog storage is shared, but client-logo selection requires explicit membership for the target contract. One entry may list several contracts; an A-only mapping does not authorize B. Matching names or images do not create a mapping.

**Code:** [app/monthly_report_branding.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_branding.py) — `_logos`, `find_logo`, `apply_defaults`, `save_branding`.

**Existing synthetic test anchors:** [tests/test_monthly_report_branding_reuse.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_branding_reuse.py) — `test_shared_defaults_do_not_review_pinned_custom_artwork_or_new_cover_photo`, `test_explicit_shared_logo_choice_reuses_review_but_later_custom_replacement_needs_review`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration.

- An existing code mapping is not evidence that a different client or contract has authorized that artwork.

### cover_photo

**Report cover photograph.** The ordinary Change cover photograph flow changes the report's photo slot. Replacement preserves review only when the exact selected artwork remains unchanged; a new choice receives its own review state. No cover photograph sets source to Omit while retaining its asset references. Rollover retains the non-monthly photo block; it does not publish a shared photo master or rewrite earlier report versions.

**Boundary:** A photograph is not a logo. Retaining a prior photo does not establish that it depicts newly completed work.

**Code:** [app/monthly_report_cover_ui.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_cover_ui.py) — `replace_cover_picture`, `render_cover_photograph`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`.

**Existing synthetic test anchors:** [tests/test_monthly_report_cover_photo_omission.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_cover_photo_omission.py) — `test_no_photo_preserves_already_omitted_retained_assets_or_genuinely_cleared_photo`, `test_same_source_photo_reselection_cannot_resurrect_report_omission`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration.

- Starting Report Omit/reinclude text-table repair #687 is merged; its independent review/edit-retention controls do not change the cover-photo source/approval boundary.

### workflow_business_hours

**Business-hours outage workflow diagram.** Current workflow standards are contract-scoped. Publishing checks the current report block, its fingerprint, reviewed pictures, source-page/site admission and the expected standing revision. Defaults fill only eligible blank included slots; the guided loader suppresses this default path for saved, recovered and rolled-forward reports. Explicit Use replaces pictures while preserving adjacent notes/tables. Legacy adoption requires matching recorded origin contract, an exact review receipt and a recheck under lock; adoption alone does not replace current report pages.

**Boundary:** Contract isolation is an explicit requirement. Current code implements it; legacy global records are read-only adoption candidates, not active global defaults.

**Code:** [app/monthly_report_workflow_standards.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_workflow_standards.py) — `load_standards`, `save_standard`, `apply_defaults`, `use_standard`, `legacy_candidate`, `legacy_review_receipt`, `adopt_legacy`.

**Existing synthetic test anchors:** [tests/test_monthly_report_contract_workflows.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_contract_workflows.py) — `test_foreign_legacy_default_is_not_applied`, `test_own_legacy_default_requires_explicit_adoption`, `test_explicit_empty_omission_is_never_refilled`; [tests/test_monthly_report_workflow_source_guards.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_workflow_source_guards.py) — `test_publication_rechecks_source_page_consent`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/474) — Requires contract-specific diagrams, deliberate legacy adoption and preservation of report/site content.

- The narrow independent-artifact legacy route does not recover missing original source-page history or validate that lost approval. Current UI states this limitation.
- Default availability for a new report is different from automatically replacing the pinned procedure of a carried or reopened report.

### workflow_after_hours

**After-hours outage workflow diagram.** Current workflow standards are contract-scoped. Publishing checks the current report block, its fingerprint, reviewed pictures, source-page/site admission and the expected standing revision. Defaults fill only eligible blank included slots; the guided loader suppresses this default path for saved, recovered and rolled-forward reports. Explicit Use replaces pictures while preserving adjacent notes/tables. Legacy adoption requires matching recorded origin contract, an exact review receipt and a recheck under lock; adoption alone does not replace current report pages.

**Boundary:** Contract isolation is an explicit requirement. Current code implements it; legacy global records are read-only adoption candidates, not active global defaults.

**Code:** [app/monthly_report_workflow_standards.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_workflow_standards.py) — `load_standards`, `save_standard`, `apply_defaults`, `use_standard`, `legacy_candidate`, `legacy_review_receipt`, `adopt_legacy`.

**Existing synthetic test anchors:** [tests/test_monthly_report_contract_workflows.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_contract_workflows.py) — `test_foreign_legacy_default_is_not_applied`, `test_own_legacy_default_requires_explicit_adoption`, `test_explicit_empty_omission_is_never_refilled`; [tests/test_monthly_report_workflow_source_guards.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_workflow_source_guards.py) — `test_publication_rechecks_source_page_consent`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/474) — Requires contract-specific diagrams, deliberate legacy adoption and preservation of report/site content.

- The narrow independent-artifact legacy route does not recover missing original source-page history or validate that lost approval. Current UI states this limitation.
- Default availability for a new report is different from automatically replacing the pinned procedure of a carried or reopened report.

### org_chart

**Organizational chart / site structure.** Chart defaults already have a contract store, immutable revisions and optional single-site overrides. selected_default prefers the selected site's override, then the contract default; a multi-site report uses only the contract fallback. Publication requires an exact current chart, confirmed actor, scope, source-page/artwork review and expected revision. Defaulting preserves authored, omitted and excluded copies, with a narrow exception for a just-copied profile fallback. The guided loader suppresses defaults for saved, recovered and carried reports; an eligible empty imported block can still receive a default, but an imported populated chart does not receive the profile-fallback exception.

**Boundary:** Current implementation already supports contract defaults and single-site overrides. A combined-site report does not guess one site's chart.

**Code:** [app/monthly_report_org_chart_defaults.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_org_chart_defaults.py) — `selected_default`, `save_default`, `use_default`, `apply_defaults`.

**Existing synthetic test anchors:** [tests/test_monthly_report_org_chart_defaults.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_org_chart_defaults.py) — `test_contract_site_precedence_and_no_cross_contract`, `test_explicit_refresh_preserves_notes_and_rollover_snapshot`, `test_legacy_profile_seed_precedence_preserves_explicit_report_choices`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/474) — Requires organization/workflow uploads to retain their intended contract/site scope.

- This is an implemented scope mechanism, not permission to infer a particular chart's contract-wide suitability from its filename or appearance.

### facility_contacts

**Facility contacts and contract contact directory.** Directory defaults reuse known contacts for exact selected-site bindings when the named editor and empty-copy guards allow it. automatically_keep_directory_contact_edits can persist a narrowly verified Library-copy edit without another shared-save button: it checks historical rows/bindings, excludes contract-wide rewrites and ordinary additions/removals/reorders, and rejects same-site conflicts while preserving other sites. Explicit add intent has separate checks. refresh_directory_contacts can update an unchanged working copy from newer standing records; it does not rewrite historical snapshot bytes.

**Boundary:** Do not apply subcontractor promotion rules to this existing facility-directory mechanism. Saved report history stays distinct from refreshed working copies.

**Code:** [app/monthly_report_directory.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_directory.py) — `contact_block`, `apply_defaults`, `automatically_keep_directory_contact_edits`, `refresh_directory_contacts`, `save_directory`.

**Existing synthetic test anchors:** [tests/test_monthly_report_contact_auto_scope.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_contact_auto_scope.py) — `test_auto_contact_edit_updates_only_intended_site_and_preserves_old_report`, `test_report_only_or_unmatched_contact_is_not_promoted`, `test_same_site_conflict_rejects_old_write_without_changing_history`; [tests/test_monthly_report_contact_refresh.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_contact_refresh.py) — `test_refresh_never_rewrites_historical_snapshot_bytes`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration.

- Not every contact edit is report-only, and not every edit qualifies for automatic keeping. Contract-wide contact administration remains a separate directory action.
- Direct-contact shortcut #693 is merged; literal-label PR #691 remains separate pending review. Neither changes the verified directory keeping/persistence policy.

### thermal_capacity

**Thermal capacity: site, plant and service values.** Capacity already uses contract storage with explicit row-level site_keys and revisioned history. Safe first-fill rows can be persisted automatically when the existing UI has resolved site matches, a named actor, no unverified image and no duplicate identity; browsing alone is not a save. Corrections to existing reusable values require the existing reviewed update action. capacity_block filters rows to selected sites, resolve_capacity fills only empty non-Omit content, and can_refresh_capacity permits an empty non-Omit block or an unchanged pinned copy.

**Boundary:** The unresolved decision concerns broader capacity-sharing authority, not a new prohibition on existing safe first fill. Preserve site, plant/service, units, NR, blanks and zero.

**Code:** [app/monthly_report_capacity.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_capacity.py) — `first_fill_tables`, `save_capacity`, `capacity_block`, `resolve_capacity`, `can_refresh_capacity`; [app/monthly_report_capacity_ui.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_capacity_ui.py) — `render_capacity`, `_render_capacity_source`.

**Existing synthetic test anchors:** [tests/test_monthly_report_capacity.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_capacity.py) — `test_existing_snapshot_and_manual_content_never_autofollow_shared_updates`, `test_unknown_or_ambiguous_site_cannot_be_shared`; [tests/test_monthly_report_capacity_first_fill.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_capacity_first_fill.py) — `test_first_fill_accepts_only_missing_sites_and_preserves_nr`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/287) — Explicitly permits unambiguous first fill at its proper scope, with conflict-aware updates and zero browsing/layout writes.

- This record does not authorize copying A1 numerical assumptions to A2 or changing current first-fill/correction behavior.
- The default/promotion policy cells describe the unresolved broader sharing decision; the current-mechanism paragraph states what the existing UI actually does.

**Open choices:** For each contract, decide whether any capacity assumption may apply to multiple sites and who can approve that applicability; retain current exact site partitions until resolved.

### subcontractor_contacts

**Subcontractor contacts, trade bands and contact instructions.** The merged #686 contract-scoped roster provides an independently versioned contract store with explicit reviewed-row publication, site validation, revision guards and a report-scoped Use action. The ordinary report contact editor, imported grouped trades, untouched original pages and saved report history remain separate. Shared roster application never silently edits an existing report or moves source-page approvals.

**Boundary:** Approved roster versions can be shared for explicitly eligible contract sites, not inferred across contracts. Report-only edits and source-page imagery never silently publish. Facility-directory automatic keeping remains a separate mechanism.

**Code:** [app/monthly_report_vendor_groups.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_vendor_groups.py) — `grouped_vendor_contacts`; [app/monthly_report_visual_ui.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_visual_ui.py) — `edit_contacts`; [app/monthly_report_library.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_library.py) — `save_snapshot`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`; [app/monthly_report_subcontractor_roster.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_subcontractor_roster.py) — `load_rosters`, `save_roster`, `eligible_rosters`, `apply_roster`; [app/monthly_report_subcontractor_roster_ui.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_subcontractor_roster_ui.py) — `render_subcontractor_roster`.

**Existing synthetic test anchors:** [tests/test_monthly_report_vendor_group_bands.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_vendor_group_bands.py) — `test_auto_import_and_generic_word_output_preserve_exact_contacts`, `test_manual_ui_grouped_save_reopens_without_changing_adjacent_edits`; [tests/test_monthly_report_subcontractor_roster.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_subcontractor_roster.py) — `test_two_sites_and_contracts_have_independent_approved_rosters`, `test_report_only_manual_override_and_vendor_picture_are_preserved`, `test_conflict_preserves_newer_scope_and_immutable_history`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/488) — Requests contract-level subcontractor reuse while separating report-only changes from explicit master updates. [implementation_record](https://github.com/evanroden/msapo-generator/pull/686) — Merged #686 implements explicit contract-scoped roster publication and selective reuse; this records code behavior, not broad policy signoff.

- Contract-scoped roster APIs and report UI are merged, but genuine served/published acceptance remains separate; import alone is never roster approval.
- Site scope and contract-wide status are explicit reviewer decisions. No historical report, page receipt or original source bytes are migrated to the roster.

**Open choices:** Confirm publisher authority, roster scope defaults and whether agreement-status facts require an effective/last-confirmed date; do not infer cross-site applicability.

### subcontractor_status

**Subcontractor status / when to contact.** The report editor keeps agreement/status values as recorded and distinct from fresh monthly service work. Merged #686 can explicitly publish and apply reviewed subcontractor roster rows, including existing status columns, with contract/site gates and revision checks. It does not add a general effective-dated status registry or auto-confirm every carried status. New-month report context is not evidence of this month's vendor work.

**Boundary:** Preserve unknown, blank, false and explicit MSA/agreement states. Merged roster reuse can retain reviewed status cells for selected sites but does not establish current-month service completion or effective dates.

**Code:** [app/monthly_report_visual_ui.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_visual_ui.py) — `edit_contacts`; [app/monthly_report_editor.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_editor.py) — `_cell_text`, `_typed_table`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`; [app/monthly_report_subcontractor_roster.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_subcontractor_roster.py) — `save_roster`, `apply_roster`.

**Existing synthetic test anchors:** [tests/test_monthly_report_vendor_contacts.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_vendor_contacts.py) — `test_vendor_agreement_edit_preserves_unknown_and_invalidates_only_changed_content`, `test_legacy_boolean_column_preserves_every_value_when_agreement_is_unknown`; [tests/test_monthly_report_subcontractor_roster.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_subcontractor_roster.py) — `test_report_word_output_has_only_selected_site_and_preserves_vendor_status`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/488) — Requests scoped reuse of subcontractor contacts/status without conflating report edits and master changes. [implementation_record](https://github.com/evanroden/msapo-generator/pull/686) — Merged #686 includes site-qualified, explicit roster status reuse; no automatic status effective-date or monthly-work rule.

- Existing scoped roster status reuse is explicit; effective/last-confirmed date policy and live served review remain open, not silently approved by this record.

**Open choices:** Specify which statuses are standing agreement facts, their applicable sites and effective/last-confirmed dates, and which are monthly service facts.

### capital_renewal

**Priority capital renewal recommendations.** Capital report/profile content and the merged exact-source replay guard remain distinct from the merged #684 Capital master API. The API supports explicit approval under contract revision checks, immutable row identity, selected-site overrides, report pinning and financial/date rejection; it cannot silently migrate or alter saved reports. An ordinary user-facing editor approval/replacement flow is not supplied by #684. The general Starting Report Omit-reversal edit-retention repair #687 is also merged.

**Boundary:** The #544 Capital replay guard and #687 Starting Report omission correction are merged. #684 adds an independently versioned, explicitly approved Capital master API with site overrides and financial controls, but does not by itself supply an ordinary report editor approval/reuse UI.

**Code:** [app/monthly_report_start_replay.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_start_replay.py) — `_guard_carried_capital_tables`, `merge_starting_drafts`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`; [app/monthly_report_library.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_library.py) — `save_snapshot`; [app/monthly_report_capital_master.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_capital_master.py) — `load_capital_master`, `save_capital_master`, `select_capital`, `capital_report_block`.

**Existing synthetic test anchors:** [tests/test_monthly_report_capital_source_replay.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_capital_source_replay.py) — `test_reimport_keeps_explicit_report_omission`, `test_first_import_snapshot_reopen_and_two_rollovers_keep_current_values`; [tests/test_monthly_report_capital_master.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_capital_master.py) — `test_explicit_confirm_expected_revision_and_immutable_history`, `test_report_only_edits_omission_and_history_never_advance_contract_master`, `test_financial_fields_in_master_are_blocked_before_report_inclusion`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/492) — Requests contract/site reuse of Capital recommendations. [implementation_record](https://github.com/evanroden/msapo-generator/issues/492#issuecomment-6476804503) — Confirms #544's narrow replay repair was merged while contract-wide reuse remained open. [implementation_record](https://github.com/evanroden/msapo-generator/pull/684) — Merged #684 supplies a revisioned, site-scoped approval/selection API; a user-facing master editor remains outside that PR.

- The Capital master API exists, but normal report-editor approval/replacement UI and served output acceptance have not been established by #684.
- #687 protects the general Starting Report omission reversal, but these mechanisms do not bypass source, site, financial or review gates.

**Open choices:** Define the normal editor approval/use workflow and publisher authority for the existing #684 master API; preserve existing row/site identities and manual omissions.

### proposals

**Pending and declined proposal items.** Proposal normalization and carryover use source table decisions, existing row identities and saved manual choices. seed_followups retains included proposal context, distinguishes Pending from Declined and avoids treating a manually edited scope phrase as a new status. Report saves use their own revision/history. There is no separate standing proposal-status master in this path; a carried proposal remains historical context rather than a new-month event.

**Boundary:** Pending, Declined, unknown and deliberately omitted are different states. Source or scope wording alone does not decide status.

**Code:** [app/monthly_report_followups.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_followups.py) — `normalize_proposal`, `seed_followups`, `output_followups`; [app/monthly_report_library.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_library.py) — `save_snapshot`.

**Existing synthetic test anchors:** [tests/test_monthly_report_proposal_table_carryover.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_proposal_table_carryover.py) — `test_missing_or_unresolved_decision_is_not_inferred_from_other_fields`, `test_actual_import_reopen_manual_edit_reimport_and_two_rollovers`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration.

- Omission from one report is not a contract decision to decline or permanently delete the proposal. Existing pricing and source-review gates still apply.

### issues

**Open equipment issues and evidence/update status.** canonical_issues reconciles report issue cards and followups; rollover retains unresolved issue context and its backing evidence. seed_followups applies its existing next-month inclusion rules and clears review state, while current-period confirmation gates a carried Updated claim. Therefore an issue omitted in one report is not necessarily permanently suppressed in future months, and report-only Clear is not resolution. Earlier saved report versions remain unchanged.

**Boundary:** Unresolved issues and evidence can persist as history. Neither old evidence nor a carried status proves new work this month.

**Code:** [app/monthly_report_issues.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_issues.py) — `canonical_issues`, `issue_visibility`, `clear_issues`; [app/monthly_report_followups.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_followups.py) — `seed_followups`, `needs_issue_period_confirmation`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`.

**Existing synthetic test anchors:** [tests/test_monthly_report_issue_carry.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_issue_carry.py) — `test_rollover_keeps_evidence_but_requires_current_confirmation_for_an_updated_claim`, `test_explicit_no_issue_declaration_does_not_become_a_followup`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/281) — Requires truthful historical issue evidence and current-period claims across rollover.

- Do not promise that every omission persists identically through every future issue rollover; the documented current seed rules and resolution state determine that behavior.

### training_requirements

**Standing staff training requirements / annual status matrix.** Annual matrices use training:matrix:v2:YYYY; legacy training:matrix:v1 remains year-unrecorded. Fresh reports seed exact-year selected-site rows or safely reset earlier statuses. #715 validates each site's requirement heading identity and combines equal case/whitespace titles without merging different people/sites or losing statuses; a pinned report retains its selected year. Requirements grid/Add requirement/explicit Start YEAR write selected-site/year standing data under revision checks, and #762 captures pending grid changes before adding a new requirement. Monthly notes and sessions remain report-only; no universal extra shared-Save step exists.

**Boundary:** Annual matrix year identity is explicit. #715 joins cross-site requirement columns only by normalized case/whitespace identity, preserving per-site status, original column spelling and site scope; #762 captures delivered grid edits before Add requirement changes the schema.

**Code:** [app/monthly_report_training.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_training.py) — `matrix_for_year`, `save_training`, `seed_matrix`, `new_month_training`; [app/monthly_report_training_ui.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_training_ui.py) — `_requirements_year`, `render_training`; [app/monthly_report_training.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_training.py) — `_requirement_key`, `_requirement_columns`.

**Existing synthetic test anchors:** [tests/test_monthly_report_training_years.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_training_years.py) — `test_shared_year_save_retains_legacy_and_other_years`, `test_explicit_new_year_resets_recorded_status_but_keeps_blank`, `test_annual_snapshot_omission_and_double_rollover_remain_truthful`; [tests/test_training_requirement_identity.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_training_requirement_identity.py) — `test_independent_valid_site_saves_share_requirement_identity`, `test_each_person_site_status_and_missing_course_remains_independent`; [tests/test_training_requirement_add_capture.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_training_requirement_add_capture.py) — `test_public_storage_add_preserves_real_standing_report_history_and_word`, `test_failed_add_keeps_visible_grid_and_retry_without_stale_replay`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/459) — Requires annual requirements/year identity distinct from completed monthly sessions. [implementation_record](https://github.com/evanroden/msapo-generator/pull/715) — Merged per-site, cross-year Training requirement identity and status preservation. [implementation_record](https://github.com/evanroden/msapo-generator/pull/762) — Merged Add requirement handler captures in-flight grid changes before column keys change.

- #715's normalized heading identity does not authorize punctuation-based aliases or guessed cross-site statuses; ambiguous duplicate headings are rejected.
- #762's Add requirement input capture preserves delivered edits but does not auto-approve imported evidence or substitute for served/browser verification.

### training_events

**Completed training sessions (date, topic, participants, hours).** Completed sessions are independent EVENT_REF report tables. add_event and events_for_period preserve selected report-month scope; new_month_training removes the prior month event table without changing annual requirements or old snapshots. Merged #734 validates source event-site evidence on first import and on restored review receipts; ambiguous or out-of-scope rows cannot become an approved report event without review. A current-year training requirement status does not create a session.

**Boundary:** Completed requirements are not dated sessions. Merged #734 checks explicit source Training event-site columns in both new and restored reviews; ambiguous, foreign and duplicate-heading sites require manual correction or omission rather than silent cross-site inclusion.

**Code:** [app/monthly_report_training.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_training.py) — `add_event`, `events_for_period`, `new_month_training`; [app/monthly_report_library.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_library.py) — `save_snapshot`; [app/monthly_report_training_import.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_training_import.py) — `review_training_event_sites`.

**Existing synthetic test anchors:** [tests/test_training_rollover_regressions.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_training_rollover_regressions.py) — `test_old_completion_table_is_absent_instead_of_an_anonymous_header`, `test_two_saved_rollovers_do_not_grow_tables_or_rewrite_prior_history`; [tests/test_training_event_site_scope.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_training_event_site_scope.py) — `test_public_storage_saved_review_reopen_history_and_word`, `test_old_ready_receipt_is_revalidated_before_current_or_historical_publication`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/459) — Separates annual requirements from completed sessions. [owner_intake](https://github.com/evanroden/msapo-generator/issues/281) — Requires retained standing Training without carrying old monthly completion as new work. [implementation_record](https://github.com/evanroden/msapo-generator/pull/734) — Merged source-site validation for new and restored Training event reviews.

- #734's site checks cover explicit source-site columns; absent or ambiguous site evidence is never permission to infer foreign attendance.
- Monthly event reset preserves historical records and original source bytes; served and authentic layout acceptance remains separate.

### activity_work_orders

**Current-month work orders, service calls and operational narrative.** CMMS mapping uses explicit selected sites, date/status interpretation and declared coverage; it retains evidence rather than inventing completion or zero counts. Source contribution receipts bind accepted uses to report/site/period facts. new_month_draft clears period-specific output rows while retaining source records still referenced by carried content. It does not publish a reusable current-work master or erase prior snapshots.

**Boundary:** Current-month completion, PM/non-PM counts and zero require their existing evidence/coverage rules, not merely a repeated table.

**Code:** [app/monthly_report_cmms.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_cmms.py) — `map_cmms`; [app/monthly_report_source_scope.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_source_scope.py) — `contribution_receipt`, `included_scope_valid`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`.

**Existing synthetic test anchors:** [tests/test_monthly_report_cmms.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_cmms.py) — `test_monthly_service_calls_filter_month_and_status_but_keep_evidence`, `test_zero_only_for_confirmed_complete_history`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration. [owner_intake](https://github.com/evanroden/msapo-generator/issues/281) — Requires period provenance and separation of retained history from newly completed work.

- Planned target-month interpretation repair #664 is merged; it does not authorize treating imported planned work as completed current-month activity.
- Generic output reset is not source-byte deletion or permission to relabel retained evidence.

### monthly_attachments

**Scorecards, commissioning, water, vendor, progress photos and other attachments.** prepare_section_pages validates explicit selected pages and destination ownership against current report content, preserves page provenance and applies the existing page-review and size limits. new_month_draft removes period-specific attachment output; issue/proposal evidence and other referenced source context can remain under their own carry rules. Saved report versions and source originals are separate from the new month's selected pages.

**Boundary:** A page belongs to its reviewed source occurrence and destination. Current review, scope, privacy and resource gates remain applicable.

**Code:** [app/monthly_report_section_uploads.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_section_uploads.py) — `prepare_section_pages`, `included_pages`; [app/monthly_report_sources.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_sources.py) — `prepare_pages`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`.

**Existing synthetic test anchors:** [tests/test_monthly_report_section_uploads.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_section_uploads.py) — `test_append_only_new_page_preserves_exact_source_provenance`, `test_section_upload_does_not_embed_same_file_elsewhere`, `test_review_and_total_report_limits_remain_enforced`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration.

- The separately owned equipment gallery #690 and PDF preparation #669 are not claimed as merged by this record.
- Blank or cleared monthly output does not imply that all source metadata or archived bytes disappeared.

### source_originals

**Imported report, uploaded source file and shared reference shelf.** ingest stores source bytes under the existing profile/contract namespace and records their digest; source_bytes verifies the selected original before use. Saved report references and reviews are separate from those bytes. The shared reference-bundle shelf is a distinct immutable, discoverable no-login testing facility with its existing audience; its user-supplied manifest is not approval to import, adopt a standing default or assign an acceptance scenario. Rollover retains only source records still referenced by carried content and does not perform an archive migration.

**Boundary:** Reference storage is not report approval, tenant ownership assignment or authorization to promote/import content.

**Code:** [app/monthly_report_sources.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_sources.py) — `ingest`, `source_bytes`; [app/monthly_report_shared_source_bundles.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_shared_source_bundles.py) — `validate_reference_archive`, `SharedSourceBundles.upload`, `SharedSourceBundles.download`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`.

**Existing synthetic test anchors:** [tests/test_monthly_report_sources.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_sources.py) — `test_integrity_and_unsafe_reference_rejected`; [tests/test_monthly_report_shared_source_bundles.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_shared_source_bundles.py) — `test_reference_bundle_roundtrip_dedup_and_new_reader_preserve_immutable_bytes`, `test_changed_disk_bytes_fail_closed_instead_of_being_called_downloaded`.

**Decision evidence:** [owner_intake](https://github.com/evanroden/msapo-generator/issues/470) — Requests an ownership/carryover decision record; does not approve every proposed rule or authorize migration.

- The source shelf is not a newly permissioned private vault; this document adds no authentication or access policy.
- Original preservation does not imply every temporary QA lease is permanent; existing fixture retention and quotas remain unchanged.

## Worked scenarios

Use invented **Contract A** (A1, A2) and **Contract B** (B1, B2), with saved September and October 2026 reports. These are design walkthroughs, not records of browser or production execution. Each scenario distinguishes its desired boundary from what current main can actually do; all four site controls are inspected in the steps or expected outcomes.

### workflows_between_contracts

**Actions**

1. Publish reviewed business-hours and after-hours pictures explicitly for Contract A, then create a fresh eligible October A2 report.
2. Replace A's approved diagram with a new standing revision; reopen saved September A1 and October A2 reports.
3. Open October B1 and B2 without B-approved diagrams, and compare A1/A2 against those two controls.

**Expected boundary**

- A2 may consume only an approved A version; a fresh eligible report may default without a second per-report publication.
- Existing A1/A2 saved copies retain their selected version until a distinct permitted report action changes the working copy.
- B1 and B2 do not acquire A diagrams. Any legacy candidate needs same-contract review/adoption; adoption is separate from Use.

**Current main**

- These contract-scoping, omission and revision mechanisms are implemented on audited main.
- Saved/recovered/rolled-forward reports do not automatically adopt the newest workflow standing version.

**Pending or decisions:** Real native/served and genuine output acceptance is separate from these code/test anchors.

**Anchors:** [app/monthly_report_workflow_standards.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_workflow_standards.py) — `save_standard`, `apply_defaults`, `use_standard`, `adopt_legacy`; [tests/test_monthly_report_contract_workflows.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_contract_workflows.py) — `test_foreign_legacy_default_is_not_applied`.

### report_only_contact_correction

**Actions**

1. Save September reports for A1, A2, B1 and B2; create October working copies using their own directory scopes.
2. Edit A1's manually authored or unproved report contact table; separately edit an exact verified Library-backed A2 site contact.
3. Reload A1/A2 working copies and all four September snapshots; inspect B1 and B2 directories and October reports.

**Expected boundary**

- The unproved A1 edit remains report-only; it is not authority to reassign or delete standing people.
- The qualifying A2 edit can update only its verified shared site, without a separate shared-save button; a same-site intervening edit conflicts.
- All September snapshots and both B sites remain unchanged; an unchanged eligible A working copy may refresh, while an authored override remains intact.

**Current main**

- Current directory behavior deliberately distinguishes report-only edits from narrowly qualified automatic keeping.
- Historical snapshot bytes are not rewritten by working-copy refresh.

**Pending or decisions:** No additional policy decision is introduced for this narrow existing mechanism.

**Anchors:** [app/monthly_report_directory.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_directory.py) — `automatically_keep_directory_contact_edits`, `refresh_directory_contacts`; [tests/test_monthly_report_contact_auto_scope.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_contact_auto_scope.py) — `test_report_only_or_unmatched_contact_is_not_promoted`, `test_same_site_conflict_rejects_old_write_without_changing_history`.

### vendor_master_promotion

**Actions**

1. Import grouped vendor contacts into October A1 and correct a contact/status in that report; retain its September snapshot.
2. Inspect a separate A2 report and both B1/B2 reports; distinguish retained report/profile copies from a contract roster.
3. Explicitly approve A's reviewed vendor roster with revision/site scope and Use that eligible version in A2; verify no automatic share from the earlier A1 import or report-only edits.

**Expected boundary**

- Importing a vendor table or editing A1 does not itself approve a contract master.
- An explicitly published A roster can be selected for eligible A sites only; A2 report-only edits and deliberate omissions remain intact, while B1/B2 never inherit A records.
- September A1/A2/B1/B2 versions and their original pages remain retained.

**Current main**

- Merged #686 provides explicit contract-scoped roster publication and report-side Use with site eligibility, revision guards and immutable report history.
- A1's report-only import/correction never advances a shared roster by itself; A2 and B1/B2 remain unchanged absent a qualifying explicit action.

**Pending or decisions:** Merged #686 is the supported contract roster implementation; closed alternative #563 is not combined with it. The matrix does not authorize new cross-site scope or automatic promotion. Publisher authority and effective/last-confirmed vendor status policy still require an owner decision and genuine served acceptance.

**Anchors:** [app/monthly_report_visual_ui.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_visual_ui.py) — `edit_contacts`; [app/monthly_report_vendor_groups.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_vendor_groups.py) — `grouped_vendor_contacts`; [tests/test_monthly_report_vendor_group_bands.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_vendor_group_bands.py) — `test_manual_ui_grouped_save_reopens_without_changing_adjacent_edits`; [app/monthly_report_subcontractor_roster.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_subcontractor_roster.py) — `save_roster`, `apply_roster`; [tests/test_monthly_report_subcontractor_roster.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_subcontractor_roster.py) — `test_two_sites_and_contracts_have_independent_approved_rosters`.

### capacity_site_partition

**Actions**

1. Read a synthetic A1 capacity table with exact site identity and known plant/service/units; allow only the existing qualified first-fill path.
2. Open fresh October A2, B1 and B2 reports; compare them with A1 and the four saved September snapshots.
3. Review a later A1 correction and an intervening A2 shared revision, using the existing explicit correction/conflict path.

**Expected boundary**

- Safe A1 first fill may persist automatically at its proper scope; it does not assign A1 numbers to A2.
- A1 corrections must preserve other sites and fail on stale/shared conflicts; manual or omitted report copies remain distinct.
- B1/B2 cannot receive A capacity. Historical snapshots and original source values/units remain unchanged.

**Current main**

- The current store, first-fill guards, selected-site filtering and revision checks implement the narrow mechanism.
- Broader shared assumptions across sites remain an open business decision; this example does not implement one.

**Pending or decisions:** Define any allowed cross-site capacity assumption and its approval authority per contract before broadening current scope.

**Anchors:** [app/monthly_report_capacity.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_capacity.py) — `first_fill_tables`, `save_capacity`, `capacity_block`; [tests/test_monthly_report_capacity.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_capacity.py) — `test_updated_steam_preserves_chilled_water_and_other_sites`, `test_existing_snapshot_and_manual_content_never_autofollow_shared_updates`.

### history_and_monthly_facts

**Actions**

1. Save September A1/A2/B1/B2 reports with their own annual requirements, monthly sessions and dated work-order evidence.
2. Create October for all four sites; inspect requirements references separately from completed-session and work-order output.
3. Edit an A1 October requirements cell, then inspect the selected shared year/site, A2/B1/B2 standing rows and all September snapshots.

**Expected boundary**

- October does not present September sessions/work-order rows as new completion; original historical reports remain available.
- The exact annual matrix/year can remain pinned, including an older year; an explicit year transition is required to relabel/reset annual requirements.
- The requirements edit is a shared selected-site/year action, not a report-only note; unrelated sites/contracts and prior snapshots remain unchanged.

**Current main**

- Annual references, year-aware shared storage and #715 normalized per-site course identity preserve distinct requirement statuses across sites and years.
- #762 Add requirement captures pending grid changes; #734 validates source event-site identity; monthly EVENT_REF removal and saved history CAS do not delete stored originals.

**Pending or decisions:** Imported arbitrary annual tables and genuine/served output remain separate acceptance; normalized headings or reviewed site evidence do not fabricate a session.

**Anchors:** [app/monthly_report_training.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_training.py) — `save_training`, `new_month_training`; [app/monthly_report_setup.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_setup.py) — `new_month_draft`; [tests/test_monthly_report_training_years.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_training_years.py) — `test_year_change_reuses_exact_year_and_keeps_other_sites`; [tests/test_training_rollover_regressions.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_training_rollover_regressions.py) — `test_two_saved_rollovers_do_not_grow_tables_or_rewrite_prior_history`; [tests/test_training_requirement_identity.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_training_requirement_identity.py) — `test_each_person_site_status_and_missing_course_remains_independent`; [tests/test_training_event_site_scope.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_training_event_site_scope.py) — `test_old_ready_receipt_is_revalidated_before_current_or_historical_publication`.

### capital_proposal_revision

**Actions**

1. Save September A1/A2/B1/B2 reports, then correct or omit a carried Capital row in October A1.
2. Reimport its same consumed physical source; separately inspect Pending and Declined proposal rows with source dates.
3. Inspect October A2/B1/B2 and all September snapshots; separately compare an explicitly approved #684 Capital master API version, without treating the report-only correction as a master update.

**Expected boundary**

- The implemented Capital replay guard does not silently revive that consumed corrected/omitted row or append a duplicate.
- Pending, Declined and unknown remain distinct; the report's source history is not a new monthly event.
- Other reports and prior snapshots remain unchanged; no shared Capital master is created by the report correction.

**Current main**

- Merged #544 Capital replay and #687 general Starting Report Omit-reversal edit retention protect report choices, and proposal decisions remain distinct.
- Merged #684 provides revisioned contract/site Capital master API selection, but no ordinary report-editor approval/replacement workflow or automatic migration.

**Pending or decisions:** Connect the merged #684 master API to a reviewed, explicit editor approval/use flow only after the #492 owner defines authority; independent native/served acceptance remains.

**Anchors:** [app/monthly_report_start_replay.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_start_replay.py) — `_guard_carried_capital_tables`, `merge_starting_drafts`; [app/monthly_report_followups.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_followups.py) — `seed_followups`; [tests/test_monthly_report_capital_source_replay.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_capital_source_replay.py) — `test_reimport_keeps_explicit_report_omission`; [tests/test_monthly_report_proposal_table_carryover.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_proposal_table_carryover.py) — `test_actual_import_reopen_manual_edit_reimport_and_two_rollovers`; [app/monthly_report_capital_master.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/app/monthly_report_capital_master.py) — `load_capital_master`, `select_capital`; [tests/test_monthly_report_capital_master.py](https://github.com/evanroden/msapo-generator/blob/9cc96e6265fbf0ce40dbacf8d013cdc6b612e549/tests/test_monthly_report_capital_master.py) — `test_report_only_edits_omission_and_history_never_advance_contract_master`.

## Non-destructive migration proposal

This is a plan for separately authorized future work. No inventory of production data or migration has been performed for this document.

1. Inventory records read-only by canonical contract, explicit site, profile, year/month, standing revision and report revision. Keep original hashes, scope/approval receipts, unknown values and explicit exclusions. Separate working-copy state from published history.
2. Preserve current stores and their existing behaviors. The shared ENFRA branding catalog is not a legacy mistake to remove. Legacy global workflow records are already read-only adoption candidates, with an existing origin/receipt review path; never assign a new contract by filename or resemblance.
3. Resolve only the missing policy needed by the particular change. For capacity, clarify any broader site applicability. For subcontractors, preserve the merged #686 explicit site-scoped roster publication/use and decide any effective-status policy. For Capital, preserve merged #684 approval/selection API and define its still-missing ordinary editor flow. This matrix chooses no competing implementation.
4. Reuse existing validation, named/confirmed actions, CAS locks, bounded reads and immutable history. Keep source hashes and approval semantics distinct. A failed standing publication must not replace the old head; a report-only operation must not be repurposed as a broader migration.
5. Preserve both versions during compatibility work. Test read/reopen with the supported old and new code, original/asset inventories, pinned reports, reviewed adoption, stale revisions and each site/month boundary. Keep any deliberate data conversion separate from ordinary open, preview and layout.
6. Qualify the final integrated tree before release: synthetic storage/history/conflict checks, native UI delivery, authentic source mapping when authorized, complete Word/PDF output and served reopen/month rollover. Missing or queued evidence stays missing or queued; a specification test is not enforcement or production acceptance.

## Open choices and ownership boundaries

Thermal capacity's broader sharing authority remains unresolved by [#470](https://github.com/evanroden/msapo-generator/issues/470) and [#287](https://github.com/evanroden/msapo-generator/issues/287). The current site-partitioned first-fill/correction mechanism remains in place.

Merged [#686](https://github.com/evanroden/msapo-generator/pull/686) provides explicit contract/site-scoped subcontractor roster save/use; [#488](https://github.com/evanroden/msapo-generator/issues/488) still owns publisher/effective-status policy. Closed alternative [#563](https://github.com/evanroden/msapo-generator/pull/563) is not combined. Merged [#684](https://github.com/evanroden/msapo-generator/pull/684) provides the contract Capital master API; [#492](https://github.com/evanroden/msapo-generator/issues/492) still owns its future ordinary editor approval/use and served acceptance. This documentation creates no new authorization.

The general Starting Report Omit/reinclude edit-retention repair [#687](https://github.com/evanroden/msapo-generator/pull/687) is merged. It does not authorize overriding other source, site or output review gates. Other active repairs and the release queue remain separately owned.

## Verification and completion limits

The new ownership tests validate this documentation: complete rows, approved vocabulary, real code/test symbols, evidence links, Markdown/JSON agreement and the distinction between current and proposed behavior. They do not execute the application or grant policy approval.

A separate local support selection on audited main completed **183 existing synthetic tests in 14 modules, with zero skips**, covering workflow source/contract boundaries, annual Training and rollover, directory defaults/automatic keeping/refresh, capacity first fill and history, library snapshots, branding and org-chart defaults. Two expected openpyxl fixture-title warnings occurred. These results support only the tested current mechanisms; they do not turn the six walkthroughs into executed acceptance or cover every row's output and native interaction.

No current-PR hosted result, native browser journey, genuine customer document, live data migration, deployment or owner acceptance is claimed here. Keep #470 and dependent acceptance issues open for their remaining decisions and applicable served/output evidence. Jamie owns integration, merges and release.
