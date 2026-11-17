# As-is Azure Container Apps: read-only control-plane observations (16–17 November 2026)

**Status:** observations only; nothing in Azure was changed. **Classification:** public, sanitized.
**Evidence reference:** `AZ-RO-20261116`, the owner's private notes. They hold the real names, image digests and raw command output; none of that belongs in this repository.
**Read:** 16 Nov 2026 20:30–21:05 UTC and 17 Nov 02:40–02:50 UTC, in the owner's signed-in Azure Cloud Shell, with the owner's own access: Contributor on one resource group and secrets officer on its vault.
**Refs:** #270, #877.

This is the first independent read of the existing Azure footprint. It replaces "unverified" and "unknown" with an observed state for the facts listed here in the [reconciliation](azure/ACA_APP_SERVICE_RECONCILIATION_2026-11-12.md), the [readiness delta](azure/ACA_ASIS_APP_SERVICE_READINESS_DELTA_20261112.md) and the [identity boundaries](azure/IDENTITY_SECRETS_AI_BOUNDARIES_2026-11-12.md). It authorizes nothing. **17 Nov 2026:** the owner has since decided to finish the move on these Container Apps instead of App Service and to keep this repository, made private later; the decisions and the task list are in [AZURE_CUTOVER_PLAN.md](AZURE_CUTOVER_PLAN.md).

## 1. How it was read

- `az … show` and `az … list` queries only. Names, counts and metadata were read; no secret value, no file on the share, no log line and no container shell.
- [`scripts/azure_config_check.py`](../scripts/azure_config_check.py) from a fresh clone of main, as [AZURE_MIGRATION.md](AZURE_MIGRATION.md) section 4, step 0 describes.
- One signed-out `GET` of the health path on each app. On the dev-like app this started a replica from zero for a few minutes.
- Not run: `scripts/host_check.py` (it writes a probe folder and takes test locks), any write to the share, any log query, the About page of either app, cost reports.

## 2. What exists

One resource group in one region, created on 4 Nov 2026 by an administrator account that is not the owner's, with a delete lock and no tags. No template deployment is recorded: the resources were made by individual commands. The dev-like app was added on 9 Nov. Nothing has been changed since 11 Nov.

| Role | Observed |
| --- | --- |
| Prod-like container app | One revision since 4 Nov, single-revision mode, always one replica (min 1, max 1), 0 restarts. 1 vCPU, 2 GiB. Port 8501, liveness and readiness probes on `/_stcore/health`. Data share mounted at `/test1`. The three required secret settings come from the vault through the managed identity; the eight fixed settings equal `render.yaml`. Built-in Microsoft sign-in is on and limited to one tenant. Runs an image built on 4 Nov. |
| Dev-like container app | 30 revisions between 9 and 11 Nov, single-revision mode, scale 0 to 1, no probes. Same size, same port. Mounts the **same share at the same path, read-write**; its data folder is a subfolder of the prod-like app's data folder. Its three secret settings come from secrets stored on the app, not from the vault. It also sets the global client-price switch described as item 4.4 in the [external patch provenance](EXTERNAL_MONTHLY_PATCH_PROVENANCE_2026-11-12.md); no code on main reads that setting. |
| Environment | Consumption only. Joined to a virtual network but **not internal**, so an app with external ingress is reachable from the internet. Application logs go to the log workspace. |
| Registry | Basic tier, no admin user, no anonymous pull, public network access. One repository with 31 tags: one production-style tag and 30 numbered development tags. Tags are not locked, so a tag can be overwritten or deleted. No retention or soft-delete policy. |
| Vault | Role-based access. Three secrets, one for each required secret setting. Soft delete 90 days; purge protection off; public network access; no resource logs. |
| Managed identity | One user-assigned identity used by both apps: registry pull and vault secret read. No federated credential, so nothing in GitHub can deploy here. |
| Storage | Premium file storage, locally redundant. One NFS share, 100 GiB provisioned, about 0.2 GiB used, root squash off as the guide requires. Network rules deny by default and allow the environment's subnet. Share soft delete 7 days. **No snapshots and no backup.** |
| Network | One virtual network with one subnet delegated to the environment. No security group, NAT gateway, peering or private endpoint. |
| Log workspace | 30-day retention, no daily cap. The resource group holds no alert rule and no action group. No resource logs from the vault, storage or registry. |
| Sign-in registration (prod-like) | Single tenant. Assignment is not required, so any account in the tenant can sign in. Its client secret is stored on the app and expires on 4 Nov 2027. |

The owner has Contributor on the resource group. Subscription owners and platform service principals inherit access from above; no names are recorded here.

## 3. The repository's own checker

| App | Result | Notes |
| --- | --- | --- |
| Prod-like | **0 failures, 0 warnings** | Every expectation in `render.yaml` and the migration guide is met. |
| Dev-like | 5 failures and 2 warnings as printed; **2 failures and 5 warnings in fact** | Three "secret … is a plain value" failures were false. Azure returned an empty `value` beside each `secretRef` for this app, and the checker treated the key's presence as a plain value. The checker is corrected in the change that adds this file. True failures: the data folder differs from `render.yaml`, and restricted finding R-1. Warnings: scale to zero, no probes, and three secrets kept on the app rather than in the vault. |

## 4. Answers to the open evidence requests

`ACA-01` to `ACA-08` are from section 2 of the readiness delta; follow-ons 13 to 16 are from section 7 of the reconciliation.

| Request | State | Finding |
| --- | --- | --- |
| ACA-01 revisions, traffic, replicas | **PASS** (read) | Both apps: single-revision mode, all traffic to the latest revision. Prod-like 1 to 1 replicas; dev-like 0 to 1. |
| ACA-02 image and digest per active revision | **PARTLY** | Both active tags resolve to digests, recorded in `AZ-RO-20261116`. Both apps reference a tag, not a digest. The source commit of the 4 Nov image is unknown: About was not opened, and the builds were made from an uploaded folder, not from GitHub. |
| ACA-03 ingress, probes, sign-in | **PASS** prod-like; **R-1** dev-like | Prod-like: external ingress, port 8501, http redirected to https, both probes, sign-in enforced; a signed-out request to the health path is refused with 401. |
| ACA-04 mounts and storage binding | **PASS** (read); isolation **FAIL** | One environment storage definition, one NFS share, read-write. Both apps mount it at the same path. File ownership and lock behaviour were not tested. |
| ACA-05 identity, vault references, registry pull | **PASS** (read) | One identity for both apps, with pull and secret-read only. Prod-like uses vault references; dev-like does not. |
| ACA-06 logging and alerts | **PARTLY** | The environment's log destination is the workspace. Actual ingestion was not queried. The resource group holds no alert rule and no action group. |
| ACA-07 backup and restore | **FAIL** | No snapshot, no backup resource, no restore ever run. Share soft delete protects only against deleting the share. |
| ACA-08 active writable hosts | **PARTLY** | Render serves main: its live deploy and the live acceptance are on `72923e4b` (17 Nov 00:29 and 00:55 UTC). The prod-like Azure app has a running, writable replica but received no requests from 12 to 15 Nov; the dev-like app received none from 13 to 15 Nov. Which store holds authoritative data is an owner statement, not something read here. |
| 13 image and source provenance | **PARTLY** | Every development image is the 4 Nov production-style image plus thin top layers: 2 layers on the first, 18 on the latest, under 1 MB in all. The external dev patch is therefore recoverable, byte for byte, from those layers by someone with registry read access. Layer contents were not extracted. |
| 14 durable-data isolation | **FAIL** | Same share, same mount path, read-write on both, and the dev-like data folder sits inside the prod-like one. |
| 15 access, network, revisions | **PASS** prod-like; **R-1** dev-like | As ACA-01 and ACA-03. The environment is not internal. |
| 16 traffic and data authority | **PARTLY** | As ACA-08. Request counts per day are in `AZ-RO-20261116`. |

## 5. Restricted findings

Detail is in `AZ-RO-20261116` only.

- **R-1, dev-like app.** One access-control setting needs the owner's or IT's action before that app is used again.
  **Closed on 17 Nov 2026 (task M1, #941):** the app had sign-in switched off and public ingress while holding real secrets and the data share. Its ingress is now off, its secret settings and the client-price switch are removed, its secrets deleted and its revision deactivated; a signed-out request to its old address answers 404.

## 6. Audit policies

Eleven audit-only policy results on the resource group are non-compliant; none blocks anything today. They are: registry images with unresolved vulnerabilities; registry network access not restricted; registry without private link; vault without purge protection; vault without a firewall; vault without private link; vault without resource logs; storage without secure transfer (NFS requires it off); storage allowing shared-key access; storage without private link; virtual network without DDoS protection.

## 7. What follows from this

These were decisions for the owner and IT on 16 Nov. On 17 Nov the owner took them as tasks M1 to M12 of [AZURE_CUTOVER_PLAN.md](AZURE_CUTOVER_PLAN.md); this list is kept as it was read.

1. **Close R-1.**
2. **Say what the two apps are for.** The prod-like app has run a 4 Nov build untouched while main has taken 226 merged pull requests; Render is what serves main. Keep, stop or retire each app deliberately, and record which store is authoritative.
3. **If the dev-like app stays:** give it its own share, take its secrets from the vault, add probes, and remove the client-price switch. Until then, treat anything it writes as sharing a disk with the prod-like app.
4. **Recover the external patch** for #877 from the registry's top layers in a restricted workspace: file list, SHA-256 of each file, then a comparison with main. This replaces "source unknown" with a reviewable manifest.
5. **Make builds traceable.** Build from a clone with `APP_GIT_COMMIT`, tag by commit and reference images by digest, as section 1 of the migration guide says. Lock tags that are in use.
6. **Backups.** Nothing on the share is backed up.
7. **Alerts and expiry.** Nothing alerts anyone. The sign-in client secret expires on 4 Nov 2027.
8. **Deploys stay manual.** No identity links GitHub to Azure, and the live acceptance cannot pass the Microsoft sign-in, as section 6 of the migration guide already notes.

## 8. What this does not show

Which commit either Azure app runs; whether the WebSocket works behind the sign-in; what is on the share; whether logs are arriving; whether any backup could be restored; cost; anything outside the one resource group. None of the three workflows was exercised on Azure.

## 9. Further detail (added 17 Nov)

Facts from the same two reads that the sections above summarise. Counts, dates and settings only; the names and identifiers are in `AZ-RO-20261116`.

**Requests per day** (the platform's request metric, both apps, UTC days):

| App | 4 Nov | 5 Nov | 6 Nov | 7 Nov | 8 Nov | 9 Nov | 10 Nov | 11 Nov | 12 Nov | 13–15 Nov |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prod-like | 352 | 543 | 3 | 0 | 376 | 193 | 51 | 6 | 0 | 0 |
| Dev-like | – | – | – | – | 571 | 351 | 690 | 8 | 7 | 0 |

The prod-like app had one replica every day. Nobody has used either app since 12 Nov; Render took every request in that time.

**Timeline** (activity log, 20 days, successful operations):

- 4 Nov, 20:24 to 21:36 UTC: an administrator account other than the owner's created everything in one evening by individual commands: the log workspace, network, storage and share, registry, vault, identity, five role assignments, the delete lock, the environment and its storage definition, the prod-like app, its sign-in configuration (three writes) and one registry build; the prod-like app's only replica started at 21:36.
- 6 Nov: one more role assignment by the same account.
- 9 Nov: the dev-like app was created, its sign-in configuration written three times, and about seven registry builds were run from an uploaded folder.
- 10 and 11 Nov: about nine and then more than a dozen further builds, the same way. The last development image is from 11 Nov 19:28 UTC; the dev-like app's last revision followed a minute later. On 11 Nov the owner's account only fetched sign-in tokens.
- 12 to 16 Nov: no changes.

**Prod-like app.** Revision created 4 Nov 21:15 UTC, never replaced; 0 restarts. 1 vCPU, 2 GiB memory, 4 GiB ephemeral storage. Liveness probe after 20 s, every 30 s; readiness after 10 s, every 10 s; both on the health path. Scale rule: none beyond min = max = 1. Ingress redirects http to https; no IP restrictions, custom domain, sticky sessions, CORS or client certificates. Its image is about 417 MB (amd64, 11 layers).

**Sign-in (prod-like).** Microsoft Entra as the only provider; signed-out requests are sent to the login page; no excluded paths; no token store; single tenant; ID tokens on; one redirect address. The registration's client secret is stored on the app, not in the vault, and expires on 4 Nov 2027. The enterprise application does not require assignment.

**Environment.** Public network access on, not zone redundant, peer-to-peer encryption off, Consumption profile only.

**Storage.** Secure transfer off (NFS needs it), minimum TLS 1.0, shared-key access allowed, Microsoft-managed encryption, trusted Azure services allowed through the firewall. About 166 MiB used on 16 Nov.

**Registry.** About 0.45 GB of the Basic tier's 10 GiB used. No tasks, webhooks, tokens or scope maps.

**Vault.** Its three secrets were created on 4 Nov and have no expiry dates. Two users can manage secrets: the owner and one other user.

**Log workspace.** Public ingestion and query on.

**Access.** On the resource group: Contributor for the owner and for one other user. Above it: four subscription owners, platform service principals, and two User Access Administrators at the root. Nobody else with write access was seen.

**Development images.** Each is the 4 Nov image plus thin layers; the number of extra layers grows from 2 on the first to 18 on the thirtieth. A tag can still be overwritten or deleted.
