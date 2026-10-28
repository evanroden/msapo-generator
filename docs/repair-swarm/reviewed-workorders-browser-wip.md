# Reviewed work-order browser checkpoint (2026-10-28)

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
