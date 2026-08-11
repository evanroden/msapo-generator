# Public repository and release audit

**Date:** 2026-08-11
**Scope:** current tracked tree, deployment examples, generated artifacts, and
release controls for Process Control

## Outcome

The tracked source tree is designed to be reviewable by ENFRA IT without
publishing a production credential, live form endpoint, employee profile,
uploaded quote/receipt, completed financial report, email draft, or local
application database.

The product owner explicitly approved retaining the account/site registry,
RRH asset registry, cost-code policy, and verified job-number catalog in the
public repository. Those datasets remain because they are functional source,
not accidental runtime output.

## Removed or externalized

- Generated Python bytecode and cache directories were removed from Git.
- Uploaded examples, rendered images/PDFs, local SQLite state, generated output,
  and `.env` remain ignored and untracked.
- The production Smartsheet form URL is no longer present in the current tree.
  `.env.example` uses a nonfunctional all-zero identifier, while `render.yaml`
  requires a private deployment value.
- The RRH administrator name and email are deployment variables. Public local
  defaults use an obviously synthetic name and the reserved `.invalid` domain.
- Tests use synthetic people, employee identifiers, vendors, addresses, and
  reserved example email domains.
- The author-credit test trigger contains a static synthetic quote only. It
  reads no uploaded example, calls no AI service, and performs no submission.

## Intentionally retained

- Account, facility, address, and asset mappings used by deterministic routing.
- RRH full asset UIDs, as required by the product owner.
- Site/cost-code business rules and the complete job-number dropdown catalog.
- ENFRA brand colors and layout rules; the alpha page does not present an ENFRA
  logo or an ENFRA wordmark at the top.
- The blank official reimbursement workbook and MSAPO document templates
  required to generate editable reports. Completed reports and receipt evidence
  are not tracked.

## Automated release guard

`tests/test_public_repository_hygiene.py` anchors itself to the repository and
fails when:

- a cache, upload, local database, email draft, image/PDF, completed workbook,
  or other generated artifact becomes tracked;
- a high-confidence Anthropic/GitHub/AWS key, private-key block, ENFRA email
  address, or non-placeholder Smartsheet form identifier appears in tracked
  text; or
- the Render blueprint stops requiring private approver, endpoint, token, or
  sheet-ID configuration.

The binary allow-list contains only the blank official JDE workbook and MSAPO
document templates. Adding another binary source artifact therefore requires an
explicit code-review decision.
The contract-registry test separately asserts the approved production inventory
of 36 non-RRH contracts, 106 raw site buckets, and 11,368 asset rows so an empty
or truncated replacement cannot silently remove all-account functionality.

## Git-history and incident boundary

The 2026-08-11 release audit scanned 776 reachable Git objects across the local
references. It found no Anthropic key, GitHub token, AWS access key, private-key
block, committed `.env`, receipt image, completed report, email draft, or SQLite
database. Historical commits do contain ENFRA email addresses and earlier
non-placeholder Smartsheet form identifiers; the product owner reviewed and
explicitly accepted those specific historical disclosures. The current tree
continues to prohibit both categories. The only historical `output` path was an
empty `.gitkeep`, not generated customer data.

A clean current tree does not erase identifiers from commits that were already
published. Before a rewritten history is force-pushed, repository owners must
assume any previously committed endpoint or business contact was copied. Rotate
or retire an exposed endpoint independently; history rewriting cannot revoke it
or remove it from existing clones and caches.

Rewriting published history and force-pushing `main` are destructive repository
operations. They require an explicit owner decision, coordinated clone reset,
and a configured authenticated remote. The release commit can make the current
tree safe without silently performing that separate operation.

## Deployment checklist

1. Configure `ANTHROPIC_API_KEY`, `RRH_APPROVER_NAME`, and
   `RRH_APPROVER_EMAIL` privately.
2. Configure the production `SMARTSHEET_FORM_URL` privately. Keep direct API
   mode disabled until its independent authorization and schema gates pass.
3. Confirm no secret value is entered into `render.yaml`, `.env.example`, a test
   fixture, issue, pull-request body, or CI log.
4. Run `python -m pytest -q`, `python -m py_compile app/*.py`, and
   `git diff --check` from the repository root.
5. Review `git status --short` and `git ls-files` before push. Only the blank
   reimbursement template may appear as a tracked spreadsheet/binary artifact.
