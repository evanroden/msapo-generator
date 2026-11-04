# Moving the app off Render (Azure Container Apps)

What the app needs from a new host, how to move its data safely, and what
changes for people and for QA. Written for the Render → Azure Container Apps
move; most of it applies to any container host. No secrets or real names
belong in this file: the repository is public.

## 1. Settings

Copy these from the Render dashboard (msapo-generator → Environment). Values
set in the dashboard win over `render.yaml`, so check the dashboard for
anything extra too.

| Kind | Name | Notes |
|---|---|---|
| Secret | `ANTHROPIC_API_KEY` | |
| Secret | `EXPENSE_ACCOUNT_DIRECTORS_JSON` | One JSON object keyed by account: `{"<account>": {"name": "...", "email": "..."}}`. Account names must match the app's; a bad entry shows a warning on the expense page. Holds real names and emails: never commit it. |
| Secret | `SMARTSHEET_FORM_URL` | |
| Secret | `SMARTSHEET_API_TOKEN`, `SMARTSHEET_SHEET_ID` | Only if set on Render. |
| Fixed | `PDF_BACKEND`, `ANTHROPIC_MODEL`, `SMARTSHEET_*` | Copy the values from `render.yaml`. |
| Fixed | `EPC_DATA_DIR=/test1` | Mount the data share at `/test1` so every path stays as it was. |
| Optional | `EPC_TIMEZONE` | Defaults to America/New_York. |
| Optional | `EPC_SQLITE_JOURNAL_MODE` | `wal` or `delete`; normally leave unset (see section 3). |
| Not needed | `GOTENBERG_URL`, `FONTCONFIG_FILE` | Other PDF engine only; already set in the image. |

Build arguments (no effect on Render, which supplies its own):

- `APP_GIT_COMMIT=$(git rev-parse HEAD)`: shows the served commit under
  About. Without it About says "build identifier unavailable", and served-build
  checks cannot confirm what is deployed.
- `PUBLIC_SITE_ORIGIN=https://<public address>`: the address used in link
  previews (Teams, Slack). A bare `https://host` only.

```
az acr build -r <registry> -t msapo-generator:$(git rev-parse --short HEAD) \
  --build-arg APP_GIT_COMMIT=$(git rev-parse HEAD) \
  --build-arg PUBLIC_SITE_ORIGIN=https://<public address> .
```

## 2. Container

- Port 8501. Health: `GET /_stcore/health` (use it for liveness and readiness).
- Runs as root (no `USER` in the Dockerfile). On an NFS share keep root squash
  **off** ("No Root Squash"), or the app cannot write its data.
- Streamlit holds each person's session in memory and uses a WebSocket at
  `/_stcore/stream`; check that it connects behind the sign-in during testing.
- Render runs the `starter` plan. LibreOffice conversion is the heaviest work;
  give the container at least as much CPU and memory as Render does.

## 3. Storage and the one-instance rule

The data folder holds plain files (`monthly_reports/`, learning data) and two
SQLite databases: `epc_memory.db` (learning and preferences) and
`smartsheet_submissions.db` (fail-closed Smartsheet idempotency state).

- **Run exactly one replica** (min = max = 1) in single-revision mode.
  `app/memory.py` states it: the app is single-instance only, and learning must
  move to a shared transactional database before it is ever scaled out.
- **Avoid overlapping revisions.** An update normally runs the new revision
  beside the old one for a short time. Deploy in a quiet window.
- **SQLite on a network share:** SQLite's WAL mode does not work over a network
  filesystem. The app now detects an NFS or SMB mount under the data folder and
  uses SQLite's rollback journal there, keeping WAL on a local disk such as
  Render's. `EPC_SQLITE_JOURNAL_MODE` overrides the detection.

## 4. Moving the data

`scripts/migrate_data.py` copies the whole data folder with a checksum
manifest. Databases are copied with SQLite's backup API (consistent even if
someone is using the app) as single self-contained files. Nothing is replaced
on the target until every file and database has been checked.

1. **Announce a quiet window.** Anything written on Render after the export is
   not moved. Ask people to save open Monthly drafts as report versions first
   (section 5).
2. **Export, in the Render shell:**
   ```
   python scripts/migrate_data.py export --source /test1 --output /tmp/msapo-data.tar.gz
   ```
   Note the printed SHA-256. `/tmp` needs room for the archive.
3. **Transfer** through a short-lived Azure Blob SAS URL (write-only to upload,
   read-only to download). Keep the URL out of shell history:
   ```
   read -rs SAS && curl --fail -T /tmp/msapo-data.tar.gz -H "x-ms-blob-type: BlockBlob" "$SAS"
   ```
   One upload handles up to about 5 GB; use azcopy for more.
4. **Restore, on Azure** (`az containerapp exec ... --command bash`), right after
   the first deployment and before anyone uses it:
   ```
   read -rs SAS && curl --fail -o /tmp/msapo-data.tar.gz "$SAS"
   sha256sum /tmp/msapo-data.tar.gz        # must match step 2
   python scripts/migrate_data.py verify  --archive /tmp/msapo-data.tar.gz
   python scripts/migrate_data.py restore --archive /tmp/msapo-data.tar.gz --target /test1
   ```
   If the fresh app already created files, the restore stops. Add
   `--replace-existing` to move them aside into `/test1/.pre-restore-<time>/`.
   Nothing is deleted.
5. **Restart the revision** so the app reopens the restored databases. Then
   delete the blob and the SAS.
6. **Spot-check:** a saved Monthly report opens with its history; the contract
   and site directory lists the expected contracts; an expense form shows the
   right director per account; About shows the deployed commit.
7. Keep Render **suspended, not deleted,** until the new host is accepted.
   Never let both write at once. Going back means pointing people at Render
   again; anything saved on Azure in the meantime would not be there.

## 5. What people notice

- A new address and a Microsoft sign-in.
- The app recognises each browser by a cookie, and cookies belong to one
  address. On the new address every browser starts fresh:
  - **unfinished Monthly drafts** that were only in the browser are not
    carried over. Save them as report versions before cutover;
  - remembered requester, vendor, expense-profile and employee-number details
    are learned again on first use.

  Saved report versions, history, the contract and site directory, designs
  and logos all move with the data.
- If a custom domain is planned, use it from the start; changing the address
  again later repeats this.

## 6. QA and process

- `monthly-live-qa.yml` reads the served address from the repository variable
  `MONTHLY_QA_PUBLIC_URL` (default: the Render address). Set it when cutting
  over.
- The live QA runs a browser from GitHub Actions. Behind the Microsoft sign-in
  it cannot reach the app unless a test identity or an exception is arranged.
  That is a decision for the owner and IT; until then served-build QA is manual.
- `qa_render_archive_redeploy_readonly.py` and
  `qa_shared_fixture_redeploy_readonly.py` check Render redeploys specifically
  and stay Render-only.
- `render.yaml` stays until Render is retired.
