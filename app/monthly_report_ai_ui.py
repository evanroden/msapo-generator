"""Optional reading/drafting controls, with explicit comparison before applying."""

from dataclasses import asdict, replace
import hashlib
import json

import streamlit as st

from app import monthly_report_ai as ai, monthly_report_library as library
from app.monthly_report_model import EvidenceFact, ReportSource
from app.monthly_report_prompts import copilot_prompt, parse_copilot
from app.monthly_report_sources import SourceContent
from app.receipt_jobs import start_receipt


LABELS = {"activity_summary": "Work done this month", "improvements": "Improvement titles and captions",
          "equipment_issues": "Equipment issues", "training_summary": "Training summary",
          "work_orders": "Work-order narrative", "proposals": "Proposals and follow-ups"}


def copy_prompt(prompt):
    # Same clipboard fallback and JSON escaping used by the existing handoff
    # component. Source text is data, never interpolated executable markup.
    payload = json.dumps(prompt).replace("<", "\\u003c")
    st.iframe("""<button id="copy" style="padding:12px;background:#D6EF4B;border:1px solid #092B24;border-radius:6px">Copy Copilot prompt</button>
<span id="status" role="status"></span><script>
const text=PAYLOAD;document.getElementById('copy').onclick=async()=>{
let ok=false;try{await navigator.clipboard.writeText(text);ok=true}catch(_){}
if(!ok){let t=document.createElement('textarea');t.value=text;t.contentEditable='true';t.readOnly=false;t.style.cssText='position:fixed;opacity:0;width:1px;height:1px';document.body.appendChild(t);t.focus();t.setSelectionRange(0,text.length);try{ok=document.execCommand('copy')}catch(_){}t.remove()}
document.getElementById('status').textContent=ok?' Copied':' Copy failed. Select the prompt below.';};</script>""".replace("PAYLOAD", payload), height=60)


def copilot_source(text, profile, period):
    lines, unmatched = parse_copilot(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    identity = "copilot-" + digest[:20]
    source = ReportSource(identity, "Pasted Copilot notes.txt", digest, ".txt", page_texts=tuple(l.text + " [" + l.source + "]" for l in lines))
    kinds = {1: "action", 2: "action", 3: "issue", 4: "proposal", 5: "action", 6: "training", 7: "improvement", 8: "follow_up"}
    facts = []
    for n, line in enumerate(lines, 1):
        if ai.contains_price(line.text):
            continue  # Original pasted notes remain available; report the count.
        flags = ["Pasted Copilot summary: verify the cited original"]
        if line.source == "Source not supplied":
            flags.append("Source not supplied")
        facts.append(EvidenceFact("fact-" + ai.digest((identity, n))[:20], identity, n, kinds[line.section],
                                  ai.clean_text(line.text), ai.clean_text(line.text), flags=tuple(flags)))
    return replace(source, facts=tuple(facts)), unmatched, len(lines) - len(facts)


def _finish_job(draft, prefix):
    key = prefix + "_ai_job"
    job = st.session_state.get(key)
    if not job:
        return
    if not job["future"].done():
        st.info("Reading evidence… You can keep editing. Your existing report stays intact.")
        st.button("Check reading progress", key=prefix + "_ai_check")
        return
    try:
        result = job["future"].result()
        contents = st.session_state.get(prefix + "_evidence", ())
        current = next((c.source for c in contents if c.source.id == job.get("source_id")), None)
        if job["kind"] == "extraction":
            if not current or current.fingerprint != job["source_fingerprint"]:
                raise ValueError("Source details changed while reading. Start again to read the current version.")
            facts = ai.normalize_facts(result, current, job["pages"], draft.profile, draft.period, ai.vendor_names(draft))
            ai.save_cache(draft.profile, "extraction", job["key"], result)
            st.session_state[prefix + "_ai_facts"] = (current.id, current.fingerprint, facts)
        elif job["kind"] == "draft":
            if tuple(s.fingerprint for s in draft.sources) != job["source_fingerprints"]:
                raise ValueError("Evidence changed while drafting. Your report is preserved; draft again from current evidence.")
            block = ai.normalize_draft(result, job["block"], job["facts"], draft.sources)
            ai.save_cache(draft.profile, "draft", job["key"], result)
            st.session_state[prefix + "_ai_suggestion"] = block
        else:
            from app.monthly_report_image_review import complete_review
            if not current or current.fingerprint != job["source_fingerprint"]:
                raise ValueError("Source details changed while reading the image. Read the current version again.")
            complete_review(job["scope"], job["key"], result)
            pages = list(current.page_texts)
            pages[job["page"]-1] = result
            revised = replace(current, page_texts=tuple(pages), client_page_reviews=(), facts=())
            st.session_state[prefix + "_evidence"] = tuple(replace(c, source=revised) if c.source.id == current.id else c for c in contents)
            st.success("Image text read. Compare it with the preview before including the page or its facts.")
    except Exception as exc:
        st.warning("Reading was not applied. " + (str(exc) if isinstance(exc, ValueError) else "The reader could not finish. Retry or continue with entered text."))
    finally:
        st.session_state.pop(key, None)


def _start(prefix, draft, job, prepare, read=ai.request_json):
    try:
        future = start_receipt(prepare, read)
        if future is None:
            st.info("The document reader is busy. Try again shortly.")
        else:
            st.session_state[prefix + "_ai_job"] = {**job, "future": future}
            st.rerun()
    except ValueError as exc:
        st.warning(str(exc))


def render_drafting(draft, blocks, prefix, field):
    """Return updated draft/blocks; caller still owns snapshot confirmation."""
    _finish_job(draft, prefix)
    busy = prefix + "_ai_job" in st.session_state
    evidence_key = prefix + "_evidence"
    contents = st.session_state.get(evidence_key, ())
    with st.expander("Help write this month’s updates", expanded=bool(contents)):
        st.write("Read the useful facts from your files, then review suggested wording before adding it. Existing text and pages are preserved.")
        st.caption("No prices in suggestions. Maximum 80 reading/drafting requests per report/month; cached results are reused. Each source read is limited to 60,000 characters. Image reading shares the report's 20-image allowance.")
        if contents:
            by_id = {c.source.id: c for c in contents}
            chosen = st.selectbox("File to read for work performed", list(by_id), format_func=lambda k: by_id[k].source.filename, key=prefix + "_ai_source")
            source = by_id[chosen].source
            pages = st.multiselect("Pages to read for facts", list(range(1, len(source.page_texts)+1)),
                                   default=list(range(1, len(source.page_texts)+1)), key=prefix + "_ai_read_pages_" + source.id,
                                   help="Reading facts does not include the original pages in the client report. Pages containing prices stay excluded from output.")
            if st.button("Find work, findings and follow-ups", key=prefix + "_ai_extract", disabled=busy or not pages):
                try:
                    key, content = ai.extraction_request(source, pages)
                    saved = ai.cached(draft.profile, "extraction", key)
                    if saved is not None:
                        facts = ai.normalize_facts(saved, source, pages, draft.profile, draft.period, ai.vendor_names(draft))
                        st.session_state[prefix + "_ai_facts"] = (source.id, source.fingerprint, facts)
                    else:
                        def prepare():
                            ai.reserve_call(draft.profile, draft.period)
                            return content
                        _start(prefix, draft, {"kind": "extraction", "key": key, "source_id": source.id,
                                             "source_fingerprint": source.fingerprint, "pages": pages}, prepare)
                except ValueError as exc:
                    st.warning(str(exc))
            image_pages = [n for n in source.needs_vision if n in pages]
            if image_pages:
                page = st.selectbox("Scanned page to read", image_pages, key=prefix + "_ai_image_" + source.id)
                if st.button("Read this scanned page", key=prefix + "_ai_ocr", disabled=busy):
                    from app.monthly_report_sources import page_image
                    from app.monthly_report_image_review import prepare_bytes_review, read_image
                    scope = library.imported_review_scope(draft.profile.contract, draft.profile.key, draft.period) or prefix
                    meta = {"kind": "ocr", "source_id": source.id, "source_fingerprint": source.fingerprint, "page": page, "scope": scope}
                    def prepare():
                        image = page_image(draft.profile, by_id[chosen], page, preview=True)
                        key, saved, content = prepare_bytes_review(scope, image.data, "." + image.extension)
                        meta["key"] = key
                        return saved, content
                    _start(prefix, draft, meta, prepare, lambda v: v[0] or read_image(v[1]))
            proposed = st.session_state.get(prefix + "_ai_facts")
            if proposed and proposed[0] == source.id:
                if proposed[1] != source.fingerprint:
                    st.info("File details changed. Read it again before accepting facts.")
                else:
                    st.write(f"{len(proposed[2])} facts found")
                    for fact in proposed[2]:
                        st.write(f"Page {fact.page} · {fact.text}")
                        if fact.flags:
                            st.warning("; ".join(fact.flags))
                    accept = st.checkbox("Use these facts as evidence for suggestions", key=prefix + "_ai_accept_facts_" + ai.digest([asdict(f) for f in proposed[2]]))
                    if st.button("Keep these facts", disabled=not accept, key=prefix + "_ai_keep_facts"):
                        updated = replace(source, facts=proposed[2])
                        st.session_state[evidence_key] = tuple(replace(c, source=updated) if c.source.id == source.id else c for c in contents)
                        st.session_state.pop(prefix + "_ai_facts", None)
                        st.rerun()
        with st.expander("Add optional Copilot notes"):
            prompt = copilot_prompt(draft.profile, draft.period, ai.vendor_names(draft), draft.profile.asset_tags)
            copy_prompt(prompt)
            st.text_area("Prompt to copy manually if needed", prompt, height=100, key=prefix + "_copilot_prompt_" + ai.digest(prompt))
            pasted = st.text_area("Paste Copilot's response", key=field(prefix + "_copilot_paste", ""), height=150)
            if pasted.strip():
                try:
                    candidate, unmatched, priced = copilot_source(pasted, draft.profile, draft.period)
                    st.caption(f"{len(candidate.facts)} usable lines; {len(unmatched)} lines need placement; {priced} priced lines excluded from suggestions.")
                    if unmatched:
                        st.text("\n".join(f"Line {n}: {t}" for n, t in unmatched))
                        st.caption("These lines remain in your pasted notes. Correct their heading/date/source before adding them.")
                    if st.button("Use these notes as evidence", disabled=not candidate.facts, key=prefix + "_copilot_use"):
                        if candidate.id not in {c.source.id for c in contents}:
                            # Store text like other originals, without executing or uploading it.
                            from app.monthly_report_sources import _path, MAX_SOURCES, MAX_REPORT_TEXT
                            if len(contents) >= MAX_SOURCES or sum(len(t) for c in contents for t in c.source.page_texts) + len(pasted) > MAX_REPORT_TEXT:
                                raise ValueError("This report's source/text allowance is used. Remove unused sources before adding notes.")
                            library._atomic_write(_path(draft.profile, candidate.sha256, ".txt"), pasted.encode())
                            st.session_state[evidence_key] = (*contents, SourceContent(candidate))
                        st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
        sources = tuple(c.source for c in st.session_state.get(evidence_key, ()))
        draft = replace(draft, sources=sources)
        target = st.selectbox("Section to help write", list(LABELS), format_func=LABELS.get, key=prefix + "_ai_target")
        instruction = st.text_input("Optional redraft instruction", key=field(prefix + "_ai_instruction", ""), max_chars=2000)
        if st.button("Suggest wording / redraft", key=prefix + "_ai_draft", disabled=busy or not any(s.facts for s in sources)):
            try:
                key, content, facts = ai.drafting_request(target, sources, draft.period, ai.vendor_names(draft), draft.profile.asset_tags, instruction)
                saved = ai.cached(draft.profile, "draft", key)
                if saved is not None:
                    st.session_state[prefix + "_ai_suggestion"] = ai.normalize_draft(saved, target, facts, sources)
                else:
                    def prepare():
                        ai.reserve_call(draft.profile, draft.period)
                        return content
                    _start(prefix, draft, {"kind": "draft", "key": key, "block": target, "facts": facts,
                                          "source_fingerprints": tuple(s.fingerprint for s in sources)}, prepare)
            except ValueError as exc:
                st.warning(str(exc))
        suggestion = st.session_state.get(prefix + "_ai_suggestion")
        if suggestion:
            st.subheader("Check the suggested wording")
            st.caption("Nothing below replaces your report until you choose Add or Replace.")
            facts = {f.id: f for s in sources for f in s.facts}
            paragraphs, ready = [], True
            for n, paragraph in enumerate(suggestion.ai_paragraphs):
                text = st.text_area(f"Suggested paragraph {n+1}", key=field(prefix + "_ai_p_" + suggestion.fingerprint + str(n), paragraph.text), height=90)
                evidence = "\n".join(f"Page {facts[i].page}: {facts[i].quote}" for i in paragraph.fact_ids if i in facts)
                st.caption(evidence or "Source evidence is no longer available.")
                flags = tuple(f for f in paragraph.flags if "Unsupported number" not in f)
                if ai.numbers(text) - ai.numbers(evidence):
                    flags += ("Unsupported number: correct against the evidence",)
                for flag in flags:
                    st.warning(flag)
                checked = st.checkbox(f"I checked paragraph {n+1} against its source", key=prefix + "_ai_p_ok_" + ai.digest((text, evidence, flags)))
                ready &= checked and bool(text.strip()) and not ai.contains_price(text) and not any("Unsupported number" in f for f in flags)
                paragraphs.append(replace(paragraph, text=ai.clean_text(text), flags=flags))
            ready &= bool(paragraphs) and suggestion.ai_evidence_fingerprint == ai.evidence_fingerprint(sources, suggestion.references)
            existing = blocks.get(suggestion.key)
            st.text("Current wording:\n" + (existing.text if existing else "Nothing entered yet."))
            mode = st.radio("Use the checked suggestion", ["Add below existing wording", "Replace existing wording"], key=prefix + "_ai_apply_mode")
            if st.button("Use checked wording in this report", disabled=not ready, key=prefix + "_ai_apply"):
                revised = replace(suggestion, ai_paragraphs=tuple(paragraphs), text="\n".join("- " + p.text for p in paragraphs))
                if existing:
                    text = revised.text if mode.startswith("Replace") else "\n".join(t for t in (existing.text, revised.text) if t)
                    revised = replace(revised, text=text, asset_hashes=existing.asset_hashes, asset_captions=existing.asset_captions,
                                      rows=existing.rows, extra_tables=existing.extra_tables)
                blocks[revised.key] = ai.reviewed_block(revised, sources)
                draft = replace(draft, sections=tuple(replace(s, included=True) if any(b.key == revised.key for b in s.blocks) else s for s in draft.sections))
                st.session_state.pop(prefix + "_ai_suggestion", None)
                # Remove stale widget mirrors so the normal editor shows the accepted text.
                for key in list(st.session_state):
                    if key.startswith(prefix + "_edit_" + revised.key + "_text_"):
                        del st.session_state[key]
                st.success("Checked wording added. Existing pictures and tables were retained.")
    return draft, blocks
