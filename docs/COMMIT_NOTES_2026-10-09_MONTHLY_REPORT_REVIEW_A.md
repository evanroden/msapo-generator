---
document_type: implementation_checkpoint
date: 2026-10-09
base_commit: f685aaa10285bce9587a4998ff0462894c5741ab
status: local_validation_complete_publication_pending
---

# Review A fixes and thirteen section reviews

The owner requested the six confirmed defects be addressed, then one dedicated
reviewer for each report section. Work resumed from the uncommitted section
experience increment. Its MBCx and ambiguous-price-heading changes are included,
with additional rollover protection discovered during this review.

## Reported defects

| Finding | Implemented behavior |
|---|---|
| Lowercase contract directory crashes landing | Canonical case/spacing identity plus collision-resistant card keys. Legacy paths and history remain readable. |
| Duplicate custom site crashes repeatedly | Validate selected/custom sites before rendering their widgets. Show a recoverable warning and preserve text for correction, including standalone import. |
| Nameless directory read/write/restore | Require entered editor name before contacts/history load or render. Clearing the name hides them. Report contact comparison uses the same rule. |
| Renamed group prints old cover | Refresh current title/scope/site labels on resumed working drafts without overwriting their schema or historical snapshots. DOCX regression checks actual cover text. |
| Second import after reviewed contact table fails | Ignore unused incoming template schemas. Align genuinely compatible contact headings; preserve manual rows and unknown columns. Real schema conflicts still block. |
| Small XLSX causes large XML tree allocation | Stream all workbook XML through callbacks without building trees. Global node/text/depth/name budgets include ignored nodes, attributes, namespaces and metadata. Repeated-node crafted ZIPs reject below 8 MB traced peak; distinct-name files reject below 2 MB. |

Directory removal is a confirmed, attributed archive with revision guards and
restorable history. It does not delete source workbooks, contacts or snapshots.

**Access limitation:** an entered name is not authentication. The owner previously
deferred passcodes while testing; this patch does not claim confidentiality or
prevent someone entering a name from accessing shared content. Existing reports
remain shared. Revisit authenticated access before ending public testing.

## Review friction and output corrections

- Preserve image approval through no-op editor rendering, unchanged merges and
  verified shared-logo insertion. Monthly content edits no longer reset the
  unrelated standing-information review.
- Bound prior utility/MBCx updates to their actual reporting period. Keep source
  evidence and require current-period confirmation before final output. Legacy
  monthly MBCx prose can no longer silently become an approved standing update.
- Corrected CMMS imports merge known schemas by site/WO or month/site. Conflicting
  known values reject the entire prepared batch; blank fields may gain values.
- Completed-work suggestions exclude negated, recommended and future/conditional
  work. Original text remains available for manual review.
- Proposal decisions remain Pending/Approved/Declined/On hold/Not confirmed, apart
  from issue lifecycle. Carried issues retain evidence and wrapped descriptions;
  exact no-issues declarations do not become ongoing issues.
- Organization replacements replace just their named part. Saved contact/vendor
  pages remain visible and editable. Unknown MSA/RFI statuses and partial equipment
  replacement dates remain text instead of crashing or inventing precision.
- Utility results have a clear upload classification/destination. New utility and
  capital sections no longer invent pending-approval/no-recommendations claims.
- Existing notes attached to page/table sections are visible. Training and issue
  photos can be appended. Image-only replacement of a whole page set is explicit
  and optional. MBCx source-linked wording has one editor, retaining its evidence.

## Dedicated section reviews

Thirteen separate reviewers examined first use, partial updates and returning
months against the implementation. This is an audit with bounded improvements,
not a claim that thirteen complete new editors are deployed. See the original
[section designs](MONTHLY_REPORT_SECTION_DESIGNS.md) for fuller acceptance cases.

| Section | Implemented in this increment | Next distinct workflow |
|---|---|---|
| Cover/design | Reuse reviewed shared-logo approval. | Assembled cover first; preserve existing cover by default on partial import; one optional branding area. |
| Organization | Contact-page change controls; replacement substitutes one part; hide unused import replacements. | Four previews with Change beside chart/daytime/after-hours/contacts; optional conversion to editable chart. |
| Activity | No-op approval retention; CMMS conflict rejection; exclude noncompleted action suggestions. | Three tasks: completed work, totals, photos; review only unresolved mapping; retain verified historical totals. |
| Scorecards | Utility uploads, blank honest defaults, period-bound carried results. | One utilities/capacity workspace; classify imported tables conservatively; native chart-page preservation. |
| MBCx | Dedicated status/pages UI, no assumed status, period check, single source-linked editor. | Section-local PDF/Word upload with fixed destination and one apply action. |
| Maintenance | Atomic prepared-batch merge rejects corrected-WO/count conflicts. | Work and pages together; actual header-row selection; page-specific period decisions. |
| Subcontractors | Unchanged content keeps approval; pictures visible beside tables; unknown agreements preserved. | Vendor/site/service identities, explicit agreement states and matched change decisions. |
| Water | Previously hidden findings visible in page editor. | Service-visit cards, local upload, persistent open concerns independent of monthly attachments. |
| Equipment issues | Wrapped descriptions, no-issues declarations and retained resolution evidence fixed; add photo. | One issue list with Still ongoing/Update/Resolved; optional evidence fields. |
| Capital | No invented no-recommendations note; existing notes visible; partial/unknown timing editable. | Recommendation cards, readable table labels and heading correction for legacy primary schemas. |
| Proposals | Correct decision lifecycle and omission language. | Compact carried proposals plus New proposals; optional supporting details. |
| Training | Append supporting photos without replacing existing content. | Separate current training from dated training-history ledger. |
| Appendix G | Text statuses; preserve original symbols in legacy Boolean schema. | Requests tied to selected sites; explicit matched updates; suppress empty appendix in effective output. |

## Remaining concrete findings, not silently marked fixed

1. Per-picture approval remains block-wide. A genuine caption/text/picture change
   can require other pictures in that block to be rechecked. Persist per-asset,
   caption and source review before promising only changed-picture review.
2. Rollover clears historical work-order/training table rows from the new draft.
   Originals/snapshots retain them. Implement a schema-aware dated ledger; simply
   retaining an undated table could misrepresent prior work as current work.
3. Imported scorecard tables default to thermal capacity even when they contain
   monthly utility data; this can bypass utility-period review. Add explicit or
   conservative schema routing without losing unknown tables.
4. Vendor/RFI reimports can retain old and changed rows, and arbitrary row site
   names are not constrained to report membership. Structured record identity and
   explicit site matching are needed. No silent guessed matching is authorized.
5. Prior/undated service actions still need better page-specific period handling;
   current stale-source warnings are not equivalent to confirmed current work.
6. Multi-date service packets, spreadsheet title/header rows, water open concerns,
   mixed contact tables/images and primary-table ambiguous-heading repair need
   dedicated workflows. Full Word-chart preservation remains organization-only.
7. Shared upload/review/prepare/apply controls remain. The named section-local
   workflows above are the next implementation, not already shipped.

## Validation and release

Focused regressions cover all six owner reports, recoverable directory archives,
new image/period behavior, proposals, issues, org replacement and utility uploads.
The final full local run passed 1110 tests, skipped 8 (renderer/CI-dependent).
Independent release review then found ElementTree caches distinct expanded tag
names even with a SAX target. A follow-up caps the global name vocabulary and
expanded name bytes, including attributes and namespace expansion. Dedicated
regressions cover all four XML parts and cross-part name budgets. Exact-head CI
must run with real LibreOffice installed before merge. Compilation, changed-file Ruff F/E9 and diff checks passed. Broader Ruff
also found two preexisting findings in unrelated document_generator.py; unchanged.

No real contacts, private documents, runtime images or output reports are committed.
Render verification remains public-only per the existing owner instruction.
No persistent synthetic production profile or directory should be created for QA.
Publication, final CI and public verification are recorded in the next checkpoint.

Rollback: revert the feature merge. Preserve newer snapshots before rollback;
mbcx_status, utility source classification and proposal statuses need this code for
their intended editor behavior. There is no destructive runtime migration.
