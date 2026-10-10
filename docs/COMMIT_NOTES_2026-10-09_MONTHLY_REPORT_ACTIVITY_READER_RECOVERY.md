---
document_type: implementation_checkpoint
date: 2026-10-09
workflow: monthly_report
change_type: defect_fix
base_commit: 309eae5b0189d2aa6bb7f6ec873b4579efa6016e
status: candidate_pending_ci
---

# Activity source upload: native text first, safe automatic reading second

## Verified user problem

The October 9 hands-on audit recorded `activity.txt` failing twice with
`Expecting value: line 1 column 1 (char 0)` and yielding no usable draft.
The reviewer manually reentered the facts; that workaround is not an upload
success. The source is included as a synthetic, self-contained reproduction
fixture in the audit. This change does not require a private live customer file.

On the immediately preceding main tree, `request_json()` threw a raw
`JSONDecodeError` for fenced text, chatter, or malformed results. The
upload-first UI also called `st.rerun()` from an inline job-progress fragment
before its parent could commit native text; an instantly completed cached
future or failed future could mark the source processed while discarding its
first-pass text. This was reproduced with a real Streamlit `AppTest`, not by
copying isolated helper implementations. With no model key, automatic reading
was still launched rather than treating native text as the useful fallback.

## Fix and compatibility

- The existing shared JSON-object extractor accepts a single fenced object or
  an object followed by explanatory text. Empty/incomplete/malformed answers
  produce an actionable ValueError, not raw JSON diagnostics. Incomplete model
  output still fails closed; no fabricated facts are accepted.
- Native first-pass text and source identity are committed to the working
  report session **before** marking the upload processed or launching its
  optional model reader. The completion path handles an already-finished job
  in the same normal run, avoiding an early rerun and false edit-conflict alert.
- An unconfigured model reader does not start a network job, decode images,
  reserve a request allowance, or offer a futile Retry. Native source text can
  be edited immediately. A short neutral explanation distinguishes this from
  a damaged upload.
- Only fully validated, applied reader results enter the reusable model cache;
  an invalid answer cannot permanently poison the source digest. Explicit
  Retry bypasses the failed cached response once. Existing manually edited
  blocks are protected through their fingerprint comparison; suggestions
  remain reviewable when human edits arrived during reading.
- Unexpected worker errors are logged internally while the user sees a
  nontechnical retry/edit message. Original source bytes, saved snapshots,
  authentication/attribution semantics, picture approvals, pricing gate,
  evidence quotes, versioned design pins and the conversion lock are unchanged.
- The `section-upload` reader digest is versioned to `v3`, so malformed old
  caches are not silently promoted as successful current readings.

## Tests and limits

New synthetic tests include fenced/trailing/non-JSON/empty model messages;
actual AppTest uploads with an unset model key; a cached Future already done;
an immediately failed Future; valid model text deduplication against native
extractive text; and malformed cached suggestions followed by an explicit
cache-bypassing retry. Each checks current draft text and the displayed
messages, not just exception classes. No paid model calls are made by tests.

The final exact-head full-suite, production renderer, Docker health and capped
resource results belong in the PR and its CI run. Green local application
simulations do not establish success of a real remote AI request. This fix does
not implement advanced source classification, work-order CSV derivation,
per-item AI recovery, or the owner-requested **autosave across a 502 reconnect**;
those remain separate defects. The final report must still be reviewed for
accuracy, pricing and status. Real browser upload/download acceptance and an
authentic authored-PDF comparison remain open.

Rollback is code-only; do not delete saved uploads, reports, standing contacts,
capacity data, stored originals, versioned profile state or reader histories.
