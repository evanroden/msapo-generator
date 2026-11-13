# MSAPO full-container portability contract — preparation only

**Scope:** Current three-workflow `run_web.py` product only. No Azure resource, Render setting, secret, live data, DNS, routing, provider, storage, repository ownership, or release workflow is changed by this contract. Source ledger: #270; independent adapter PR #868; App Service IaC PR #859. This is a build/test contract, **not** platform or release acceptance.

## Baseline and image invariants

- **One application:** `run_web.py` → `app.web_ui.main` → Purchase Order/Smartsheet, Expense Reimbursement, and Monthly Report. The root workflow selector and existing manual/approved source routes remain intact. Do not substitute a monthly-only image or hide either other workflow.
- **Renderer:** `ubuntu:24.04`, Python 3.12 venv, `requirements.lock`, LibreOffice **Writer and Calc 24.2**, native libraries, verified font substitutions, both expense-signature fonts, Streamlit and frontend/date patches, bundled master/expense templates, and `runtime/check_renderer.py` must survive unchanged. Build fails if renderer version/font matches drift. All current report and financial provenance/safety rules remain in their application modules. No new AI provider is activated.
- **Default Render behavior:** Dockerfile runs `streamlit run run_web.py --server.address=0.0.0.0 --server.port=8501 ...` and retains its single `/app` working directory. `.streamlit/config.toml` keeps CORS and XSRF protections. Render `render.yaml` selects Docker runtime and `/test1` for persistent data. The dashboard's effective settings and the actual mounted state are **not** proved by the source file.
- **Optional host-neutral process launch:** `python scripts/container_portability.py serve` is an **explicit command override**, not the default command. `EPC_PORT` (1–65535) and `EPC_HOST` (`0.0.0.0` by default) are interpreted only by this launcher, and `EPC_PORT` is also used by the new local health probe. An unqualified `PORT` is intentionally **not** auto-selected: check the specific platform's ingress setting. For nondefault port deployments, configure the launcher **and** the matching platform target port. Do not interpret an ingress `Host` or proxy header as a bind address. `os.execvp` replaces PID 1 so Streamlit receives termination signals. Startup preflight checks the current `/app/output`, temp directory and any explicitly configured `EPC_DATA_DIR` with disposable files; a missing declared mount fails closed without creating it.
- **Image identity:** Build with `APP_GIT_COMMIT=<full reviewed 40-character SHA>` and approved `PUBLIC_SITE_ORIGIN=<https origin>`. OCI revision/source labels plus `APP_GIT_COMMIT` identify the source without secrets. Production Render builds may omit the argument and retain the existing `RENDER_GIT_COMMIT` runtime fallback; **do not claim** an unstamped OCI label identifies an exact revision. The build context must come from exactly that commit and have no uncommitted edits; no floating `latest` tag and no tag reuse. A local Docker image **ID** is not the same as the OCI **manifest digest** in the registry.

## Readiness, liveness, shutdown and files

| Surface | Contract | Boundary / unknown |
|---|---|---|
| Readiness | local HTTP `127.0.0.1:<effective-port>/_stcore/health` must return `200 ok`; Docker HEALTHCHECK probes it. | Streamlit HTTP readiness does **not** prove storage safety, external API access, user authorization, migrations or output correctness. An edge sign-in/proxy may produce different external results. |
| Liveness | PID 1 / process lifetime, restart on exit; `serve` uses `execvp`, not a shell parent. | ACA and App Service probe wiring and termination deadlines must be validated on the target; no assumption that Docker HEALTHCHECK config is adopted as a platform liveness probe. |
| Startup | Docker build checks native renderer and bundled synthetic fixture; `serve` checks only disposable writable paths. | Actual host must run `python scripts/host_check.py --offline` to prove owner-only permissions, `flock`/`lockf`, SQLite transaction mode and database checks. This is a separate **data safety** gate; no network/AI calls when `--offline`. |
| Shutdown/restart | `SIGTERM` reaches Streamlit; preserve the existing application save/restore semantics. Stop with a finite drain timeout then restart and inspect state. | Graceful in-flight conversions and the exact platform grace period are **unverified** until nonproduction testing. No concurrent writers/slots/revisions against the same SQLite store. |
| Immutable source | `/app` code, `runtime/`, templates, fontconfig and built front-end assets are packaged by image. | The **current** app writes `/app/output` and may create caches; the current image is **not** verified with `readOnlyRootFilesystem`. Do not mark `/app` immutable at runtime without a separately qualified output-path change (also proposed in PR #868). |
| Durable writes | `EPC_DATA_DIR=/test1` is the Render-source default; preserve histories, originals, standing data, idempotency and site/contract boundaries. | Mount destination, permissions, persistence and whether ACA prod/dev share subpaths must be proved privately. Never auto-create a missing configured mount or replace stores with tmp storage. |
| Scratch/output | Current `/app/output`; system `tempfile` and LibreOffice user-profile scratch; synthetic smoke cleans its own `TemporaryDirectory`. | `/app/output` is currently container writable and may be ephemeral. No arbitrary global tmp cleanup or deletion of retained originals is authorized. Bound temp/disk use, orphan cleanup and mount capacity need on-host measurement. |
| CPU/memory/disk | One initial worker; cap uploads at the current Streamlit 512 MiB setting, noting smaller importer-specific limits. Record CPU/RSS, peak scratch, cold start, 512 MiB upload and long DOCX/PDF timings before assigning limits. | A 2 vCPU / 8 GiB instance is only a **benchmark candidate**, not an approved resource entitlement. A 512 MiB request is not evidence that ingress accepts it. Do not increase replicas until storage concurrency is qualified. |

## Read-only, synthetic qualification

Use a trusted, disposable, authorized development builder that has Docker/Buildx. No production image/tag, public artifact, private customer file, secret, cloud credential, AI API or Smartsheet row is required for these commands. Shell substitutions below are examples; replace placeholders locally, never commit restricted origin/registry values.

```bash
set -eu
SHA="$(git rev-parse HEAD)"
test "$(git status --porcelain | wc -l | tr -d ' ')" = 0
printf '%s' "$SHA" | grep -Eq '^[0-9a-f]{40}$'
python -m pytest -q tests/test_container_portability.py tests/test_expense_deployment.py
# Use a locally authorized HTTPS site origin; the origin does not imply deployment.
docker build --pull --build-arg APP_GIT_COMMIT="$SHA" \
  --build-arg PUBLIC_SITE_ORIGIN="https://example.invalid" \
  --tag "msapo-local:${SHA}" --iidfile image-id.txt .
docker image inspect "msapo-local:${SHA}" \
  --format '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
docker run --rm --network none --entrypoint python "msapo-local:${SHA}" \
  scripts/container_smoke.py
# Use a new throwaway instance with no persistent production mounts.
docker run -d --name msapo-portability-check \
  -p 127.0.0.1:18501:8501 "msapo-local:${SHA}"
# Wait for Docker Health.Status=healthy; record the exact status and timing.
docker inspect --format '{{.State.Health.Status}}' msapo-portability-check
curl --fail --silent http://127.0.0.1:18501/_stcore/health
docker stop --time 30 msapo-portability-check
docker start msapo-portability-check
docker inspect --format '{{.State.Health.Status}}' msapo-portability-check
docker rm -f msapo-portability-check
```

The smoke script imports the **three actual UI modules**, verifies all three callable entrypoints and an exactly pinned Python lock, records OS architecture, Python, LO and font basenames, and creates a **synthetic DOCX and synthetic expense workbook** that Writer/Calc convert to PDF. It verifies both PDF text markers and page counts without preserving a report. This proves only startup/import and conversion plumbing, **not** the complete PO submission, a true expense signature workbook, or a native complete Monthly report. Run existing focused real-app synthetic tests and the full required exact-head suite; do not skip, weaken or delete regressions. Only already-authorized private test settings may be used for genuine-file acceptance, with sanitized summaries.

For local-vs-platform parity, run this *same* smoke script in both copies of the **same digest**, compare architecture/Python/LO/fonts, the lock SHA-256, imported workflows, and synthetic extracted marker + PDF page counts. Byte-for-byte PDF equality is not required: PDF metadata/time can differ. Verify full actual Word/PDF/Expense output independently using approved synthetic fixtures. The Render-served commit/health, any Azure served digest, and on-host actual mounts are separate observations, not inferred from a successful build.

## Publication and digest (only after a separate authorized nonproduction release)

An OCI registry's SHA-256 **manifest digest** becomes available after publishing to an **authorized nonproduction** registry under a new immutable tag, for example by `docker buildx build --push --metadata-file build-metadata.json ...`; read `containerimage.digest` from the returned metadata and match the registry artifact to the SHA/labels. **Never overwrite** current live tags or reuse production/dev revisions. Do not start a deployment workflow or enable auto-deploy. Without authorized registry access, report `registry digest: NOT PRODUCED`; a local `sha256:` image configuration ID is not a substitute. Platform verification requires that exact registry digest pulled and served in a distinct authorized nonproduction instance.

## Current Container Apps vs proposed App Service

**As-is ACA (user-provided snapshot, not independently authenticated):** two Container Apps reportedly share an environment, registry, identity and a named volume family. A shared volume name does **not** determine whether mounts use identical shares/subpaths. Before *any* dev test, independently inspect revision mode/traffic, actual targetPort, ingress/TLS, authenticated health access, app-level identity and secret references, replica counts, mount-to-share/subpath mapping, write permissions, volume locking, and network egress in a restricted read-only inventory. Do not run this smoke against ACA dev until its data isolation from production is proven. App Service slot/Easy Auth assumptions do not apply to ACA. No Azure execution is authorized here.

**To-be App Service (merged #849 architecture; draft #859 implementation, not provisioned here):** Linux custom container, currently designed for explicit `WEBSITES_PORT=8501`, external Entra auth, WebSockets and `/_stcore/health`. Verify the actual custom storage mount at the app's expected path, permissions, SQLite/locking safety and any alternative approved managed state. An App Service slot is not an ACA revision. No provisioning, slots, identity/secret changes, cutover, or deployment are included.

**Render:** the existing Dockerfile/CMD/port and `render.yaml` remain supported. Its effective dashboard env, persistent disk mount and current served source/digest require independent observations; a local image build never proves live Render parity.

**Open gates:** exact-head CI and combined-tree qualification; Docker/Buildx image test on an authorized Linux builder; full synthetic app workflow acceptance; observed image registry digest; actual nonproduction platform resource/mount/health/restart/termination tests; production data migration/storage design; platform architecture decision and explicit P20/ENFRA release approval. Keep focused acceptance issues open until their own served criteria pass.

