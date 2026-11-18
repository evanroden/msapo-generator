# Finishing the move to Azure Container Apps

**Status, 17 Nov 2026 (evening):** M1, M2, M4, M5 and M6 are done. Following
the owner's decision (section 1), Azure runs current main with Render's data
and is open to the company tenant next to Render. Its AI calls Claude in
Microsoft Foundry on the company's subscription (section 1, Foundry row).
Azure will follow main by itself, as Render does, once IT has granted the
deploy identity (M12) and the owner has turned the deploy workflow on (M9);
until then it changes only with a release by hand.
Progress is tracked in [#941](https://github.com/evanroden/msapo-generator/issues/941).

This is the working plan for moving the app from Render to the Azure Container
Apps that already exist. It is written for the agents who will carry it out, one
task at a time, and for the owner who approves each task by handing it to an
agent. It relies on [AZURE_MIGRATION.md](AZURE_MIGRATION.md) (settings, the
one-replica rule, SQLite on NFS, `scripts/migrate_data.py`) and on
[AZURE_ASIS_OBSERVATIONS_2026-11-16.md](AZURE_ASIS_OBSERVATIONS_2026-11-16.md)
(what exists in Azure).

The repository is public until task M10. Real resource names, addresses,
identifiers and the restricted findings are therefore not written here. Commands
use the placeholders in section 5, and the owner holds the key to them.

## 1. Decisions of 17 November 2026

| Subject | Decision | What it replaces |
| --- | --- | --- |
| Hosting | Finish on the existing Container Apps. The prod-like app becomes production. The dev-like app is closed (M1) and later removed (M11, M12). | Azure App Service (Linux custom container), the target recorded in [azure/MIGRATION_MANIFEST.md](azure/MIGRATION_MANIFEST.md) section 2, and the open question in [azure/ACA_APP_SERVICE_RECONCILIATION_2026-11-12.md](azure/ACA_APP_SERVICE_RECONCILIATION_2026-11-12.md). |
| Code | Stays in this repository. It is made private once the move is accepted (M10). | "New ENFRA-private repository", proposed in the manifest. |
| Who changes Azure | Agents, each carrying out one task below from a prompt the owner gives them, with the owner's own Azure access. The prompt approves exactly the changes its task lists, nothing more. | Nothing: no one had been assigned. |
| Private details | Kept out of this repository while it is public. Agents get them from the owner: the Render service's environment variable `MIGRATION_PRIVATE_AZURE_KEY_JSON` (Render dashboard, service msapo-generator, Environment) and the owner's private prompt page. From M2 on, task records also go to a private storage container. After M10 the key moves into this repository. | Records "only in an approved restricted change record", which did not exist. |
| Data authority | Render is the only place where work is saved until the cutover (M7). Every Azure copy before then is a rehearsal and is closed to people (C1). | Not decided before. |
| Claude through the company's Azure (owner, 17 Nov) | The Azure copy does not use the owner's personal Claude API key: it calls Claude in Microsoft Foundry on the company's subscription (Opus, Azure-hosted, US data zone, billed on the company's Azure invoice). `app/ai_client.py` selects it from `ANTHROPIC_FOUNDRY_RESOURCE`; `ANTHROPIC_MODEL` names the deployment. Keyless sign-in needs IT to give the app's identity the Cognitive Services User role on the Foundry resource; until then the app uses the resource's key from Key Vault. Render keeps the Claude API. | The model key copied from Render into Key Vault. |
| Azure follows main (owner, evening of 17 Nov) | Azure deploys each commit on main once Tests has passed on that exact commit, as Render deploys each merge. `.github/workflows/azure-deploy.yml` runs `scripts/azure_release.py` as a deploy identity that only IT can grant (M12), and stays off until the owner turns it on (M9). Each deploy restarts the app, briefly runs the old and new revision side by side ([AZURE_MIGRATION.md](AZURE_MIGRATION.md) section 3), and is not preceded by a snapshot; the nightly backup covers the data. | M9 by hand for every release, in a quiet time, after a snapshot. |
| Both copies for now (owner, later on 17 Nov) | Render keeps running. Azure is brought up to main with a copy of Render's data, checked, and opened to the company tenant next to Render. Render stays the copy where work is saved until the owner announces the switch; the two copies do not sync, so anything saved on Azure before then is not on Render, and the switch (M7) copies Render's data over Azure's again. | M5 ending with Azure closed again, and M7 closing Render in the same window that opens Azure. |

Unchanged: everything in [AZURE_MIGRATION.md](AZURE_MIGRATION.md) still
applies; the open acceptance work in #270 (authentic reports, devices, PO and
Expense, per-site access) is not closed by this move; [azure/IDENTITY_SECRETS_AI_BOUNDARIES_2026-11-12.md](azure/IDENTITY_SECRETS_AI_BOUNDARIES_2026-11-12.md)
and [azure/CUTOVER_ACCEPTANCE_CHECKLIST.md](azure/CUTOVER_ACCEPTANCE_CHECKLIST.md)
still describe what "accepted" means. Where the 11 and 12 Nov documents in
`docs/azure/` assume App Service, a new ENFRA repository or an unnamed change
commander, this plan takes precedence.

Draft PR #940 compared four ways of closing R-1 (turn off the dev-like app's
ingress, restrict it by network, require sign-in with assignment, or stop its
revision). This plan takes the first, together with removing that app's secrets:
the dev-like app has no further job, because rehearsals run on the prod-like app
while it is closed to people.

## 2. Where things stand (17 Nov)

- **Render** serves main and is the only writer. Main's Tests and the live
  acceptance pass.
- **The prod-like app** runs a 4 Nov build, about 230 merged pull requests
  behind main. Sign-in is on and limited to the company tenant; the repository's
  checker reports 0 failures and 0 warnings. It has had no requests since
  12 Nov. Its share holds whatever people saved on it from 4 to 11 Nov.
- **The dev-like app** carries restricted finding R-1, mounts the same share
  read-write, and keeps its secrets on the app.
- **Missing:** backups and snapshots, alerts, blob storage for the transfer the
  guide describes (the existing storage account holds file shares only), and any
  identity that lets GitHub deploy.
- **The resource group has a delete lock** that the owner's role cannot remove.
  Nothing in it can be deleted without IT; new resources made by these tasks are
  therefore permanent unless IT removes them.

## 3. End state

- One production app: the prod-like Container App, single revision, one replica,
  running main's image built by commit and pinned by digest, settings from the
  vault, Microsoft sign-in limited to the company tenant, data share at `/test1`.
- Daily, checked backups of the whole data folder to separate storage, kept
  14 days; a share snapshot before every change; alerts to the owner.
- The dev-like app closed, then deleted by IT.
- Render closed with a notice that links to the new address, suspended after
  acceptance, then deleted. Until the owner announces the switch, both copies
  run (section 1).
- Releases deployed by a written procedure (M9) until IT grants a deploy
  identity (M12).
- This repository private, with CI sized for a private repository's minutes.

## 4. Order

| ID | Task | What it changes | Runs after |
| --- | --- | --- | --- |
| M1 | Close R-1 | The dev-like app only | now |
| M2 | Storage for transfers, backups and private records; first share snapshot | One new storage account; one snapshot | now |
| M3 | Recover the external patch from the registry (#877) | Nothing in Azure (reads the registry) | M2 |
| C1 | "Closed copy" switch in the app | Code, through a pull request | now |
| M4 | Build main by commit in the registry | One new, locked image tag | C1 merged, D1 |
| M5 | Rehearse the move on the prod-like app | That app's image, settings and data; closed to people throughout | M2, M4 |
| M6 | Daily backups, alerts and hygiene | A backup job, alerts, two settings | M2, M5 |
| M7 | Cutover | Render closed; Azure given Render's latest data | M5, M6, D2 |
| M8 | First week after cutover | Records only | M7 |
| M9 | Deploy a release: automatic after Tests once turned on, by hand until then | Production image and backup job image | M5; automatic once M12's deploy identity exists |
| M10 | Make the repository private | GitHub visibility; private key into the repository | M8, D6 |
| M11 | Retire Render, the dev-like app and old images | Render, registry tags, code, docs, branches | M3, M10, D5 |
| M12 | Requests for IT | Nothing: drafts requests for the owner to send | any time |

**Owner decisions**

- **D1 Address.** The prod-like app's own Azure address (default), or a company
  domain, which needs IT for DNS (M12). Decide before M4: the address is built
  into the image for link previews, and every browser starts fresh on a new
  address (unfinished browser-only drafts and remembered details).
- **D2 Window and announcement.** A quiet window of about an hour (M5 measures
  it) and the messages before and after; drafts in
  [azure/EMPLOYEE_COMMS.md](azure/EMPLOYEE_COMMS.md). The owner sends them.
- **D3 Model key.** Because of R-1, check the model provider's usage for 9 to
  16 Nov; rotate the key if anything is unexplained.
- **D4 Vault purge protection.** Recommended on. It cannot be turned off again.
- **D5 Retirement.** When to suspend and delete Render (suggested: two weeks
  after a cutover with no rollback); what happens to the folders the restores
  move aside.
- **D6 GitHub Actions minutes** once the repository is private (M10). The
  Azure deploy (M9) adds one image build per merge.

## 5. Placeholders

| Placeholder | Stands for |
| --- | --- |
| `<RG>`, `<REGION>` | The resource group and its region |
| `<ENV>`, `<ENV_ID>` | The Container Apps environment and its resource ID |
| `<PROD_APP>`, `<DEV_APP>` | The prod-like and dev-like container apps |
| `<REGISTRY>`, `<IMAGE_REPO>` | The registry (login server `<REGISTRY>.azurecr.io`) and the image repository in it |
| `<VAULT>` | The key vault |
| `<IDENTITY>` | The user-assigned identity both apps use (`<IDENTITY_ID>`: its resource ID) |
| `<DATA_ACCOUNT>`, `<DATA_SHARE>`, `<ENV_STORAGE>` | The premium storage account, its NFS share, and the environment's storage definition for that share |
| `<VNET>`, `<SUBNET>` | The virtual network and the environment's subnet |
| `<LOGS>` | The log workspace |
| `<BACKUP_ACCOUNT>` | The standard storage account M2 creates |
| `<BACKUP_JOB>` | The backup job M6 creates |
| `<PROD_ADDRESS>` | The address people will use (D1) |
| `<OWNER_EMAIL>` | The owner's work address for alerts, given by the owner |

Render's address is public already: `https://msapo-generator.onrender.com`.

## 6. Rules for every task

1. One task per session. Read the whole task first and do only what it lists.
   Anything else: stop and ask the owner.
2. Work in the owner's signed-in Azure session: the portal's Cloud Shell (Bash),
   or an `az` CLI the owner has signed in. Start with
   `az config set extension.use_dynamic_install=yes_without_prompt` (an
   extension prompt otherwise swallows the next command) and `az account show`;
   stop if the subscription is not the one in the key.
3. Cloud Shell here is ephemeral and closes after about 20 idle minutes. Clone the
   repository again in each session, keep commands short, and print compact
   results (`--query … -o tsv` or `-o table`).
4. Never create or change role assignments, locks, policies, app registrations,
   service principals or credentials; never delete anything the task does not
   list; never print or store a secret value, account key or SAS URL. A SAS goes
   only into the shell that uses it, read with `read -rs`. Secrets are compared
   by fingerprint only: the first 12 hex characters of a SHA-256.
5. Read before changing. If what you read differs from what the task expects,
   stop and report.
6. Take a share snapshot (M2, step 4) before any change that touches the data
   share.
7. Don't open an app's address signed out unless the task says so: a request
   can wake a scaled-to-zero app.
8. While Render is the writer, the Azure copy is either closed (C1) or reachable
   only from the operator's own address (an `operator-check` allow rule). It is
   never open to everyone while Render is still the copy people use.
9. Record every task twice: one public comment on #941 (what was done, each
   check and its result, what is left; no names, addresses, identifiers, digests
   or secret values), and the detail privately, in the session's final message
   to the owner and, from M2 on, as a file in the `records` container.
10. Render changes go through the Render dashboard or Render's tools. The
    dashboard's Shell tab runs commands in the live container.

## 7. Tasks

### M1. Close R-1

**Done on 17 Nov 2026, 16:52 to 16:56 UTC** (recorded on #941). R-1 was the
dev-like app answering without sign-in: its sign-in was configured but switched
off and its ingress was public, while it held the real model key, the expense
director map and the Smartsheet form address and mounted the data share. Its
ingress is now off; the three settings that read those secrets and the
client-price switch are removed; the three secrets are deleted from the app;
its only active revision is deactivated. A signed-out request to its old address
now answers 404 (200 before). The prod-like app was not touched. The app itself
can only be deleted by IT (M12); until then it cannot run or be reached.

### M2. Storage for transfers, backups and records; first snapshot

Why: the guide's transfer needs blob storage, backups need a second place, and
records need a private home while the repository is public. One standard account
serves all three; it is permanent (section 2).

1. Pick a name and check it: `az storage account check-name -n <BACKUP_ACCOUNT> --query nameAvailable`.
2. Create it, private by default:
   ```
   az storage account create -n <BACKUP_ACCOUNT> -g <RG> -l <REGION> \
     --kind StorageV2 --sku Standard_LRS --https-only true --min-tls-version TLS1_2 \
     --allow-blob-public-access false --tags app=msapo purpose=transfer-backup-records
   az storage container create --account-name <BACKUP_ACCOUNT> -n transfer --auth-mode key
   az storage container create --account-name <BACKUP_ACCOUNT> -n records --auth-mode key
   az storage share-rm create -g <RG> --storage-account <BACKUP_ACCOUNT> -n backups --quota 100 --enabled-protocols SMB
   ```
3. A safety net for forgotten transfers: a lifecycle rule that deletes blobs
   under `transfer/` a day after they were written
   (`az storage account management-policy create --account-name <BACKUP_ACCOUNT> -g <RG> --policy @policy.json`),
   with `policy.json`:
   ```
   {"rules": [{"enabled": true, "name": "transfer-after-1-day", "type": "Lifecycle",
     "definition": {"filters": {"blobTypes": ["blockBlob"], "prefixMatch": ["transfer/"]},
                    "actions": {"baseBlob": {"delete": {"daysAfterModificationGreaterThan": 1}}}}}]}
   ```
4. Snapshot the data share, so the 4 to 11 Nov Azure data is kept whatever
   happens next:
   ```
   az storage share-rm snapshot -g <RG> --storage-account <DATA_ACCOUNT> --name <DATA_SHARE>
   az storage share-rm list -g <RG> --storage-account <DATA_ACCOUNT> --include-snapshot \
     --query "[].{share:name, snapshot:snapshotTime}" -o table
   ```
   The delete lock also stops snapshots from being deleted; that is intended.
5. Check: the account shows https only, TLS 1.2, no public blob access; two
   containers, one share; one snapshot listed.

### M3. Recover the external patch (#877)

Reads the registry; changes nothing in Azure. Never runs the recovered code.

1. Get a pull token for the image repository without printing it, then each
   image's manifest: `az acr login -n <REGISTRY> --expose-token` gives a refresh
   token; exchange it at `https://<REGISTRY>.azurecr.io/oauth2/token` for a
   `repository:<IMAGE_REPO>:pull` token; request
   `/v2/<IMAGE_REPO>/manifests/<tag>` with both Docker v2 and OCI manifest
   `Accept` types.
2. Download the thin top layers of every development image (each is the 4 Nov
   image plus 2 to 18 layers under 1 MB) and the application-source layer of the
   4 Nov image. List every file with its size and SHA-256; note deletions
   (`.wh.` entries).
3. Find the commit the 4 Nov image was built from: compare `git hash-object` of
   its files with `git ls-tree` of main's history around 4 Nov.
4. For each file the patch layers change: base version, patched version, and
   whether main today has the same content, different content, or no such file.
5. Put the files, the manifest and the diff in `records/m3/`. Post on #877 only
   the manifest (paths, sizes, hashes, base commit, per-file comparison with
   main), not file contents. Porting anything is a separate decision.

### C1. "Closed copy" switch (code)

A setting, `MSAPO_SERVICE_MOVED_TO`, that closes one copy of the app and points
people to the other. It fences writes during the cutover and tells people where
to go afterwards.

- When it is set, every page (the main page and each file in `pages/`) shows a
  short notice, with a link when the value is an `https://` address, and stops
  before it reads or writes anything in the data folder or calls an outside
  service. Any non-empty value closes the copy; a value that is not an
  `https://` address shows the notice without a link.
- An optional `MSAPO_SERVICE_NOTICE` replaces the notice's sentence with plain
  text (for example "Moving to the new address; back by 7 pm"). It is shown as
  text, never as HTML or Markdown.
- When it is unset, nothing changes. The health endpoint is Streamlit's own and
  keeps answering.
- Tests: each entry script closed with a valid address, closed with a bad value,
  and open; nothing is created in a temporary data folder while closed; every
  file in `pages/` calls the switch, so a new page cannot skip it.
- The variable is added to the settings table in AZURE_MIGRATION.md.

### M4. Build main by commit

Adds one image tag; changes no app. Needs C1 merged and D1 decided.

```
git clone https://github.com/evanroden/msapo-generator.git && cd msapo-generator
git checkout <commit>      # main's head, with Tests green on that exact commit
az acr build -r <REGISTRY> -t <IMAGE_REPO>:$(git rev-parse --short=12 HEAD) --timeout 3600 \
  --build-arg APP_GIT_COMMIT=$(git rev-parse HEAD) \
  --build-arg PUBLIC_SITE_ORIGIN=https://<PROD_ADDRESS> .
az acr repository show -n <REGISTRY> --image <IMAGE_REPO>:<short sha> --query digest -o tsv
az acr repository update -n <REGISTRY> --image <IMAGE_REPO>:<short sha> --write-enabled false
```

The build log ends with the pushed digest; the image is used by digest
(`<REGISTRY>.azurecr.io/<IMAGE_REPO>@sha256:…`), never by a moving tag.

### M5. Rehearse the move on the prod-like app

Changes the prod-like app's image, settings and data. Render stays the only
writer, so the Azure copy is closed (C1) from the moment the new image runs,
and is opened only to the operator's own address for the browser checks.
Everything this task restores is replaced at the cutover.

1. Read the app's state (revision, image, replicas, ingress, sign-in, access
   restrictions) and the checker's result; snapshot the data share.
2. Deploy the new image **closed**, in one update, and wait until the new
   revision is healthy:
   ```
   az containerapp update -n <PROD_APP> -g <RG> --image <REGISTRY>.azurecr.io/<IMAGE_REPO>@<digest> \
     --set-env-vars MSAPO_SERVICE_MOVED_TO=https://msapo-generator.onrender.com
   az containerapp revision list -n <PROD_APP> -g <RG> -o table
   ```
   A signed-in browser now shows the notice that points to Render.
3. Inside the app (`az containerapp exec -n <PROD_APP> -g <RG> --command bash`,
   from `/app`): `python scripts/host_check.py`. No failures allowed. The switch
   closes the pages only; scripts run normally.
4. Compare the secret settings with Render's by fingerprint (both sides):
   ```
   python -c "import os,hashlib;[print(n, hashlib.sha256(os.environ.get(n,'').encode()).hexdigest()[:12] if os.environ.get(n) else 'unset') for n in ('ANTHROPIC_API_KEY','EXPENSE_ACCOUNT_DIRECTORS_JSON','SMARTSHEET_FORM_URL','SMARTSHEET_API_TOKEN','SMARTSHEET_SHEET_ID')]"
   ```
   If one differs, the owner copies Render's value into a new version of the
   vault secret; the agent never sees it.
5. Export on Render (dashboard Shell), after checking space with
   `du -sh /test1; df -h /tmp`:
   `python scripts/migrate_data.py export --source /test1 --output /tmp/msapo-data-rehearsal.tar.gz`.
   Note the SHA-256 and the time it took.
6. Transfer. In Cloud Shell make a write-only SAS for one blob, valid two hours:
   ```
   END=$(date -u -d "+2 hours" +%Y-%m-%dT%H:%MZ)
   az storage blob generate-sas --account-name <BACKUP_ACCOUNT> -c transfer -n msapo-data-rehearsal.tar.gz \
     --permissions cw --expiry "$END" --https-only --full-uri -o tsv
   ```
   In the Render shell:
   ```
   read -rs SAS && curl --fail -T /tmp/msapo-data-rehearsal.tar.gz \
     -H "x-ms-blob-type: BlockBlob" -H "x-ms-version: 2021-12-02" "$SAS" && rm /tmp/msapo-data-rehearsal.tar.gz
   ```
7. Restore inside the prod-like app, still closed, with a read-only SAS
   (`--permissions r`):
   ```
   cd /tmp && read -rs SAS && curl --fail -o msapo-data.tar.gz "$SAS"
   sha256sum msapo-data.tar.gz          # must match step 5
   python /app/scripts/migrate_data.py verify  --archive /tmp/msapo-data.tar.gz
   python /app/scripts/migrate_data.py restore --archive /tmp/msapo-data.tar.gz --target /test1 --replace-existing
   rm /tmp/msapo-data.tar.gz
   ```
   Whatever was on the share (the 4 to 11 Nov data and the dev-like app's
   folder) moves to `/test1/.pre-restore-<time>/`; nothing is deleted.
8. Open the copy **to the operator only**. Read the operator's public IPv4
   address in the browser that will do the checks (for example a "what is my
   IP" page), then:
   ```
   az containerapp ingress access-restriction set -n <PROD_APP> -g <RG> --rule-name operator-check \
     --ip-address <operator IPv4>/32 --action Allow --description "M5 browser checks"
   curl -s -o /dev/null -w '%{http_code}\n' https://<PROD_ADDRESS>/_stcore/health   # from Cloud Shell: refused
   az containerapp update -n <PROD_APP> -g <RG> --remove-env-vars MSAPO_SERVICE_MOVED_TO
   ```
   An allow rule refuses every other address ("RBAC: Access Denied"), so
   Cloud Shell's own request is refused. If the operator's browser is refused
   too, its traffic leaves from another address (a VPN or proxy): ask the owner
   rather than widening the rule. Removing the setting starts a new
   revision, which opens the restored databases. Wait until it is healthy, run
   `scripts/host_check.py` again, and in the signed-in browser check: About shows
   the commit; a saved Monthly report opens with its history; the contract and
   site directory lists the expected contracts; an expense form shows a director
   per account; the PO form builds its prefilled link (do not submit). Save
   nothing.
9. Close the copy again, then lift the restriction so that everyone sees the
   notice instead of an error:
   ```
   az containerapp update -n <PROD_APP> -g <RG> --set-env-vars MSAPO_SERVICE_MOVED_TO=https://msapo-generator.onrender.com
   az containerapp ingress access-restriction remove -n <PROD_APP> -g <RG> --rule-name operator-check
   ```
   Lift it only once the closed revision is healthy.
10. Clean up: delete the blob, then renew the account key that signed the SAS
    (`az storage account keys renew -g <RG> -n <BACKUP_ACCOUNT> --key key1 -o none`).
11. Record the export size and the time each step took: that sizes the window
    for D2.

**As run on 17 Nov.** C1 was still in review, so the `operator-check` rule
closed the copy from the first deploy instead of the switch. Following the
owner's decision (section 1, last row), step 9 is replaced: once the checks
pass, the rule is removed and the switch stays unset, so Azure is open to the
company tenant next to Render. Note the time of the restore: M7 needs it.

How the data moved that day, which M7 can repeat:

- The owner's network blocked Cloud Shell, so the Azure steps ran from an
  Azure CLI signed in with a device code.
- Render's web shell adds bracketed-paste markers to pasted text. The command
  typed into it therefore read the upload link with `read -rs` and extracted
  the token, so only the short link was pasted. The link was write-only for
  the `transfer` container and short-lived, and the storage key was rotated
  right after the upload.
- No read link was needed. A server-side copy put the archive into the backup
  share. One run of the backup job, with its arguments temporarily replaced by
  the restore script, checked the archive's SHA-256, then ran `verify` and
  `restore --replace-existing` into `/test1`. The job was then put back from
  its YAML.
- `az containerapp job start` with an override that changes only `--args`
  loses the job's command, and the container never starts. The `-c`
  argument cannot be passed on that command line either, so change the job,
  not the execution.
- An app update that changes settings starts a new revision, which opens the
  restored databases.

### M6. Daily backups, alerts and hygiene

1. Register the `backups` share with the environment, using the account's
   second key (the first is the one renewed after transfers):
   `az containerapp env storage set -g <RG> -n <ENV> --storage-name backups --access-mode ReadWrite --azure-file-account-name <BACKUP_ACCOUNT> --azure-file-share-name backups --azure-file-account-key "$(az storage account keys list -g <RG> -n <BACKUP_ACCOUNT> --query '[1].value' -o tsv)"`.
2. Create `<BACKUP_JOB>` with `az containerapp job create -n <BACKUP_JOB> -g <RG> --yaml job.yaml`.
   It runs daily at 08:15 UTC (job schedules are in UTC), uses the production
   image by digest and the shared identity, and mounts the data share at
   `/test1` and the `backups` share at `/backup`:
   ```yaml
   location: <REGION>
   identity:
     type: UserAssigned
     userAssignedIdentities:
       <IDENTITY_ID>: {}
   properties:
     environmentId: <ENV_ID>
     configuration:
       triggerType: Schedule
       replicaTimeout: 3600
       replicaRetryLimit: 0
       scheduleTriggerConfig:
         cronExpression: "15 8 * * *"
         parallelism: 1
         replicaCompletionCount: 1
       registries:
         - server: <REGISTRY>.azurecr.io
           identity: <IDENTITY_ID>
     template:
       containers:
         - name: backup
           image: <REGISTRY>.azurecr.io/<IMAGE_REPO>@<digest>
           command: ["/bin/bash", "-c"]
           args:
             - |
               set -euo pipefail
               out=/backup/msapo-$(date -u +%Y%m%dT%H%MZ).tar.gz
               python /app/scripts/migrate_data.py export --source /test1 --output "$out"
               python /app/scripts/migrate_data.py verify --archive "$out"
               find /backup -maxdepth 1 -name 'msapo-*.tar.gz*' -mtime +14 -delete
           resources: {cpu: 0.5, memory: 1Gi}
           env:
             - {name: EPC_DATA_DIR, value: /test1}
           volumeMounts:
             - {volumeName: data, mountPath: /test1}
             - {volumeName: backups, mountPath: /backup}
       volumes:
         - {name: data, storageType: NfsAzureFile, storageName: <ENV_STORAGE>}
         - {name: backups, storageType: AzureFile, storageName: backups}
   ```
   The export copies databases with SQLite's backup API, so it is consistent while
   the app runs. Start it once by hand (`az containerapp job start`), then check
   `az containerapp job execution list` and the archive and its `.sha256` in the
   share.
3. Alerts to `<OWNER_EMAIL>` through one action group: the production app
   restarted, has no replica, or answers with server errors; the backup job
   failed. (On 17 Nov the owner chose to leave alerts out for now.) List the
   metric names first
   (`az monitor metrics list-definitions --resource <id> --query "[].name.value" -o tsv`)
   rather than guessing them.
4. Hygiene: minimum TLS 1.2 on `<DATA_ACCOUNT>` (NFS is unaffected); lock image
   tags in use; vault purge protection if D4 says so. The sign-in client secret
   expires on 4 Nov 2027: the owner puts a reminder in the calendar.

### M7. Cutover

In the window from D2. The production image already runs on `<PROD_APP>`,
closed with `MSAPO_SERVICE_MOVED_TO` pointing at Render (M5 step 9, or M9 for a
newer release), with no access restriction left over.

While both copies run (section 1), Azure is open when this task starts. First
close it: `az containerapp update -n <PROD_APP> -g <RG> --set-env-vars MSAPO_SERVICE_MOVED_TO=https://msapo-generator.onrender.com`,
and wait until that revision is healthy. Then, inside it, list what changed
since the M5 restore:
`find /test1 -type f -newermt '<restore time>' -not -path '/test1/.pre-restore-*'`.
Databases change on their own when the app starts, but saved reports, uploads
or other new files mean people worked on Azure: show the list to the owner and
continue only when he says so. Step 4 moves Azure's data aside, so nothing is
deleted, but it is no longer what the app shows.

1. Turn off the live acceptance:
   `gh workflow disable "Monthly Isolated Live Acceptance" -R evanroden/msapo-generator`.
2. Close Render: set `MSAPO_SERVICE_MOVED_TO=https://<PROD_ADDRESS>` on the
   Render service and wait for that deploy to go live. From now on nothing can be
   saved anywhere.
3. Export on Render (dashboard Shell) as in M5 step 5, to
   `/tmp/msapo-data-final.tar.gz`; note the SHA-256 and the file count.
4. Snapshot the data share. Transfer and restore into the still-closed
   `<PROD_APP>` as in M5 steps 6 and 7, with `--replace-existing`. The restored
   file count must equal the exported one.
5. Open Azure **to the operator only**, exactly as M5 step 8: the
   `operator-check` allow rule first, then
   `az containerapp update -n <PROD_APP> -g <RG> --remove-env-vars MSAPO_SERVICE_MOVED_TO`.
   The new revision starts with the restored databases. Wait until it is
   healthy, run `scripts/host_check.py` inside it, and do the browser checks of
   M5 step 8, saving nothing.
6. Open Azure to everyone:
   `az containerapp ingress access-restriction remove -n <PROD_APP> -g <RG> --rule-name operator-check`.
   From now on people can save work on Azure.
7. Delete the blob and renew key1 as in M5 step 10.
8. The owner announces the new address.

**Going back.** Never reopen Render while Azure can still accept work, and never
reopen it without Azure's latest data unless Azure provably accepted none.

- **Before step 6** (only the operator's address could reach Azure, and the
  checks saved nothing): close Azure again
  (`--set-env-vars MSAPO_SERVICE_MOVED_TO=https://msapo-generator.onrender.com`),
  wait until that revision is healthy, then remove the `operator-check` rule,
  remove the setting from Render, and re-enable the live acceptance. Render's
  data has not changed since step 2, so nothing is lost.
- **From step 6 on** (anyone could have saved on Azure), in this order:
  1. Close Azure first: set `MSAPO_SERVICE_MOVED_TO` back to Render's address
     (and, if wanted, `MSAPO_SERVICE_NOTICE` with the expected time) and wait
     until that revision is healthy. Render stays closed.
  2. Export inside `<PROD_APP>`:
     `python /app/scripts/migrate_data.py export --source /test1 --output /tmp/msapo-data-back.tar.gz`.
  3. Transfer it the other way: a write SAS used from the Azure container, a read
     SAS used in Render's Shell; check the SHA-256 on both sides.
  4. Restore on Render with `--replace-existing`, then remove the setting from
     Render; its redeploy opens the restored databases.
  5. Leave Azure closed, pointing at Render, until the problem is understood.

### M8. First week after cutover

Daily for a week, reads only: revision health and restarts, error lines in the
console log (`az containerapp logs show -n <PROD_APP> -g <RG> --type console --tail 300`),
the backup job's last run and newest archive, the alerts. Then record on #941,
update AZURE_MIGRATION.md and the observations to say what now runs where, and
tick the items in #270 that the move settled (and only those).

### M9. Deploy a release

**Automatic, once turned on.** The "Deploy to Azure" workflow
(`.github/workflows/azure-deploy.yml`) runs after every Tests run on main and
calls `scripts/azure_release.py`, signed in as the deploy identity. When Tests
passed on main's head, it builds that commit (stamped for About, with
`PUBLIC_SITE_ORIGIN` set to the app's address), pushes it to the registry and
repository the app already runs from, tagged with the commit, and deploys it to
`<PROD_APP>` by digest under a revision named for the commit
(`c<first 12 hex>-<run>-<attempt>`). It waits until that revision serves;
otherwise it puts the previous image back and fails. Then it moves
`<BACKUP_JOB>` to the same image. A run for an older commit deploys nothing,
and a commit Azure already runs is skipped. Every name comes from the `azure`
environment's secrets and is masked in the public log. "Run workflow" deploys
main's head, or a given commit on main that passed Tests, also while automatic
runs are off.

Turning it on, after IT has created the deploy identity (M12):

1. Settings > Environments > New environment `azure`; deployment branches:
   `main` only.
2. Its secrets: `AZURE_CLIENT_ID` (the deploy identity's client ID),
   `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` (`<RG>`),
   `AZURE_APP` (`<PROD_APP>`), `AZURE_BACKUP_JOB` (`<BACKUP_JOB>`); and
   `AZURE_PUBLIC_ORIGIN` only if a company address replaces the app's own
   (D1). They are names and IDs, not passwords, but the repository is public.
3. Actions > Deploy to Azure > Run workflow. Check: the run is green, a revision
   named for main's head serves, About shows the commit, and the backup job
   has the same image. Record it on #941.
4. Settings > Secrets and variables > Actions > Variables:
   `AZURE_DEPLOY_ENABLED` = `true`. Any other value pauses automatic runs.

**By hand**, while the workflow is off or to repair a release:

1. The release commit is main's head with Tests green on that exact commit.
2. Build it as in M4.
3. Snapshot the data share.
4. In a quiet time (the requests metric for the last 30 minutes is zero or the
   owner says go), update `<PROD_APP>` to the new digest; wait until healthy; run
   `scripts/host_check.py`; check About shows the commit.
5. Update the backup job: `az containerapp job update -n <BACKUP_JOB> -g <RG> --image <REGISTRY>.azurecr.io/<IMAGE_REPO>@<digest>`.
6. Record the commit on #941 and the digest privately.

Going back: set `AZURE_DEPLOY_ENABLED` to `false` so the next merge does not
move Azure forward again, then run the workflow with the earlier commit (it
must be on main with Tests green), or update `<PROD_APP>` and the job to the
previous digest by hand. Database changes made by the newer release are not
undone by that; restore from a snapshot or the nightly archive only with the
owner's approval.

### M10. Make the repository private

1. D6: total last month's Actions minutes (`gh api` on the workflow runs) and
   compare them with what the owner's plan includes for private repositories.
   Decide between buying minutes and running less (for example the full test
   shards only on main, or nightly).
2. Note how many forks exist (`gh api repos/evanroden/msapo-generator/forks --jq length`):
   their copies stay public.
3. The owner changes visibility (Settings, General, Danger Zone), or approves
   `gh repo edit evanroden/msapo-generator --visibility private --accept-visibility-change-consequences`.
4. Only after `gh api repos/evanroden/msapo-generator --jq .private` prints
   `true`: add the private key (the Render variable's content) as
   `docs/azure/PRIVATE_ENVIRONMENT_KEY.md` through a pull request, and lift the
   "no real names" rule from this plan. Secret values still never go in.
5. From then on Cloud Shell clones need a token: the owner creates a read-only
   fine-grained token and enters it with `gh auth login` in Cloud Shell.

### M11. Retire Render, the dev-like app and old images

After D5.

1. Render: one last export kept in `records/`, then the owner suspends the
   service; later deletes it.
2. Registry: after M3's bundle is checked, delete the development tags; after two
   M9 releases, delete the 4 Nov tag (`az acr repository delete -n <REGISTRY> --image <IMAGE_REPO>:<tag> --yes`).
   If the lock refuses, leave them for IT.
3. The dev-like app: IT deletes it (M12).
4. Code, through one pull request: remove the two Render-only QA scripts (with
   their tests and workflow references), set the Dockerfile's default
   `PUBLIC_SITE_ORIGIN` to the new address, and turn the migration guide into an
   operations guide. Keep `render.yaml`: it is the settings contract that
   `scripts/azure_config_check.py`, `scripts/host_check.py` and several tests
   read, so it no longer deploys anything but still defines every setting.
   Renaming it to a host-neutral file is a separate change that moves every
   reader (`grep -rn render.yaml`) and its tests in one go. The live acceptance
   stays off until it can sign in.
5. Delete the 12 Azure branches listed on #270 once nothing on them is needed.
6. The `.pre-restore-*` folders on the share: delete only with the owner's
   approval and after a snapshot.

### M12. Requests for IT

Drafts for the owner to send; no agent sends anything.

- A deploy identity for GitHub Actions (M9), drafted for the owner on 17 Nov:
  a user-assigned managed identity in `<RG>` with a federated credential
  (issuer `https://token.actions.githubusercontent.com`, subject
  `repo:evanroden/msapo-generator:environment:azure`, audience
  `api://AzureADTokenExchange`) and these roles: AcrPush on `<REGISTRY>`;
  Contributor on `<PROD_APP>` and on `<BACKUP_JOB>`; on `<ENV>`, the join
  permission (`Microsoft.App/managedEnvironments/join/action`) that every app
  or job update needs, through Contributor or a custom role with only that;
  Reader on `<RG>`. Only an Owner can make the role assignments. IT sends back
  the identity's client ID.
- Keyless Foundry sign-in, drafted in the same request: Cognitive Services User
  on the Foundry resource for `<IDENTITY>`. The app then signs in with its
  identity and the Foundry key setting comes off the app.
- Delete the dev-like app, which needs the lock lifted.
- DNS for a company address, if D1 chose one.
- Optionally, require assignment on the sign-in enterprise application and
  assign a group, so that only named people can open the app.
- Cost visibility for the owner, and a view on the eleven audit-only policy
  results.

## 8. Not covered here

Per-site authorization inside the app, authentic-report acceptance (AUTH01 to
AUTH03), devices, Smartsheet's direct API and the other open items in #270.
Live acceptance behind the Microsoft sign-in needs a test identity or another
arrangement with IT, as section 6 of the migration guide says; until then
served-build checks after a deploy are manual.
