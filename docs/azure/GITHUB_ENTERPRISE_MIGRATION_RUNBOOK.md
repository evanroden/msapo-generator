# A02 — MSAPO enterprise GitHub migration runbook (DRAFT)

**State: PREPARATION ONLY.** No repo transfer, import, credential copy, collaborator removal, rewrite, policy change, Azure provisioning, production routing, cutover or deployment is authorized.

**Contract:** A01 docs/azure/MIGRATION_MANIFEST.md (draft PR #849). Functional release remains with P20 in issue #270. Inventory date 2026-11-11 UTC. Source https://github.com/evanroden/msapo-generator, source repository ID 1166801522, default branch main, audited 57c5cd87e3e441dfea3cddbc666248f8e469d986. A01 may move; refresh before every final step. Store all private ENFRA values and inventory exports in a separate restricted change record, not this public repository.

## 1. Decision and exact prerequisites

The GitHub account available to this preparation lists no organizations. Target enterprise host (github.com / GHE.com / private GHES hostname), edition/version, organization, repository path, visibility/retention, enterprise policy and named migration approvers are UNKNOWN, not absent. Obtain an authoritative restricted decision from ENFRA GitHub administrators before selecting an execution path.

Check: source administrator and destination repository-creation rights; transfer policy and Enterprise Managed Users restrictions; target name collision; SSO/SCIM requirements and required membership; whether external collaborators or forks are permitted; target rulesets; Actions retention; GitHub Apps/runners; secure environment approval and branch permissions; target Azure OIDC issuer support; source secrets/history classification; and legal ownership. Do not publish names of private organizations, teams, tenants or service identities.

**Preferred supported method by target:**

1. Ordinary Enterprise Cloud organization on github.com, when transfer permitted: native GitHub repository transfer from the personal account. Preserves repository identity and Git commits, issue/PR/review conversations, wiki, stars/watchers and attached Git LFS objects. Hooks/secrets/deploy keys are associated with the moved repository, but MUST be re-audited against destination permissions; assignees outside the receiving organization can be cleared. Native GitHub.com transfers cannot target a different GitHub host or cross an incompatible managed-user boundary. Preserve a separate Actions evidence ledger; the transfer documentation does not guarantee indefinite historical run/check/artifact accessibility.
2. GHE.com or separate supported Enterprise Cloud location: GitHub Enterprise Importer (GEI), but first address source ownership. **GEI does not directly migrate repositories owned by personal user accounts.** To use GEI, a separately authorized initial transfer into an approved GitHub.com source organization is required. Conduct a trial, validate losses and approve a short final write pause; GEI does not support delta migrations. Do not create a staging org or transfer it during this preparation.
3. GitHub Enterprise Server: use the version-appropriate ghe-migrator organization-source export and target import, with an authorized intermediate source organization if necessary, GHES site-admin approval and trial. GitHub Enterprise Importer does not support this inbound GitHub.com→GHES path. Confirm capabilities in the exact GHES version; record missing metadata before approval.
4. Git mirror / ordinary Git import: tracks commits, tags/branches and repository files ONLY. It does NOT transfer issues, PRs, reviews, Actions logs/artifacts, rulesets or permissions. Treat as an unacceptable sole method for MSAPO; use only with separately authorized metadata export/recreation and explicit loss acceptance.

References: https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository ; https://docs.github.com/en/migrations/using-github-enterprise-importer/migrating-between-github-products/about-migrations-between-github-products ; https://docs.github.com/en/migrations/using-ghe-migrator/about-ghe-migrator .

## 2. Source inventory (2026-11-11 snapshot)

- GitHub REST confirms repository ID 1166801522, public, personal owner, main at 57c5cd87e3e441dfea3cddbc666248f8e469d986, issues enabled, wiki and discussions disabled. Releases list empty. Repository rulesets list empty, but direct main branch protection API returns 403 Resource not accessible by integration: **branch protection remains unverified**. Tag ref endpoint returned 404; the zero-tag claim needs a separate tag-list inventory.
- GitHub search reports 109 lifetime issues and 740 lifetime PRs. The pull list showed **24 open PRs** at the initial inspection (before this A02 draft #850), including A01 draft #849 and P20 draft #844, active repair PRs and #26 strategic provider refactor. The REST open_issues_count of 128 includes PRs and is not an issue-only count. Reviews are real records: source PR #827 had one COMMENTED review, while #828 had five COMMENTED reviews at review sampling; #844 and #849 had no submitted reviews then. **This sample is not a repository-wide review count**; enumerate every PR's reviews, inline threads and comment events in the restricted full reconciliation.
- Main contains **20 Actions workflows**. All inspected files give the workflow token contents: read. Tests builds and smoke-checks a local container. Monthly Isolated Live Acceptance is triggered by successful Tests on main and still targets Render (MONTHLY_QA_PUBLIC_URL default to https://msapo-generator.onrender.com). Two manual shared-redeploy evidence workflows are read-only. No Azure deploy job was observed among these files. Render dashboard auto-deploy settings were not readable; no claim is made about external Render configuration.
- The exact main Git tree was recursively enumerated without truncation: 1,558 entries, **zero gitlinks/submodules, zero .gitattributes, zero .gitmodules and zero CODEOWNERS**. The .github tree contains only workflows. No tracked Git LFS configuration or submodule definition was found; a separate LFS remote inventory remains a required acceptance step. Wiki reported disabled and releases API returned [].
- A follow-up eight-page read-only branch enumeration returned **762 branches** (seven full pages of 100 and one page of 62); Git matching tag refs returned **zero tags**. These counts can change as other agents work and must be repeated before trial/final migration. Submodule and LFS tracked-path configuration was absent in the 1,558-entry source tree; check LFS remote objects and all release assets separately. Issue attachments, fork heads, packages, environment protections, inherited rulesets, team memberships, runner groups, GitHub Apps, hooks, variable/secret names, audit logs, security findings and Actions history need a privileged inventory.
- Source-of-truth references include docs/README.md (mandatory index for top-level docs), docs/AZURE_MIGRATION.md (historical Azure Container Apps guide), Render render.yaml, live QA workflow, source PR/issue links and external integrations. Scan repo and every automation, badge, status callback and Azure IaC reference for stale source URLs.

### Metadata-preservation and reconciliation matrix

| Item | Same-host native transfer | GEI / cross-host target | Acceptance test |
|---|---|---|---|
| Commits, branches, tags, annotated tags | Same Git repository history | Import supported Git refs | Compare every ref SHA/object and branch HEAD |
| Release records and assets | Retain association | Supported with size limits; GHES trial varies | Compare asset counts, sizes and SHA256 |
| Issues, labels, comments, milestones | Retained; assignees may change | Import subset; identities and numbers can remap | Compare by state, author mapping, body, attachment |
| PRs, conversations, approvals, reviews, inline threads | Retained in same repository | Import metadata with limitations | Per-PR review/comment/thread mapping and head refs |
| Wiki | Moves if enabled | Supported with attachment caveats | Compare wiki pages/attachments (source disabled) |
| LFS objects | Automatic asynchronous transfer | GEI explicitly excludes LFS objects | Count pointers, transfer separately if needed, hash |
| Submodules | Gitlink retained, URL unmodified | Gitlink retained, remote auth must be repaired | Recursive gitlink SHA and URL reachability |
| Actions workflow YAML | Git-tracked | Git-tracked | Compare workflow paths/triggers |
| Historical Actions checks, status runs, logs/artifacts | Not guaranteed indefinitely by transfer docs | **Not migrated by GEI** | Restricted, independently retained run→commit evidence |
| Rulesets, required check contexts, CODEOWNERS | Reconcile under org policy | Rulesets not migrated in GEI; branch protection partial | Effective rulesets, owners and expected apps |
| Teams, access and collaborators | Receiving org policies apply | Access/team membership not migrated in GEI | Least-privilege user/team matrix and assignee audit |
| Environments, reviewers, deployment permissions | Revalidate under target org policy | Not migrated by GEI | Protected prod approval and exact job permissions |
| GitHub Apps, hooks, deploy keys and runners | Verify remnant installations/associations | Apps/runners not migrated; hooks re-enable | Installation scopes, hooks and runner eligibility |
| Packages, secrets and Actions variables | Verify, rotate as policy requires | Packages, variables and secrets not migrated by GEI | Names/permissions only; credentials remain in vault |
| Azure OIDC federation | Trust must be revalidated | Reconfigure with new issuer/subject | A06+A08 approved audience, branch/environment subject |
| Stars/watchers, reciprocal links | Native retains stars/watchers and redirects | GEI excludes stars/watchers and some link relations | Map/remediate and record accepted losses |

No Git mirror should be described as preserving collaboration metadata. For native transfer validate repository ID and original issue/PR numbers after transfer; crosswalk only if something changes. For GEI/ghe-migrator produce restricted source→destination mapping of repository, issue, PR, review thread/comment, attachment, milestone and actor IDs plus old/new URLs and migration status. Include #270, open PRs and references from external integrations; record unmapped entries as exceptions. Never place a crosswalk containing private target identities into the public repository.

## 3. Read-only source inventory commands

Run with approved authentication, from a restricted encrypted operator workspace, **not from source CI**, and do not publish command output. gh api returns metadata (not secret values). Any 403 is an access gap, never evidence a feature is absent.

    set -euo pipefail
    SRC=evanroden/msapo-generator
    gh api "repos/$SRC" --jq '{id,full_name,default_branch,visibility,has_wiki,has_issues,open_issues_count}'
    gh api --paginate "repos/$SRC/branches?per_page=100" --jq '.[].name' > branches.txt
    gh api --paginate "repos/$SRC/tags?per_page=100" --jq '.[].name' > tags.txt
    gh api --paginate "repos/$SRC/releases?per_page=100" --jq '.[].tag_name' > releases.txt
    gh api --paginate "repos/$SRC/issues?state=all&per_page=100" --jq '.[]|select(.pull_request==null)|[.number,.state,.updated_at]|@tsv' > issues.tsv
    gh api --paginate "repos/$SRC/pulls?state=all&per_page=100" --jq '.[]|[.number,.state,.draft,.head.ref,.head.sha,.base.ref,.updated_at]|@tsv' > prs.tsv
    gh api "repos/$SRC/rulesets"
    gh api "repos/$SRC/branches/main/protection"
    gh api "repos/$SRC/environments"
    gh api "repos/$SRC/hooks"
    gh api "repos/$SRC/actions/permissions"
    gh api "repos/$SRC/actions/runners"
    gh api "repos/$SRC/actions/secrets" --jq '.secrets[].name'
    gh api "repos/$SRC/actions/variables" --jq '.variables[].name'
    gh api --paginate "repos/$SRC/deployments?per_page=100" --jq '.[]|[.id,.environment,.sha]|@tsv'
    gh api --paginate "repos/$SRC/actions/runs?per_page=100" --jq '.workflow_runs[]|[.id,.head_sha,.conclusion,.created_at]|@tsv'

For each PR: query pull reviews, issue/PR comments, inline review threads, commit statuses/check runs and fork heads; compare user attribution and review states. Export to the restricted ledger under appropriate retention and access controls. Enumerate releases and wiki, CODEOWNERS paths, environments, target rulesets/inherited policies, GitHub Apps, packages, webhook deliveries/config, runner groups, branch protections, required check app identifiers and action variable/secret NAMES. Do NOT export credential values.

From a separate temporary, read-only clone scan refs and code:

    git ls-remote --heads origin
    git ls-remote --tags origin
    git submodule status --recursive || true
    git lfs ls-files --all || true
    git grep -nEI '(github[.]com/evanroden/msapo-generator|msapo-generator[.]onrender[.]com|ghcr[.]io|onrender[.]com)' -- . || true
    git log --all --name-only --format='%H' | grep -Ei '(\.env|secret|credentials|private.?key|\.pem$|\.p12$|customer|receipt|invoice)' || true

Review matches with an approved scanner and a human classification decision; path names are leads, not proof of leaked secrets. GitHub Actions artifact logs may contain data, and secrets may exist in old commits: handle history and exports under restricted permissions. **No history rewrite or delete in this preparation.**

## 4. Open PRs and timing

Do not freeze repairs while preparing. P20 owns #270 release integration and resolves #844 and #828 moving-head differences. Record each PR's number, exact head SHA, updated_at, base, merge state, review state, required-check contexts and dependent integration. Refresh before each trial; open PRs and comments can change while inventories are being gathered.

Only an independently approved A12 final migration may establish a narrow T0 write hold. Native transfer should be arranged without prematurely closing PRs. GEI lacks delta imports: explicitly reconcile every commit/issue/comment/review from T0 to completion, or redo migration against a new freeze snapshot. PRs arriving during any paused window get a queue entry and owner acknowledgment; nothing silently disappears.

## 5. Source-of-truth transition, duplicate deployments and rollback

1. **Now:** existing github.com repository and Render remain authoritative; this draft PR is an inactive preparation artifact. No target deployment is permitted; local preflight JSON flags are both false.
2. **Trial:** after destination/prerequisites approved, perform supported non-production migration into a separately authorized trial space, compare every record class above and examine migration warnings. Do not turn on production workflows or trust.
3. **Before go/no-go:** final P20 release SHA and immutable image digest, evidence ledger, verified protected environment/rulesets, CODEOWNERS, runner and A06/A08 signed OIDC issuer/audience/subject checks; signed owner approval for accepted metadata losses.
4. **At separately approved A12 cutover only:** stop source merges/writes and Render auto-deploy, fence Render/app data writers and verify stopped; establish new enterprise repo as unique source of truth; explicitly enable ONE approved target release job after A08/A06/A04 validation. Retarget QA from Render only after authenticated App Service acceptance; update canonical repo URLs, badges, integrations, hooks, environment permissions and all required check contexts. Preserve old-path redirect if native transfer, and do not re-create a repo under the old owner/name.
5. **Rollback:** fence all destination deployments and writers before reverting traffic; restore application data only from a separately verified compatible backup. Never let Render and App Service write to the same SQLite database. Repository rollback does not imply database rollback.

Compare audit output from both sides: all Git branch/tag SHAs; counts and content of issues, PRs, reviews, comments, attachments, release assets, wiki and LFS; org/team permissions; effective policy; environments, runners and hooks; exact check names and run-evidence archive; OIDC trust; deployment image digest and served commit. Record failures/acceptance exceptions in a **restricted** report with timestamps. Final signoff: A01, A02, P20, A04, A06, A08, A11, A12.

No step in this runbook grants authority to perform a transfer, change visibility, remove collaborators, copy credentials, rewrite history, disable Render or deploy Azure.
