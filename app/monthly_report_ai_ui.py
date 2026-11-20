"""Optional reading/drafting controls, with explicit comparison before applying."""

from dataclasses import asdict, replace
import hashlib
import json

import streamlit as st

from app import monthly_report_ai as ai, monthly_report_ai_items as items, monthly_report_library as library
from app import monthly_report_ai_coverage as coverage
from app.monthly_report_model import BlockSpec, EvidenceFact, ReportSource, ResolvedBlock
from app.monthly_report_prompts import copilot_prompt, parse_copilot
from app.monthly_report_sources import SourceContent
from app.receipt_jobs import start_receipt


LABELS = {
    "activity_summary": "Work done this month",
    "improvements": "Improvement titles and captions",
    "equipment_issues": "Equipment issues",
    "training_summary": "Training summary",
    "work_orders": "Work-order narrative",
    "proposals": "Proposals and follow-ups",
}


def copy_prompt(prompt):
    # Same clipboard fallback and JSON escaping used by the existing handoff
    # component. Source text is data, never interpolated executable markup.
    payload = json.dumps(prompt).replace("<", "\\u003c")
    st.iframe(
        """<button id="copy" style="padding:12px;background:#D6EF4B;border:1px solid #092B24;border-radius:6px">Copy Copilot prompt</button>
<span id="status" role="status"></span><script>
const text=PAYLOAD;document.getElementById('copy').onclick=async()=>{
let ok=false;try{await navigator.clipboard.writeText(text);ok=true}catch(_){}
if(!ok){let t=document.createElement('textarea');t.value=text;t.contentEditable='true';t.readOnly=false;t.style.cssText='position:fixed;opacity:0;width:1px;height:1px';document.body.appendChild(t);t.focus();t.setSelectionRange(0,text.length);try{ok=document.execCommand('copy')}catch(_){}t.remove()}
document.getElementById('status').textContent=ok?' Copied':' Copy failed. Select the prompt below.';};</script>""".replace(
            "PAYLOAD", payload
        ),
        height=60,
    )


def copilot_source(text, profile, period):
    lines, unmatched = parse_copilot(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    identity = "copilot-" + digest[:20]
    source = ReportSource(
        identity,
        "Pasted Copilot notes.txt",
        digest,
        ".txt",
        page_texts=tuple(l.text + " [" + l.source + "]" for l in lines),
    )
    kinds = {
        1: "action",
        2: "finding",
        3: "issue",
        4: "proposal",
        5: "finding",
        6: "training",
        7: "improvement",
        8: "follow_up",
    }
    facts = []
    for n, line in enumerate(lines, 1):
        if ai.contains_price(line.text):
            continue  # Original pasted notes remain available; report the count.
        flags = ["Pasted Copilot summary: verify the cited original"]
        if line.source == "Source not supplied":
            flags.append("Source not supplied")
        facts.append(
            EvidenceFact(
                "fact-" + ai.digest((identity, n))[:20],
                identity,
                n,
                kinds[line.section],
                ai.clean_text(line.text),
                ai.clean_text(line.text),
                flags=tuple(flags),
            )
        )
    return replace(source, facts=tuple(facts)), unmatched, len(lines) - len(facts)


@st.fragment(run_every=1)
def _reading_progress(prefix):
    # Only mounted while a job exists; completion advances the page queue
    # without requiring another click. The UI thread remains the sole writer.
    job = st.session_state.get(prefix + "_ai_job")
    if job is not None and job["future"].done():
        st.rerun()


def _page_scope(draft):
    return (draft.profile.contract, draft.profile.key, draft.period.key,
            st.session_state.get("_monthly_qa_generation", ""))


def _merge_page_facts(prefix, source, facts):
    """Keep older proposals and human-accepted facts; never replace by ID."""
    key = prefix + "_ai_facts"
    proposed = st.session_state.get(key)
    merged = {}
    if proposed and proposed[:2] == (source.id, source.fingerprint):
        merged = {fact.id: fact for fact in proposed[2]}
    for fact in facts:
        merged.setdefault(fact.id, fact)
    st.session_state[key] = (source.id, source.fingerprint, tuple(merged.values()))


def _queue_page_reads(draft, prefix, source, pages, *, failed_only=False):
    """Resolve cached successful siblings without another model request."""
    if prefix + "_ai_job" in st.session_state:
        return
    waiting = []
    for page in dict.fromkeys(pages):
        try:
            key, _ = ai.extraction_request(source, (page,))
            saved = ai.cached(draft.profile, "extraction", key)
            if saved is not None:
                facts = ai.normalize_facts(saved, source, (page,), draft.profile,
                                           draft.period, ai.vendor_names(draft))
                _merge_page_facts(prefix, source, facts)
            elif not failed_only or items.status(draft.profile, draft.period, key) == "failed":
                waiting.append(page)
        except ValueError as exc:
            # One empty/invalid source page cannot prevent independent pages
            # from being read. Report the exact skipped page to the operator.
            st.warning(f"Page {page}: {exc}")
    st.session_state[prefix + "_ai_page_batch"] = {
        "scope": _page_scope(draft), "source_id": source.id,
        "source_fingerprint": source.fingerprint, "waiting": waiting,
    }
    _advance_page_reads(draft, prefix)


def _advance_page_reads(draft, prefix):
    """Start at most one pending page; a completed sibling is never resubmitted."""
    batch_key = prefix + "_ai_page_batch"
    batch = st.session_state.get(batch_key)
    if not batch or prefix + "_ai_job" in st.session_state:
        return
    contents = st.session_state.get(prefix + "_evidence", ())
    current = next((c.source for c in contents
                    if c.source.id == batch["source_id"]), None)
    if (batch["scope"] != _page_scope(draft) or not current
            or current.fingerprint != batch["source_fingerprint"]):
        st.session_state.pop(batch_key, None)
        return
    while batch["waiting"]:
        page = batch["waiting"][0]
        try:
            key, content = ai.extraction_request(current, (page,))
            saved = ai.cached(draft.profile, "extraction", key)
            if saved is not None:
                facts = ai.normalize_facts(saved, current, (page,), draft.profile,
                                           draft.period, ai.vendor_names(draft))
                _merge_page_facts(prefix, current, facts)
                batch["waiting"].pop(0)
                continue
            job = {
                "kind": "extraction", "page_job": True, "key": key,
                "source_id": current.id, "source_fingerprint": current.fingerprint,
                "pages": (page,), "scope": batch["scope"],
                "profile": draft.profile, "period": draft.period,
            }

            def prepare():
                state, token = items.claim(draft.profile, draft.period, key)
                if state != "claimed":
                    raise ValueError(
                        "This page is already cached or being read in another session. "
                        "Recheck its results before requesting it again."
                    )
                job["token"] = token
                return content

            if items.status(draft.profile, draft.period, key) == "pending":
                # Another session owns this page. Do not hold its siblings
                # hostage or submit the same paid work twice.
                batch["waiting"].pop(0)
                continue
            batch["waiting"].pop(0)  # Never auto-retry a failed page.
            started = _start(prefix, draft, job, prepare)
            if not started:
                latest = items.status(draft.profile, draft.period, key)
                if latest == "pending":
                    continue  # The other session won the claim race.
                if latest == "accepted":
                    saved = ai.cached(draft.profile, "extraction", key)
                    if saved is not None:
                        facts = ai.normalize_facts(saved, current, (page,),
                                                   draft.profile, draft.period,
                                                   ai.vendor_names(draft))
                        _merge_page_facts(prefix, current, facts)
                    continue
                batch["waiting"].insert(0, page)  # Capacity was full.
                return
            return
        except ValueError as exc:
            # Invalid content is local to its page. Other pages remain queued.
            st.warning(str(exc))
            batch["waiting"].pop(0)
    st.session_state.pop(batch_key, None)


def _finish_job(draft, prefix):
    key = prefix + "_ai_job"
    job = st.session_state.get(key)
    if not job:
        return
    if not job["future"].done():
        st.info(
            "Reading evidence… You can keep editing. Your existing report stays intact."
        )
        st.button("Check reading progress", key=prefix + "_ai_check")
        return
    try:
        result = job["future"].result()
        contents = st.session_state.get(prefix + "_evidence", ())
        current = next(
            (c.source for c in contents if c.source.id == job.get("source_id")), None
        )
        if job["kind"] == "extraction":
            if (not current or current.fingerprint != job["source_fingerprint"]
                    or (job.get("page_job") and job["scope"] != _page_scope(draft))):
                raise ValueError(
                    "Source details changed while reading. Start again to read the current version."
                )
            facts = ai.normalize_facts(
                result,
                current,
                job["pages"],
                draft.profile,
                draft.period,
                ai.vendor_names(draft),
            )
            if job.get("page_job"):
                if not items.accept(draft.profile, draft.period, job["key"],
                                    job.get("token"), result):
                    raise ValueError("A newer page reading took precedence. Existing facts were preserved.")
                _merge_page_facts(prefix, current, facts)
            else:
                ai.save_cache(draft.profile, "extraction", job["key"], result)
                st.session_state[prefix + "_ai_facts"] = (
                    current.id, current.fingerprint, facts,
                )
        elif job["kind"] == "coverage":
            if not current or current.fingerprint != job["source_fingerprint"]:
                raise ValueError("The source changed while reading. Earlier suggestions were not applied.")
            outcome = coverage.collect(job["plan"], result, current, draft.profile, draft.period)
            for cache_key, response in outcome["cacheable"]:
                try:
                    ai.save_cache(draft.profile, "full_coverage", cache_key, response)
                except (ValueError, OSError):
                    st.warning("A verified reading could not be cached; its suggestions remain available.")
            previous = st.session_state.get(prefix + "_ai_facts")
            retained = {
                fact.id: fact for fact in previous[2]
            } if (previous and previous[0] == current.id
                  and previous[1] == current.fingerprint) else {}
            retained.update((fact.id, fact) for fact in outcome["facts"])
            st.session_state[prefix + "_ai_facts"] = (
                current.id, current.fingerprint, tuple(retained.values()))
            st.session_state[prefix + "_ai_coverage"] = (
                current.id, current.fingerprint, outcome, job["plan"].pages)
        elif job["kind"] == "all_coverage":
            if job["owner_scope"] != _approval_scope(draft, prefix):
                raise ValueError("The report context changed while reading. Earlier suggestions were not applied.")
            by_id = {content.source.id: content.source for content in contents}
            if len(by_id) != len(contents):
                raise ValueError("Duplicate source identities require review before automatic reading.")
            if any(source_id not in by_id or by_id[source_id].fingerprint != fingerprint
                   for source_id, fingerprint, _ in job["plans"]):
                raise ValueError("The source collection changed while reading. Earlier suggestions were not applied.")
            pending = {}
            for source_id, fingerprint, planned in job["plans"]:
                source = by_id[source_id]
                outcome = coverage.collect(planned, result, source, draft.profile, draft.period)
                for cache_key, response in outcome["cacheable"]:
                    try:
                        ai.save_cache(draft.profile, "full_coverage", cache_key, response)
                    except (ValueError, OSError):
                        st.warning("A verified source reading could not be cached; its facts remain available.")
                pending[source_id] = (fingerprint, outcome["facts"], outcome, planned.pages)
            st.session_state[prefix + "_ai_all_proposals"] = pending
        elif job["kind"] == "draft":
            if (
                tuple(s.fingerprint for s in draft.sources)
                != job["source_fingerprints"]
            ):
                raise ValueError(
                    "Evidence changed while drafting. Your report is preserved; draft again from current evidence."
                )
            block = ai.normalize_draft(
                result, job["block"], job["facts"], draft.sources
            )
            ai.save_cache(draft.profile, "draft", job["key"], result)
            st.session_state[prefix + "_ai_suggestion"] = block
        else:
            from app.monthly_report_image_review import complete_review

            if not current or current.fingerprint != job["source_fingerprint"]:
                raise ValueError(
                    "Source details changed while reading the image. Read the current version again."
                )
            pages = list(current.page_texts)
            page = job["page"]
            if type(page) is not int or not 1 <= page <= len(pages) or not isinstance(result, str):
                raise ValueError("The reader returned an invalid page result. Existing evidence is unchanged.")
            complete_review(job["scope"], job["key"], result)
            changed = pages[page - 1] != result
            pages[page - 1] = result
            revised = replace(current, page_texts=tuple(pages),
                client_page_reviews=tuple(review for review in current.client_page_reviews
                                          if not changed or review[0] != page),
                facts=tuple(fact for fact in current.facts if not changed or fact.page != page))
            st.session_state[prefix + "_evidence"] = tuple(
                replace(c, source=revised) if c.source.id == current.id else c
                for c in contents
            )
            st.success(
                "Image text read. Compare it with the preview before including the page or its facts."
            )
    except Exception as exc:
        if job.get("page_job") and job.get("token"):
            try:
                items.fail(job["profile"], job["period"], job["key"], job["token"])
            except (OSError, ValueError):
                # A QA reset may have retired the original namespace.
                pass
        st.warning(
            "Reading was not applied. "
            + (
                str(exc)
                if isinstance(exc, ValueError)
                else "The reader could not finish. Retry or continue with entered text."
            )
        )
    finally:
        st.session_state.pop(key, None)


def _start(prefix, draft, job, prepare, read=ai.request_json):
    try:
        future = start_receipt(prepare, read)
        if future is None:
            st.info("The document reader is busy. Try again shortly.")
            return False
        st.session_state[prefix + "_ai_job"] = {**job, "future": future}
        st.rerun()
        return True
    except ValueError as exc:
        st.warning(str(exc))
        return False


def _approval_scope(draft, prefix):
    return (draft.profile.contract, draft.profile.key, draft.period.key,
            st.session_state.get(prefix + "_rich_text_epoch", ""),
            st.session_state.get("_monthly_qa_generation", ""))


def _fact_approval(draft, prefix, source, facts):
    return ai.digest((_approval_scope(draft, prefix), source.id, source.fingerprint,
                      tuple(asdict(fact) for fact in facts)))


def _queue_fact_approval(prefix, identity):
    st.session_state[prefix + "_pending_fact_approval"] = identity


def _date_repair(prior, fact, current):
    """The saved fact with only the re-read date (and its flags) applied.

    Facts saved before exact-source binding (A55) have empty source and page
    digests. A fresh read of the same original fills them, so they may be
    adopted with the date, but only when the read is bound to this original;
    an already bound fact keeps its digests and must match them exactly.
    """
    provenance = {}
    if (not prior.source_sha256 and not prior.page_sha256
            and fact.source_sha256 == current.sha256):
        provenance = {"source_sha256": fact.source_sha256, "page_sha256": fact.page_sha256}
    return replace(prior, date=fact.date, flags=fact.flags, **provenance)


def _apply_pending_fact_approval(draft, prefix):
    """A native click approves only the exact currently available proposal."""
    expected = st.session_state.pop(prefix + "_pending_fact_approval", None)
    if expected is None:
        return
    contents = st.session_state.get(prefix + "_evidence", ())
    proposed = st.session_state.get(prefix + "_ai_facts")
    current = next((content.source for content in contents
                    if proposed and content.source.id == proposed[0]), None)
    if (not proposed or not current or not proposed[2]
            or proposed[1] != current.fingerprint
            or st.session_state.get(prefix + "_ai_source", current.id) != current.id
            or prefix + "_ai_job" in st.session_state
            or _fact_approval(draft, prefix, current, proposed[2]) != expected):
        st.warning("The source or facts changed before that choice reached the report. Review the current facts and choose Use these facts again.")
        return
    # Reading is bounded by source/page chunks. Use these facts accepts that
    # chunk; it is not permission to remove previously accepted facts from
    # this source. Deterministic fact IDs make unchanged reacceptance idempotent.
    facts = {fact.id: fact for fact in current.facts}
    for fact in proposed[2]:
        prior = facts.get(fact.id)
        if prior is None:
            facts[fact.id] = fact
        elif (
            # Explicitly re-reading can repair a *provably unsupported* saved
            # date on the same immutable quote, without changing any other
            # human-edited field or replacing an already supported date.
            prior.date and fact.date and prior.date != fact.date
            and not prior.flags
            and _date_repair(prior, fact, current) == fact
            and ai.fact_date_problems((prior,), (current,))
            and not ai.fact_date_problems((fact,), (current,))
        ):
            facts[fact.id] = fact
        # Otherwise keep the accepted fact, including human corrections.
    updated = replace(current, facts=tuple(facts.values()))
    # Only native acceptance may record a receipt for later-month replay.
    from app.monthly_report_ai_replay import record_acceptance
    try:
        record_acceptance(draft.profile, current, proposed[2])
    except (OSError, ValueError) as exc:
        st.warning("Fact replay was not saved; current reviewed facts are retained. " + str(exc))
    st.session_state[prefix + "_evidence"] = tuple(
        replace(content, source=updated) if content.source.id == current.id else content
        for content in contents)
    st.session_state.pop(prefix + "_ai_facts", None)
    pending = st.session_state.get(prefix + "_ai_all_proposals")
    if pending and current.id in pending:
        pending.pop(current.id, None)


def _linked_manual_text(block):
    """Remove only the complete generated suffix, never a human substring."""
    rendered = "\n".join("- " + paragraph.text for paragraph in block.ai_paragraphs)
    if block.text == rendered:
        return ""
    suffix = "\n" + rendered
    if rendered and block.text.endswith(suffix):
        # One joining newline belongs to the generated suffix. All deliberate
        # spacing within/before the human notes remains exact.
        return block.text[:-len(suffix)]
    # Legacy mixed layouts may place exact generated bullets elsewhere. Only
    # a complete matching line can be owned; prefer the final occurrence so an
    # earlier identical human line is not removed by substring replacement.
    lines = block.text.splitlines(keepends=True)
    for paragraph in reversed(block.ai_paragraphs):
        owned = "- " + paragraph.text
        index = next((n for n in range(len(lines) - 1, -1, -1)
                      if lines[n].rstrip("\r\n") == owned), None)
        if index is not None:
            del lines[index]
    return "".join(lines)


def _linked_text_input(prefix, field, key, label, text, *, references=(), height=100):
    # Reuse the existing native receipt/recovery protocol. Widget IDs are
    # independent of typed text, so Clear and explicit Replace cannot revive
    # an obsolete field value or remount the editor on every accepted edit.
    from app.monthly_report_guided import _edit_content
    block = ResolvedBlock(key, "This month", text=text, references=references)
    return _edit_content(BlockSpec(key, "rich_text"), block, None, prefix, {}, field,
                         text_label=label, text_height=height).text


def edit_linked_paragraphs(draft, blocks, prefix, field, allowed_keys=None):
    facts = {f.id: (s, f) for s in draft.sources for f in s.facts}
    for block in tuple(blocks.values()):
        if allowed_keys is not None and block.key not in allowed_keys:
            continue
        if not block.ai_paragraphs:
            continue
        if block.source == "Omit":
            # Left-out source-linked wording keeps an explicit way back; it is
            # reviewed again once included. MBCx has its own retained-notes control.
            if block.key != "mbcx_report":
                st.caption(LABELS.get(block.key, block.key.replace("_", " "))
                           + " · left out of this report. Its wording and sources are kept.")
                if st.button("Include in this report", key=prefix + "_linked_" + block.key + "_include"):
                    blocks[block.key] = replace(block, source="This month", reviewed_fingerprint="",
                                                client_reviewed_fingerprint="")
            continue
        with st.expander(
            LABELS.get(block.key, block.key.replace("_", " "))
            + " · wording and sources",
            expanded=not block.reviewed,
        ):
            p = prefix + "_linked_" + block.key
            manual = _linked_text_input(prefix, field, "linked_" + block.key + "_manual",
                                        "Your other notes", _linked_manual_text(block))
            paragraphs = []
            native_fields = []
            from app.monthly_report_guided import _rich_text_editor_key
            manual_key = _rich_text_editor_key(prefix, ResolvedBlock("linked_" + block.key + "_manual", "This month"))
            for n, paragraph in enumerate(block.ai_paragraphs):
                identity = ai.digest((n, paragraph.fact_ids))
                text = _linked_text_input(prefix, field, "linked_" + block.key + f"_paragraph_{n}",
                    f"Report paragraph {n + 1}", paragraph.text,
                    references=paragraph.fact_ids, height=90)
                # A missing saved fact remains an explicit selected option.
                # Browsing/navigation cannot silently erase its evidence link.
                available = list(dict.fromkeys((*facts, *paragraph.fact_ids)))
                evidence_key = p + "_facts_" + identity + ai.digest(available)
                native_fields.append({"text": _rich_text_editor_key(prefix, ResolvedBlock(
                    "linked_" + block.key + f"_paragraph_{n}", "This month")), "evidence": evidence_key})
                selected = st.multiselect(
                    f"Evidence for paragraph {n + 1}",
                    available,
                    format_func=lambda k: (
                        f"{facts[k][0].filename} · page {facts[k][1].page} · {facts[k][1].text[:90]}"
                        if k in facts else "Unavailable saved fact · " + k
                    ),
                    key=field(
                        evidence_key,
                        list(paragraph.fact_ids),
                    ),
                )
                for identity in selected:
                    if identity not in facts:
                        st.caption("This saved fact is unavailable. Choose current evidence or explicitly remove its link.")
                        continue
                    source, fact = facts[identity]
                    st.caption(
                        f"{ai.clean_text(source.filename)}, page {fact.page} · "
                        f"original SHA-256 {fact.source_sha256 or source.sha256}: "
                        + ai.fact_quote_for_display(fact.quote)
                    )
                paragraphs.append(
                    replace(
                        paragraph, text=ai.clean_text(text), fact_ids=tuple(selected)
                    )
                )
            candidate = replace(
                block,
                ai_paragraphs=tuple(paragraphs),
                text="\n".join(
                    t
                    for t in (manual, "\n".join("- " + p.text for p in paragraphs))
                    if t
                ),
            )
            try:
                candidate = ai.refresh_evidence(candidate, draft.sources)
                for paragraph in candidate.ai_paragraphs:
                    for flag in paragraph.flags:
                        st.warning(flag)
                same = candidate.fingerprint == block.fingerprint and block.reviewed
                checked = st.checkbox(
                    "I checked this wording against the displayed current evidence",
                    key=field(p + "_review_" + candidate.fingerprint, same),
                )
                if checked:
                    candidate = ai.reviewed_block(candidate, draft.sources)
                else:
                    st.caption(
                        "Needs review. Changes to text or evidence clear this confirmation."
                    )
            except ValueError as exc:
                candidate = replace(candidate, reviewed_fingerprint="")
                st.warning(str(exc))
            blocks[block.key] = candidate
            st.session_state.setdefault(prefix + "_ai_linked_controls", {})[block.key] = {
                "paragraphs": candidate.ai_paragraphs, "manual": manual_key, "fields": tuple(native_fields)}
            from app.monthly_report_ai_correction_ui import render_paragraph_marker
            render_paragraph_marker(prefix, replace(draft,blocks=tuple(blocks.values())), candidate, native_fields)
    return blocks


def render_drafting(draft, blocks, prefix, field, allowed_keys=None, *, editor_container=None):
    """Return updated draft/blocks; caller still owns snapshot confirmation."""
    _finish_job(draft, prefix)
    _advance_page_reads(draft, prefix)
    _apply_pending_fact_approval(draft, prefix)
    busy = prefix + "_ai_job" in st.session_state
    if busy:
        _reading_progress(prefix)
    evidence_key = prefix + "_evidence"
    contents = st.session_state.get(evidence_key, ())
    from app.monthly_report_ai_replay import ReviewedReplay, replay_reviewed_facts
    replay_seen_key = prefix + "_accepted_replay_seen"
    seen = set(st.session_state.get(replay_seen_key, ()))
    replayed = {}
    enriched = []
    for content in contents:
        source = content.source
        token = ai.digest((draft.profile.contract, draft.profile.key, draft.period.key,
                           tuple(f.key for f in draft.profile.facilities),
                           source.id, source.sha256, source.scope_review, source.page_texts))
        receipt_key = prefix + "_accepted_replay_" + token
        if token not in seen:
            try:
                past = replay_reviewed_facts(draft, source)
            except (OSError, ValueError) as exc:
                st.warning("Prior extraction could not be verified and was not reused: " + str(exc))
                past = ReviewedReplay()
            st.session_state[receipt_key] = past
            seen.add(token)
            if past.reusable:
                facts = {fact.id: fact for fact in source.facts}
                facts.update((fact.id, fact) for fact in past.reusable)
                source = replace(source, facts=tuple(facts.values()))
                content = replace(content, source=source)
        replayed[source.id] = st.session_state.get(receipt_key, ReviewedReplay())
        enriched.append(content)
    st.session_state[replay_seen_key] = tuple(seen)
    if tuple(enriched) != tuple(contents):
        contents = tuple(enriched)
        st.session_state[evidence_key] = contents
    draft = replace(draft, sources=tuple(content.source for content in contents))
    targets = [key for key in LABELS if allowed_keys is None or key in allowed_keys]
    if not targets:
        return draft, edit_linked_paragraphs(draft, blocks, prefix, field, allowed_keys)
    from app.monthly_report_activity_notes_draft import render_activity_notes
    draft, blocks = render_activity_notes(draft, blocks, prefix, field,
                                          enabled="activity_summary" in targets)
    # Keep optional writing mechanics out of the primary Activity editor.
    # Everything still renders in the same section so a reviewed suggestion
    # can be accepted without navigating away or overwriting manual work.
    with st.expander("Help write this summary", expanded=False):
        st.caption(
            "Use reviewed source facts to suggest wording. Check the proposal, "
            "then choose Add or Replace."
        )
        st.caption("Reading and drafting send selected text or page images to the external document reader and may use paid requests. Choose a reading or drafting action to start.")
        with st.expander("Limits"):
            st.caption("Maximum 80 paid reading/drafting requests shared by this profile and report month, including retries; cached calls are reused. Each model call is limited to 60,000 characters. Full-source reading partitions long uploads automatically; automatic image reading has a separate bounded allowance.")
        if contents:
            # Bulk reading is an explicit paid action, never an upload side effect.
            # Only previously classified, in-scope files are admitted; the
            # source manager continues to own unknown/other-site decisions.
            from app import monthly_report_structured_uploads as structured
            names = {
                name.casefold() for facility in draft.profile.facilities
                for name in (facility.key, facility.title, *facility.aliases)
            }
            eligible_all = tuple(
                c for c in structured.reader_sources(contents, "activity_summary")
                if c.source.classification != "Reference only"
                and c.source.facility.casefold() in names
            )
            if len(contents) > 1:
                st.caption(
                    f"{len(eligible_all)} of {len(contents)} uploaded sources are "
                    "eligible for a single full-document fact read. Unknown "
                    "classification, unknown-site, other-site and unmapped activity sources "
                    "remain intact and require individual review.")
                if st.button(
                    "Find facts across eligible uploaded files",
                    key=prefix + "_ai_extract_all",
                    disabled=busy or not eligible_all,
                ):
                    try:
                        plans = tuple(
                            (c.source.id, c.source.fingerprint, coverage.plan(c.source))
                            for c in eligible_all if c.source.page_texts)
                        if not plans:
                            raise ValueError("No classified source has readable or visual pages.")
                        selected_contents = {c.source.id: c for c in eligible_all}

                        def prepare_all():
                            return coverage.join_prepared(tuple(
                                coverage.prepare_run(
                                    planned, selected_contents[source_id],
                                    draft.profile, draft.period)
                                for source_id, _, planned in plans))

                        _start(
                            prefix, draft,
                            {"kind": "all_coverage", "plans": plans,
                             "owner_scope": _approval_scope(draft, prefix)},
                            prepare_all, coverage.run)
                    except ValueError as exc:
                        st.warning(str(exc))
            by_id = {c.source.id: c for c in contents}
            chosen = st.selectbox(
                "File to read for work performed",
                list(by_id),
                format_func=lambda k: by_id[k].source.filename,
                key=prefix + "_ai_source",
            )
            source = by_id[chosen].source
            past = replayed.get(source.id, ReviewedReplay())
            if past.reusable:
                st.caption(f"{len(past.reusable)} verified recommendations reused from "
                           f"{past.from_period}; corrected text remains editable.")
            if past.historical:
                st.caption(f"{len(past.historical)} accepted facts from {past.from_period} "
                           "remain historical, not work completed in this report month.")
                for fact in past.historical:
                    st.write(f"Earlier month · Page {fact.page} · {fact.text}")
            all_pending = st.session_state.get(prefix + "_ai_all_proposals", {})
            if (chosen in all_pending
                    and all_pending[chosen][0] == source.fingerprint):
                fingerprint, facts, outcome, selected_pages = all_pending[chosen]
                st.session_state[prefix + "_ai_facts"] = (
                    chosen, fingerprint, facts)
                st.session_state[prefix + "_ai_coverage"] = (
                    chosen, fingerprint, outcome, selected_pages)
            pages = st.multiselect(
                "Pages to read for facts",
                list(range(1, len(source.page_texts) + 1)),
                default=list(range(1, len(source.page_texts) + 1)),
                key=field(prefix + "_ai_read_pages_" + source.id,
                          list(range(1, len(source.page_texts) + 1))),
                help="Reading facts does not include the original pages in the client report. Pages containing prices stay excluded from output.",
            )
            from app.monthly_report_ai_correction_ui import render_fact_page_context
            render_fact_page_context(prefix,replace(draft,blocks=tuple(blocks.values())),source,by_id[chosen])
            reviewed_pages = {fact.page for fact in (*past.reusable, *past.historical)}
            already_reviewed = bool(pages and set(pages) <= reviewed_pages)
            if already_reviewed:
                st.caption("These pages have accepted source-linked facts. Use the earlier "
                           "review without a model request, or explicitly read again.")
            read_again = (st.button("Re-read pages for additional facts (uses document reader)",
                                    key=prefix + "_ai_reread", disabled=busy)
                          if already_reviewed else False)
            if st.button(
                "Find work, findings and follow-ups",
                key=prefix + "_ai_extract",
                disabled=busy or not pages,
            ) or read_again:
                try:
                    if already_reviewed and not read_again:
                        st.info("Prior reviewed facts are displayed above. No paid extraction "
                                "request was made; earlier work remains historical.")
                    else:
                        if source.facility and source.facility.casefold() not in names:
                            raise ValueError("This file is assigned to another site. Correct its source scope before sending it to the reader.")
                        needs_coverage = (
                            len(pages) > 20
                            or sum(len(source.page_texts[n - 1]) for n in pages) > ai.MAX_EVIDENCE_CHARS
                            or any(n in source.needs_vision for n in pages)
                        )
                        if needs_coverage:
                            planned = coverage.plan(source, pages)

                            def prepare():
                                return coverage.prepare_run(
                                    planned, by_id[chosen], draft.profile, draft.period)

                            _start(
                                prefix, draft,
                                {
                                    "kind": "coverage",
                                    "source_id": source.id,
                                    "source_fingerprint": source.fingerprint,
                                    "plan": planned,
                                },
                                prepare,
                                coverage.run,
                            )
                        else:
                            _queue_page_reads(draft, prefix, source, pages)
                except ValueError as exc:
                    st.warning(str(exc))
            # Each source/page is an independent content-hash receipt. Cached
            # reads are not human-approved until Use these facts is clicked.
            states = {}
            for page in pages:
                try:
                    key, _ = ai.extraction_request(source, (page,))
                    states[page] = items.status(draft.profile, draft.period, key)
                except ValueError:
                    states[page] = "unread"
            if states:
                st.caption(
                    "Page reading: "
                    + ", ".join(f"{sum(v == status for v in states.values())} {status}"
                                for status in ("accepted", "pending", "failed", "unread"))
                    + ". Accepted readings still need your fact review."
                )
            failed_pages = [page for page, status in states.items() if status == "failed"]
            if failed_pages and st.button(
                "Retry failed pages only",
                key=prefix + "_ai_retry_failed",
                disabled=busy,
            ):
                try:
                    _queue_page_reads(draft, prefix, source, failed_pages, failed_only=True)
                except ValueError as exc:
                    st.warning(str(exc))
            image_pages = [n for n in source.needs_vision if n in pages]
            if image_pages:
                page = st.selectbox(
                    "Scanned page to read",
                    image_pages,
                    key=prefix + "_ai_image_" + source.id,
                )
                if st.button(
                    "Read this scanned page", key=prefix + "_ai_ocr", disabled=busy
                ):
                    from app.monthly_report_sources import page_image
                    from app.monthly_report_image_review import (
                        prepare_bytes_review,
                        read_image,
                    )

                    scope = (
                        library.imported_review_scope(
                            draft.profile.contract, draft.profile.key, draft.period
                        )
                        or prefix
                    )
                    meta = {
                        "kind": "ocr",
                        "source_id": source.id,
                        "source_fingerprint": source.fingerprint,
                        "page": page,
                        "scope": scope,
                    }

                    def prepare():
                        image = page_image(
                            draft.profile, by_id[chosen], page, preview=True
                        )
                        key, saved, content = prepare_bytes_review(
                            scope, image.data, "." + image.extension
                        )
                        meta["key"] = key
                        return saved, content

                    _start(
                        prefix, draft, meta, prepare, lambda v: v[0] or read_image(v[1])
                    )
            coverage_state = st.session_state.get(prefix + "_ai_coverage")
            if coverage_state and (coverage_state[0], coverage_state[1], coverage_state[3]) == (
                    source.id, source.fingerprint, tuple(pages)):
                outcome = coverage_state[2]
                inventory = outcome["inventory"]
                ready_pages = sum(status == "ready" for status in inventory.values())
                st.caption(
                    f"Reader inventory: {len(inventory)}/{len(pages)} selected pages accounted; "
                    f"{ready_pages} classified from native evidence, "
                    f"{len(inventory) - ready_pages} need visual/manual review or a retry. "
                    f"{outcome['rejected_claims']} ungrounded claims withheld. "
                    f"{outcome['admitted_calls']} new calls, "
                    f"{outcome['cache_hits']} cache hits; "
                    f"{outcome['total_seconds']:.2f}s network/queue worker time "
                    "(not a UI first-paint measurement).")
                if ready_pages != len(inventory):
                    pending_pages = [str(n) for n, status in inventory.items()
                                     if status != "ready"]
                    st.warning(
                        "No pages were silently discarded. Pages needing review or retry: "
                        + ", ".join(pending_pages[:30])
                        + ("…" if len(pending_pages) > 30 else "")
                        + ". Choose Find work, findings and follow-ups to retry uncached pages.")
            proposed = st.session_state.get(prefix + "_ai_facts")
            if proposed and proposed[0] == source.id:
                if proposed[1] != source.fingerprint:
                    st.info(
                        "File details changed. Read it again before accepting facts."
                    )
                else:
                    st.write(f"{len(proposed[2])} facts found")
                    for fact in proposed[2]:
                        st.write(f"Page {fact.page} · {fact.text}")
                        st.caption(
                            f"Original SHA-256 {fact.source_sha256 or source.sha256} · "
                            f"Exact quote: {ai.fact_quote_for_display(fact.quote)}"
                        )
                        if fact.flags:
                            st.warning("; ".join(fact.flags))
                    st.caption("These facts support suggested wording. Original pages keep their own inclusion decisions.")
                    # Equal fact text does not imply an unchanged source. Bind
                    # the native action and its delivered receipt to both.
                    identity = _fact_approval(draft, prefix, source, proposed[2])
                    st.button("Use these facts", disabled=busy or not proposed[2],
                              key=prefix + "_ai_use_facts_" + identity,
                              on_click=_queue_fact_approval, args=(prefix, identity))
        with st.expander("Use Copilot", expanded=False):
            st.caption("1. Copy the prompt. 2. Ask Copilot. 3. Paste its answer below.")
            prompt = copilot_prompt(
                draft.profile,
                draft.period,
                ai.vendor_names(draft),
                draft.profile.asset_tags,
            )
            copy_prompt(prompt)
            with st.expander("View prompt text (if copying does not work)"):
                st.text_area(
                    "Prompt to copy manually if needed",
                    prompt,
                    height=100,
                    key=prefix + "_copilot_prompt_" + ai.digest(prompt),
                )
            pasted = st.text_area(
                "Paste Copilot's response",
                key=field(prefix + "_copilot_paste", ""),
                height=150,
            )
            if pasted.strip():
                try:
                    candidate, unmatched, priced = copilot_source(
                        pasted, draft.profile, draft.period
                    )
                    st.caption(
                        f"{len(candidate.facts)} usable lines; {len(unmatched)} lines need placement; {priced} priced lines excluded from suggestions."
                    )
                    if unmatched:
                        st.text("\n".join(f"Line {n}: {t}" for n, t in unmatched))
                        st.caption(
                            "These lines remain in your pasted notes. Correct their heading/date/source before adding them."
                        )
                    if st.button(
                        "Use these notes as evidence",
                        disabled=not candidate.facts,
                        key=prefix + "_copilot_use_" + ai.digest((_approval_scope(draft, prefix), candidate.fingerprint)),
                    ) and candidate.facts:
                        if candidate.id not in {c.source.id for c in contents}:
                            # Store text like other originals, without executing or uploading it.
                            from app.monthly_report_sources import (
                                _path,
                                MAX_SOURCES,
                                MAX_REPORT_TEXT,
                            )

                            if (
                                len(contents) >= MAX_SOURCES
                                or sum(
                                    len(t)
                                    for c in contents
                                    for t in c.source.page_texts
                                )
                                + len(pasted)
                                > MAX_REPORT_TEXT
                            ):
                                raise ValueError(
                                    "This report's source/text allowance is used. Remove unused sources before adding notes."
                                )
                            library._atomic_write(
                                _path(draft.profile, candidate.sha256, ".txt"),
                                pasted.encode(),
                            )
                            st.session_state[evidence_key] = (
                                *contents,
                                SourceContent(candidate),
                            )
                        st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
        sources = tuple(c.source for c in st.session_state.get(evidence_key, ()))
        draft = replace(draft, sources=sources)
        if len(targets) == 1:
            target = targets[0]
            st.caption("Suggested wording will go in " + LABELS[target].lower() + ".")
        else:
            target_key = field(prefix + "_ai_target", targets[0])
            if st.session_state[target_key] not in targets:
                st.session_state[target_key] = targets[0]
            target = st.selectbox("Part to help write", targets, format_func=LABELS.get, key=target_key)
        instruction = st.text_input(
            "Optional redraft instruction",
            key=field(prefix + "_ai_instruction", ""),
            max_chars=2000,
        )
        if st.button(
            "Suggest wording / redraft",
            key=prefix + "_ai_draft",
            disabled=busy or not any(s.facts for s in sources),
        ):
            try:
                key, content, facts = ai.drafting_request(
                    target,
                    sources,
                    draft.period,
                    ai.vendor_names(draft),
                    draft.profile.asset_tags,
                    instruction,
                )
                saved = ai.cached(draft.profile, "draft", key)
                if saved is not None:
                    st.session_state[prefix + "_ai_suggestion"] = ai.normalize_draft(
                        saved, target, facts, sources
                    )
                else:

                    def prepare():
                        ai.reserve_call(draft.profile, draft.period)
                        return content

                    _start(
                        prefix,
                        draft,
                        {
                            "kind": "draft",
                            "key": key,
                            "block": target,
                            "facts": facts,
                            "source_fingerprints": tuple(
                                s.fingerprint for s in sources
                            ),
                        },
                        prepare,
                        read=lambda chunk: ai.request_json(
                            chunk,
                            response_kind="paragraphs",
                            validator=lambda value: ai.normalize_draft(
                                value, target, facts, sources,
                            ),
                        ),
                    )
            except ValueError as exc:
                st.warning(str(exc))
        suggestion = st.session_state.get(prefix + "_ai_suggestion")
        if suggestion and suggestion.key in targets:
            st.subheader("Check the suggested wording")
            st.caption(
                "Nothing below replaces your report until you choose Add or Replace."
            )
            facts = {f.id: f for s in sources for f in s.facts}
            fact_sources = {f.id: s for s in sources for f in s.facts}
            paragraphs, ready = [], True
            for n, paragraph in enumerate(suggestion.ai_paragraphs):
                text = st.text_area(
                    f"Suggested paragraph {n + 1}",
                    key=field(
                        prefix + "_ai_p_" + suggestion.fingerprint + str(n),
                        paragraph.text,
                    ),
                    height=90,
                )
                evidence = "\n".join(
                    f"{ai.clean_text(fact_sources[i].filename)}, page {facts[i].page} · "
                    f"original SHA-256 {facts[i].source_sha256 or fact_sources[i].sha256}: "
                    + ai.fact_quote_for_display(facts[i].quote)
                    for i in paragraph.fact_ids
                    if i in facts
                )
                st.caption(evidence or "Source evidence is no longer available.")
                flags = tuple(
                    f for f in paragraph.flags if "Unsupported number" not in f
                )
                if ai.numbers(text) - ai.fact_numbers(facts[i] for i in paragraph.fact_ids if i in facts):
                    flags += ("Unsupported number: correct against the evidence",)
                for flag in flags:
                    st.warning(flag)
                checked = st.checkbox(
                    f"I checked paragraph {n + 1} against its source",
                    key=prefix + "_ai_p_ok_" + ai.digest((text, evidence, flags)),
                )
                ready &= (
                    checked
                    and bool(text.strip())
                    and not ai.contains_price(text)
                    and not any("Unsupported number" in f for f in flags)
                )
                paragraphs.append(
                    replace(paragraph, text=ai.clean_text(text), flags=flags)
                )
            ready &= bool(
                paragraphs
            ) and suggestion.ai_evidence_fingerprint == ai.evidence_fingerprint(
                sources, suggestion.references
            )
            existing = blocks.get(suggestion.key)
            # This help precedes the ordinary native editor. Its callback may
            # already have delivered newer wording on the same request as an
            # older Replace click; keep that input and show its current value.
            from app.monthly_report_guided import _pending_rich_text_edit
            pending_manual = _pending_rich_text_edit(prefix, existing) if existing else None
            if pending_manual is not None:
                st.info("Your latest wording is shown below. Check it before choosing Add or Replace.")
            compared = pending_manual or existing
            st.text(
                "Current wording:\n"
                + (compared.text if compared else "Nothing entered yet.")
            )
            mode = st.radio(
                "Use the checked suggestion",
                ["Add below existing wording", "Replace existing wording"],
                key=prefix + "_ai_apply_mode",
            )
            if st.button(
                "Dismiss suggestion — keep my current wording",
                key=prefix + "_ai_dismiss",
            ):
                st.session_state.pop(prefix + "_ai_suggestion", None)
                st.info("Suggestion dismissed. Your report content and sources are unchanged.")
                st.rerun()
            if st.button(
                "Use checked wording in this report",
                disabled=not ready,
                key=prefix + "_ai_apply_" + ai.digest((
                    _approval_scope(draft, prefix), suggestion.fingerprint,
                    compared.fingerprint if compared else "", mode,
                    tuple(asdict(paragraph) for paragraph in paragraphs),
                    ai.evidence_fingerprint(sources, suggestion.references))),
            ) and ready and pending_manual is None:
                revised = replace(
                    suggestion,
                    ai_paragraphs=tuple(paragraphs),
                    text="\n".join("- " + p.text for p in paragraphs),
                )
                blocks[revised.key] = ai.apply_suggestion(
                    existing, revised, sources, append=mode.startswith("Add")
                )
                draft = replace(
                    draft,
                    sections=tuple(
                        replace(s, included=True)
                        if any(b.key == revised.key for b in s.blocks)
                        else s
                        for s in draft.sections
                    ),
                )
                st.session_state.pop(prefix + "_ai_suggestion", None)
                # Remove stale widget mirrors so the normal editor shows the accepted text.
                for key in list(st.session_state):
                    if key.startswith(prefix + "_edit_" + revised.key + "_text_"):
                        del st.session_state[key]
                st.session_state["report_draft_mirror"] = {
                    k: v
                    for k, v in st.session_state.get("report_draft_mirror", {}).items()
                    if not k.startswith(prefix + "_edit_" + revised.key + "_text_")
                }
                st.success(
                    "Checked wording added. Existing pictures and tables were retained."
                )
    from contextlib import nullcontext
    with editor_container if editor_container is not None else nullcontext():
        blocks = edit_linked_paragraphs(draft, blocks, prefix, field, allowed_keys)
    return draft, blocks
