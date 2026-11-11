# A07 — MSAPO Azure App Service candidate, no provisioning

**Status (2026-11-11): PREPARATION ONLY.** Based on A01 draft `docs/azure/MIGRATION_MANIFEST.md` in PR #849 (not merged). Source main inspected at `57c5cd87e3e441dfea3cddbc666248f8e469d986`. This is *not* a production-ready design, approved data service, or cutover decision. Never put ENFRA IDs, exported app settings, secret URIs, personnel data or customer files in this public repository.

## Candidate and invariants

- **Runtime:** keep `Dockerfile` unchanged: Ubuntu 24.04, Python 3.12, locked Streamlit 1.61.1, LibreOffice Writer/Calc, approved fonts and `runtime/check_renderer.py`; keep all three Streamlit frontend patch scripts and `run_web.py`. Build with `APP_GIT_COMMIT=<release SHA>` and `PUBLIC_SITE_ORIGIN=https://<approved-host>` and pin ACR image by `sha256` digest. A container started by its current CMD binds `0.0.0.0:8501`, health `/_stcore/health`.
- **App Service:** single Linux custom container **classic Docker model**, `linuxFxVersion=DOCKER|<ACR>/<repository>@sha256:<digest>`; **not** `sitecontainers`. `WEBSITES_PORT=8501` only for this classic model. Do not add `targetPort`, ACA ingress/revision/replica/probe fields, Docker registry passwords, or sidecar `containerPort`. No deployment slots or auto-swap; no autoscale, plan capacity one. Linux WebSockets do not depend on `webSocketsEnabled` (Windows-specific). `alwaysOn=true`, `healthCheckPath=/_stcore/health`, HTTPS only, minimum TLS 1.2, FTPS disabled, private inbound endpoint, approved VNet integration, ACR private endpoint and managed-identity ACR pull.
- **Security:** existing Streamlit `enableCORS=true`, `enableXsrfProtection=true`, `maxUploadSize=512` stay unchanged. App Service Auth V2 requires single-tenant Entra and explicit assigned group membership; **no anonymous paths**, including root or Streamlit WebSocket route. A05 must confirm health-check semantics with that auth policy. Secrets are app settings with Key Vault references; A05 supplies approved vault, identities, enterprise auth registration and group IDs. RBAC grants *pull* and *secret user*, never Contributor to runtime identity.
- **Persistence:** current `/test1`, SQLite and filesystem semantics are not proof of App Service compatibility. Proposed App Service custom mount is `/mounts/msapo` and the app has an `EPC_DATA_DIR` override, but exact path interactions must be audited by A03. The Bicep defaults to **no storage mount**, so the checker fails closed. Set `enableQualifiedFilesMount` only after A03 has approved an actual share/key policy and proven ownership, chmod, hard links, flock/lockf, SQLite concurrency/restart and backup/restore on App Service. An SMB Azure Files mount is **not** a default acceptance. A03 may instead deliver a managed SQL adapter and approved file/object storage; in that case revise the IaC and checker together and do not mount raw SQLite as the authority. Do not declare the app usable until persistence is wired and qualified. Key-based custom mounts conflict with storage policies that disable account keys; choose another design if forbidden.
- **Temporary files:** only disposable conversion scratch, LibreOffice profiles and previews may use `/tmp`. They do not survive restart; verify disk budget, isolation per conversion, cleanup and timeout behavior. Never equate `/home` persistence with a mounted data directory. No raw invoice/report/AI prompt content in log files or telemetry.

## Bicep layout and inputs

`infra/azure/foundation.bicep` bootstraps the per-environment private Premium ACR, runtime managed identity, AcrPull role and ACR private endpoint/DNS. A06 then pushes the approved image digest from an ENFRA private runner. `infra/azure/main.bicep` consumes the **existing** ACR/identity and provisions one Linux P1v3 plan worker, App Service, Entra Easy Auth, private App Service endpoint plus supplied DNS zones/subnets, Log Analytics/App Insights and App Service diagnostics. A05 separately grants the identity Key Vault Secrets User on the approved vault (cross-resource-group RBAC is not silently granted by this template). Production and nonproduction require **different resource groups, apps, plans, registries, identities, Entra groups and durable stores**. DNS zones or shared corporate management assets may be separately owned as approved. `nonprod.parameters.json` and `prod.parameters.json` are deliberately non-deployable placeholders. No provisioned database is implied.

Storage, networking, identity and CI handoffs:

| Dependency | Owner by this request | Required contract before deployment |
|---|---|---|
| Storage and transactional state | A03 | Selected approved DB and durable originals/artifacts, migration adapter, recovery and backup, qualified mount or no-mount revision; preserve record IDs and Smartsheet atomic claims. |
| Identity, private networking and authorization | A05 | Vault/secret names, tenant/group/app registration, private endpoints/subnets/DNS/runner route, allowed outbound AI and Smartsheet egress, health-check exception policy without anonymous application access. |
| Build, signed image and deployment workflow | A06 | Protected environment approvals, OIDC federation compatible with actual ENFRA GitHub host, immutable digest, no duplicate Render/App Service deployment, synthetic acceptance identity and actual URL. |
| Final release / source-of-truth | A01 and P20 | Reconcile moving PR heads, select final main SHA, acceptance matrix and rollout/rollback authority. |

## No-provisioning local checks

```bash
# From repository root. No Azure credentials or live secrets needed.
python3 -m pytest -q tests/test_appservice_config_check.py
python3 -m py_compile scripts/appservice_config_check.py scripts/azure_config_check.py
python3 -m json.tool infra/azure/nonprod.parameters.json >/dev/null
python3 -m json.tool infra/azure/prod.parameters.json >/dev/null
az bicep build --file infra/azure/foundation.bicep --outfile /tmp/msapo-foundation.json
az bicep build --file infra/azure/main.bicep --outfile /tmp/msapo-appservice.json
# The last command REQUIRES a local Azure CLI/Bicep installation, but provisions nothing.
```

After ENFRA provides a test subscription and filled *restricted* parameter file, run the following **without provisioning** (Azure authentication and resource-group read permission required):

```bash
az account set --subscription '<APPROVED-SUBSCRIPTION>'
az deployment group validate -g '<APPROVED-NONPROD-RG>' -f infra/azure/foundation.bicep \
  -p @'<RESTRICTED-nonprod.foundation.parameters.json>'
az deployment group validate -g '<APPROVED-NONPROD-RG>' -f infra/azure/main.bicep \
  -p @'<RESTRICTED-nonprod.parameters.json>'
az deployment group what-if -g '<APPROVED-NONPROD-RG>' -f infra/azure/foundation.bicep \
  -p @'<RESTRICTED-nonprod.foundation.parameters.json>'
az deployment group what-if -g '<APPROVED-NONPROD-RG>' -f infra/azure/main.bicep \
  -p @'<RESTRICTED-nonprod.parameters.json>'
```

Bootstrap ordering if later approved: deploy foundation in the target RG, configure private DNS/runner route and A05 vault RBAC, push approved image to ACR via A06, then deploy main with the immutable digest. No `az deployment group create` until signed A01/A03/A05/A06 gates. The Bicep does not create release or deployment slots; A03 must not point a second app/slot at a shared writable SQLite directory.

## Build contract and focused runtime acceptance

```bash
SHA=$(git rev-parse HEAD)
ORIGIN='https://<approved-app-host>'
docker build --build-arg APP_GIT_COMMIT="$SHA" \
  --build-arg PUBLIC_SITE_ORIGIN="$ORIGIN" -t msapo-a07-test:"$SHA" .
docker run --rm -p 8501:8501 -e EPC_DATA_DIR=/tmp/msapo-a07 \
  --name msapo-a07 msapo-a07-test:"$SHA"
# In a second terminal:
curl -fS http://127.0.0.1:8501/_stcore/health
```

Use **only synthetic sources**, no real credentials or Smartsheet calls. In the actual authenticated nonprod app, verify: (1) browser login and tenant/group deny; (2) `/_stcore/stream` upgrades to WebSocket through the ingress and remains open across idle and rerun; (3) health returns successful status to the App Service platform without anonymously exposing report endpoints; (4) 512 MiB synthetic upload boundary (plus actual accepted smaller importer caps), one concurrent and one interrupted conversion; (5) DOCX/PDF and spreadsheet downloads preserve exact bytes and fonts; (6) LibreOffice shape/pagination and frontend/date patches; (7) output temp paths, scratch cleanup, 5xx/cancel/restart, SIGTERM and restart during conversion with no partial authoritative writes; (8) browser reconnect preserves or clearly reports session loss; (9) two independent sessions, no overlapping writers; (10) recovered saved reports/Smartsheet idempotency and storage backup/restore. Monitor RSS, CPU, file system capacity, timeout, WebSocket 101/4xx and cold-start latency. **None of these live tests has been run on Azure.**

## Read-only App Service export verification

**Run only inside an approved restricted environment; exports can contain secret values.** Never attach raw exports to GitHub issues or public PRs. Collect the App Service resource, website config, appsettings, App Service auth, mount mapping and plan as JSON:

```bash
umask 077
export RG='<APPROVED-RG>' APP='<APPROVED-APP>' PLAN='<APPROVED-PLAN>'
mkdir -p /tmp/msapo-a07-private && cd /tmp/msapo-a07-private
az webapp show -g "$RG" -n "$APP" -o json > site.json
az webapp config show -g "$RG" -n "$APP" -o json > config.json
az webapp config appsettings list -g "$RG" -n "$APP" -o json > settings.json
az webapp auth show -g "$RG" -n "$APP" -o json > auth.json
az webapp config storage-account list -g "$RG" -n "$APP" -o json > storage.json
az appservice plan show -g "$RG" -n "$PLAN" -o json > plan.json
python '<CLONE>/scripts/azure_config_check.py' --platform appservice site.json \
  --config config.json --settings settings.json --auth auth.json \
  --storage storage.json --plan plan.json
# Securely delete/restrict exports per enterprise retention policy (do not upload).
```

The App Service checker rejects ACA exports. The older `scripts/azure_config_check.py --platform containerapps app.json --auth auth.json` still checks ACA exports, using the original legacy validation with no changes in its platform assumptions. A zero exit status means **only** that schema/configuration fields passed; it cannot approve storage, network access, data migration, auth group membership or real rendering.

## Release and rollback

1. A01/P20 freeze **one exact release commit** and completed acceptance ledger. A06 builds from that commit with the original renderer, fonts and three patches, signs/scans and records digest + build args; A05 approves immutable identity and private routing. Record a sealed config baseline and previous known-good digest. Pin nonprod, then production to that digest; never enable registry webhooks or alternate deployment workflows. Preserve Render writes until the explicit single-writer cutover.
2. **No staging slot by default.** Slots can have their own app settings and isolate databases, but swap/migration safety is not established and slots may continue running the old container. Revisit only after A03 proves isolated writable state and A06 enforces no overlap.
3. If deployment fails **before data cutover**, restore `linuxFxVersion` to the recorded prior digest and restart the app in a controlled window; restore the previous App Service config/auth/Key Vault references by versioned, restricted change records. A traditional rollback cannot undo migrated data/schema or in-flight submissions. After cutover, freeze writes first, use A03 recovery/checkpoint with explicit source-of-truth choice, and then restore an agreed image/config pair. Never run Render and Azure as simultaneous writers.
4. Keep old production endpoint read-only/suspended until signed acceptance, then update DNS and `MONTHLY_QA_PUBLIC_URL` with A06. Do not turn off Render QA without replacing exact served-digest and native-download acceptance. Verify `About` SHA, HTTP health, download bytes, activity logs with privacy controls, and a documented restore drill.

## Evidence at preparation time

- PASS (static): inspected current main Dockerfile, requirements.lock, run_web.py, .streamlit/config.toml, render.yaml, scripts/host_check.py and scripts/azure_config_check.py. The container command binds port 8501 and has an in-image curl health check at `/_stcore/health`. The image keeps LibreOffice Writer/Calc, all declared fonts and all frontend patch calls.
- PASS (offline): Python syntax check and synthetic App Service checker unit tests. Parameter JSON parsing is valid; templates intentionally have non-deployable placeholders.
- NOT RUN (environment unavailable): `docker build/run`, LibreOffice render, Bicep compilation, ARM validate/what-if, nonprod Azure health/WebSocket/upload/download/conversion, scale/workers, SIGTERM, network and storage qualification. There is no installed Docker, Azure CLI or Bicep binary in this execution environment.
- BLOCKED: A01 approval, A03 durable transactional storage + mount contract, A05 Entra/VNet/Key Vault and A06 CI/deploy authority, plus final release SHA/image digest.

### Primary platform references

- https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container
- https://learn.microsoft.com/en-us/azure/app-service/configure-sidecar
- https://learn.microsoft.com/en-us/azure/app-service/configure-connect-to-azure-storage
- https://learn.microsoft.com/en-us/azure/app-service/monitor-instances-health-check
- https://learn.microsoft.com/en-us/azure/troubleshoot/azure/app-service/faqs-app-service-linux
