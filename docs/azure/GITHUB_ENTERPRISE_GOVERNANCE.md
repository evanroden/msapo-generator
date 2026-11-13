# Enterprise GitHub governance for MSAPO (A02 draft)

This is a proposed checklist, NOT a description of an approved ENFRA configuration. It implements the preparation scope of A01 draft PR #849, and leaves ongoing P20/#270 repair integration untouched.

## Ownership and privacy

Obtain exact GitHub host, edition/version, enterprise, organization, repository, repository-owner approval and creation/transfer/import permission in the restricted ENFRA change record. The public source does not establish these identifiers. A private repository is the recommended target if the enterprise permits it. Verify SAML/SCIM/Enterprise Managed Users constraints before choosing native transfer. Define least-privilege maintainers, DevSecOps, platform, application and read-only audit roles, and verify that no outside collaborators receive unauthorized access.

Establish a real .github/CODEOWNERS on the destination with approved existing team slugs; only an inert template is in this PR. Require CODEOWNERS review for workflows, Azure infrastructure, Dockerfile, dependencies, application, runtime, secrets interface, storage and migration code. Require PR review, checks on the exact head, conversation resolution, force-push/deletion protections, and stale review dismissal as approved by ENFRA. Do not assert source branch protection was absent: GitHub integration returns 403 on the branch protection API, despite listing no repository rulesets.

## CI, OIDC and release governance

Keep the current source CI and Render isolated synthetic live QA operating during preparation. The existing 20 workflow files are test/read-only-evidence oriented, and monthly-live-qa.yml has a Render default URL. No Azure deploy workflow was present in the inspected main branch. Avoid auto-disabling those gates.

Only A08 may introduce a deployment pipeline, with A06 credential/provider approval and A04 IAM validation. Require approved issuer, audience, exact subject scoped to a protected environment/ref, allowed runner network, token lifespan and Azure role assignments. Grant id-token: write only in the environment-protected deploy job, not repository-wide or to PR code. Never copy a service principal secret, token, OIDC subject containing restricted IDs, credential, or app installation identifier into this public repository.

Require immutable build provenance (exact release commit SHA, signed image digest, registry reference, verified served SHA). Production promotion must reuse the tested digest and require manual/environment approval; no rebuild of latest and no PR-triggered deploy. Required check contexts and their owning GitHub App must be remapped explicitly on the destination.

## Prevent two simultaneous deployment authorities

The current deployment source remains Render. Azure deployment remains disabled until an A12 change record confirms Render auto-deploy/writers have been fenced, P20 has chosen a frozen release SHA, approved enterprise protections are active, and A06/A08 have validated identity trust. JSON deployment-control flags in this PR are static preparation checks, not access control and not sufficient to authorize a deployment.

At cutover, verify BOTH external Render dashboard settings and enterprise GitHub environment controls. Only one production writer and one active release authority are permitted. The existing Render QA target fallback should be removed or retargeted only after authenticated Azure end-to-end verification. No simultaneous Render/App Service writing to the same SQLite store. If a rollback is required, fence destination writes first; git rollback does not roll back application data.

## Controlled-information separation

PUBLIC: this non-sensitive policy specification, source repository URL, role requirements, safe CLI examples, synthetic-only tests, and vendor documentation.

RESTRICTED: ENFRA organization/host when classified, identity-group roster, SSO settings, Azure tenants/subscriptions, federated credential subjects, runner network addresses, webhook payload settings, database backups, customer files, production CI logs/artifacts with customer content and all secret values. Public issue comments and PR bodies must not contain these records.

## Required signoffs (all outstanding)

A01 architecture/manifest; A02 GitHub owner/admin; A04 IAM/network; A06 AI/integration and credential policy; A08 CI/OIDC and environment gates; P20 functional release; A11 operations; A12 cutover authority. The written file alone is never an approval.
