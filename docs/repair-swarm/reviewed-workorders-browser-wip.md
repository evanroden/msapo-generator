# Reviewed work-order browser checkpoint (2026-10-28)

## Recovery on 2026-10-28: local browser journey completed; hosted gates pending

The resumed harness now passes **Chromium and WebKit**, including actual CSV upload, explicit source facility/date review, status and multiline task corrections, both report inclusions, manager re-entry, snapshot save, narrow disk reload, idempotent re-inclusion, and real Word/PDF downloads. Saved/working state and original CSV bytes remain identical across reload. The downloaded Word contains both first/last work-order and maintenance rows, exact multiline task text, and totals **2 total / 2 completed / 0 open**, with one PM and one non-PM. The PDF contains each first/last ID twice (once per destination) and the complete task in its original word order.

Only the acceptance driver and this handoff/evidence changed. Product modules, native preflight, source originals, required hosted gates and parent #602 are unchanged. Keep the PR draft while hosted gates remain pending; this is local synthetic acceptance, not a production or genuine-client acceptance claim.

### Demonstrated blockers and corrections

1. Exact pinned overlay/date runtime still reproduced the old selector failure after narrow reload. The trace shows the first native keyboard opener targeting an offscreen control, followed by Playwright's option click scrolling the page and closing/detaching the popup before delivery. The driver now scrolls the control into view and awaits native settled state **before its first activation**. It retains ordinary keyboard opening and pointer option selection, with no force click, retry, input-state injection or fixed sleep.
2. The original visible-only count skipped the required source-details form when its expander was closed. The driver now requires the existing field even while collapsed, opens its native expander, chooses the source facility and enters/submits the source's September date. A canonical source receipt proves both values before row review begins.
3. Once both downloads completed, the exact task sentence was naturally line-wrapped in the PDF cell. The Word check retains its exact newline-sensitive task comparison; the PDF check folds extraction whitespace only, preserving the full task's word order. The Word status/PM count table is now also checked explicitly.
4. Server startup explicitly selects production frontend mode. New failure records include a traceback so a bare assertion cannot hide its failing boundary.

Original WIP failure summaries below are retained unchanged. Additional synthetic first-failure summaries and exact passing output hashes are in `reviewed-workorders-evidence/recovery-local-acceptance-20261028.json`, `patched-runtime-selector-first-failure.json`, and `pdf-wrap-first-failure.json`. Complete local traces, screenshots and downloaded documents were retained under `test-artifacts/` during recovery.

### Verification and environment boundary

- Both real browser journeys passed on the same final driver bytes, using an isolated copy of Streamlit 1.61.1 patched by this branch's pinned frontend/date publisher. Python 3.12.14 and Playwright 1.58.0; production mode; generation `9a5cd87d3c6cd8da82fc4039dd49eae005c4b2825e563d46570cdec92847f4f8`.
- Documentation-index checks: **58 passed**. Work-order lane integration: **6 passed**, no skips, with the supplied native LibreOffice runtime. An earlier run without the renderer PATH had two skips; those same output cases passed when rerun with the renderer configured.
- Local WebKit's system `ldconfig` inventory cannot see libraries supplied through scratch `LD_LIBRARY_PATH`. Actual `ctypes` loads of GLES/x264 and `ldd` checks for all 43 WebKit ELF files passed first. The local WebKit run used `PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1` solely for that inventory mismatch. No hosted dependency check was changed. The final hosted Chromium/WebKit job must still pass on its ordinary installed dependencies.
- The local renderer is bundled LibreOfficeDev 26.8. Hosted Ubuntu's renderer and Microsoft Word parity are not established by this run.
- #616 remains stacked on unchanged #602 `f9c822f9920dea76bdc14182133940a2e30bf55e`. Main was refreshed to `6e0ee1da43af2b70cc4f3d59dc266bd213e10026`; prospective-main integration must be reconciled and tested before release. No merge, auto-merge, deployment or production-data change was performed.

## Original checkpoint (preserved)

User cutoff checkpoint. This branch is a **WIP acceptance harness**, not a production repair or passed browser gate. Product implementation is safely published in PR #602 at `f9c822f9920dea76bdc14182133940a2e30bf55e`, tree `362e89c93cee262708e37c3c6bd408799d80ed01`; 172 focused tests passed with actual LibreOfficeDev 26.8 and no skips. Its seven hosted workflows are independently queued. The original #602 head is unchanged.

The three new executable files provide an isolated marker/cookie-gated source-manager host, a real Chromium/WebKit journey, and a dedicated hosted workflow. They use the actual source manager, native review forms, library snapshots and Word/PDF generator. No input values or report results are injected by the browser driver. Network guards forbid non-loopback requests; the only upload is the script's invented CSV. Synthetic first-failure summaries are committed beside this note; full local traces/screenshots remain in `test-artifacts/reviewed-work-orders*`.

## Exact current evidence and limits

- Latest Chromium run completed actual CSV upload, source-site form selection, work-order status correction, explicit Activity inclusion, maintenance multiline task/status correction, explicit Maintenance inclusion, source-manager close/re-entry, snapshot save, and narrow reload with identical saved/working receipt.
- It then failed on the first attempt to select the maintenance destination after reload: `Completed in-house maintenance calls` option did not become available. `passed` remains false. No Word/PDF download or WebKit pass is claimed for this harness.
- Local runtime was stock Streamlit; coordinator identified that it lacks the repository overlay compatibility publication. Repeat only in an **isolated copied runtime with this branch's pinned frontend and date patches applied**, `development_mode=false`; coordinate with source_durability. Do not change the shared runtime or reinterpret prior failures as passes.
- Earlier failures include fixture setup omissions (managed-source flag, post-commit refresh), an observer receipt schema mistake, and a native action attempted before its preceding form result settled. Those fixture mistakes are corrected; their first failures remain retained. Settling now checks canonical receipt plus native `notRunning`, without retrying failed activations.
- Source date is currently left unknown by this scenario. If final generation blocks, complete the existing source date form with the actual synthetic September date using native controls; do not bypass preflight or directly set the source.
- GitHub main advanced to `26878e84af3525dce7eef9209e456e83c4f64162` during this work. This WIP preserves the tested #602 parent tree; reconcile main before release and rerun the exact integrated gates.

## Resume

1. Read this note and the committed first-failure JSON. Inspect the script/fixture and the exact new PR head.
2. Configure an isolated patched runtime and LibreOffice, then run `python scripts/qa_reviewed_work_orders.py` (both engines by default). `REVIEWED_ROW_BROWSERS=chromium` is a labeled diagnostic subset only.
3. Retain each first failure; investigate without rescue clicks, force clicks, input-state injection or fixed sleep-based readiness. Current harness uses keyboard dropdown opening and native option pointer selection.
4. Verify exact downloaded first/last work-order and maintenance rows, status totals, multiline task text and immutable source bytes; require both Chromium/WebKit results and hosted workflow success.
5. Seek independent review before treating this WIP as complete. No production deployment, genuine-source/native-master acceptance or Microsoft Word parity has been performed.

Local command used:

```sh
PATH=/opt/codex/runtimes/codex-primary-runtime/dependencies/native/libreoffice-headless/libreoffice/program:$PATH REVIEWED_ROW_BROWSERS=chromium /workspace/scratch/3180f12c2b4a/venv/bin/python scripts/qa_reviewed_work_orders.py
```
