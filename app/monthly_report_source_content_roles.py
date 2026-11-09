"""Source-bound review for explicitly marked template prose, not guessed facts."""
from __future__ import annotations

import hashlib
import json
import re

# Conservative cues in the actual paragraph, never filenames, dates, sample
# magnitudes, or ordinary prose mentioning an example or an inspection sample.
_INSTRUCTION = re.compile(
    r"^\s*(?:(?:author|editor|template)\s+(?:instructions?|notes?)\s*:"
    r"|this\s+(?:section|report)\s+should\s+include\b)", re.I | re.M)
_EXAMPLE = re.compile(
    r"^\s*(?:example|sample\s+(?:text|values?|dates?|entry|narrative))\s*:", re.I | re.M)
_PLACEHOLDER = re.compile(
    r"\[(?:insert|enter|replace|describe|add)\b[^\]\r\n]{1,160}\]"
    r"|^\s*(?:insert\s+(?:image|photo|text)|author\s*:\s*name|month\s+year)\s*[.!]?\s*$",
    re.I | re.M)


def text_role(text: str) -> str:
    if _PLACEHOLDER.search(text):
        return "Placeholder"
    if _INSTRUCTION.search(text):
        return "Author instruction"
    if _EXAMPLE.search(text):
        return "Example text"
    return ""


def source_text_role(item) -> str:
    # Cover titles and Organization's complete-page diagram path have separate
    # preservation/review rules. This bounded repair concerns narrative prose.
    return (text_role(item.text) if item.kind == "text"
            and item.section not in ("", "cover", "organization") else "")


def source_stamp(source_sha: str, item) -> str:
    # Include identity, placement and exact text. Old choices cannot approve a
    # replacement file, even when it reuses the same sequential item IDs.
    value = (source_sha, item.id, item.part, item.position, item.word_section,
             item.section, item.suggested_slot, item.text)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def validate_role_reviews(plan, items, source_sha):
    """Direct Starting Report builds enforce the same decisions as the UI."""
    if plan.get("omit"):
        return
    by_id = {item.id: item for item in items}
    selected = set(plan.get("selected", ()))
    combined = set(plan.get("combined_text_ids", ()))
    required = set(plan.get("content_role_required", ()))
    required.update(identity for identity in selected | combined
                    if identity in by_id and source_text_role(by_id[identity]))
    reviews = plan.get("content_role_reviews", {})
    for identity in required:
        item, receipt = by_id.get(identity), reviews.get(identity, {})
        if (item is None or not source_text_role(item)
                or receipt.get("stamp") != source_stamp(source_sha, item)
                or receipt.get("action") not in ("include", "exclude")):
            raise ValueError("Review the source instructions or examples again before continuing.")
        included = identity in selected | combined
        if receipt["action"] == "exclude":
            if included:
                raise ValueError("Excluded source instructions or examples cannot be included in report text.")
            continue
        # Ordinary reviews keep source paragraphs separate; a previously edited
        # aggregate is reviewed as a whole instead of attempting a lossy split.
        anchor = plan.get("combined_text_ids", ())[0] if identity in combined else identity
        text = plan.get("texts", {}).get(anchor, "")
        if (not included or text != receipt.get("text") or not text.strip() or text_role(text)):
            raise ValueError("Replace template instructions or examples with verified report wording, or leave them out.")


def render_role_texts(items, inspection, prefix, field, old, plan, blocking, *, editing):
    """Handle text only when this section has explicit source-role questions.

    Keep paragraphs separate so a source exclusion cannot discard a neighbor or
    mistake an old one-paragraph seed for the entire editable section.
    """
    texts = [item for item in items if item.kind == "text"]
    flagged = [item for item in texts if source_text_role(item)]
    if not flagged:
        return False
    import streamlit as st
    from app.monthly_report_content_policy import contains_price
    from app.monthly_report_ui_text import literal

    required = [item.id for item in flagged]
    plan["content_role_required"] = required
    plan["content_role_reviews"] = {}
    old_reviews = old.get("content_role_reviews", {})
    # Retain these cards after a completed choice so the writer can reverse it
    # before Continue. This is a review task, not an unresolved-error flag.
    plan["questions"] = ("Review source instructions or example text.",)

    def review(label, originals, initial, key):
        valid = all(old_reviews.get(item.id, {}).get("stamp") == source_stamp(inspection.sha256, item)
                    for item in originals)
        prior = old_reviews.get(originals[0].id, {}) if valid else {}
        choices = {"": "Choose how to use this text", "exclude": "Leave out of this report",
                   "include": "Use verified report wording"}
        choice = st.radio(label, tuple(choices), format_func=choices.get,
                          key=field(key + "_choice", prior.get("action", "")))
        text = st.session_state.get(key + "_text", prior.get("text", initial))
        if choice == "include":
            text = st.text_area("Verified report wording", key=field(key + "_text", text))
            if not text.strip() or text_role(text):
                blocking.append("Replace the instruction, placeholder or example with verified report wording, or leave it out.")
            if contains_price(text):
                blocking.append("Remove pricing from the reviewed report wording.")
        elif not choice:
            blocking.append("Choose how to use the marked source text before continuing.")
        for item in originals:
            plan["content_role_reviews"][item.id] = {
                "stamp": source_stamp(inspection.sha256, item), "action": choice, "text": text,
            }
        return choice, text

    # A prior manually edited aggregate has no safe per-paragraph split. Show
    # all of that existing text for one explicit choice, rather than overwrite
    # it with the source or silently omit its unmarked neighboring paragraphs.
    aggregate = old.get("content_role_aggregate", {})
    if aggregate.get("source_sha256") != inspection.sha256:
        aggregate = {}
    combined = tuple(old.get("combined_text_ids", ())) or tuple(aggregate.get("ids", ()))
    if combined and set(combined).intersection(required):
        anchor = combined[0]
        initial = old.get("texts", {}).get(anchor, aggregate.get("text", "\n\n".join(item.text for item in texts)))
        st.caption("This previously edited text contains source-role questions. Review the whole text; it has not been split or cleared.")
        st.text(initial)
        key = prefix + "_role_combined_" + hashlib.sha256(
            (inspection.sha256 + "|".join(source_stamp(inspection.sha256, i) for i in texts)).encode()).hexdigest()
        choice, text = review("Use this edited section text", flagged, initial, key)
        plan["content_role_aggregate"] = {
            "source_sha256": inspection.sha256, "ids": list(combined), "text": text,
        }
        if choice == "include":
            plan["selected"].append(anchor)
            plan["texts"][anchor] = text
            plan["combined_text_ids"] = list(combined)
        return True

    # Previously reviewed paragraphs stay independently editable and keep
    # their exact source item references. No new dates or values are inferred.
    for number, item in enumerate(texts, 1):
        role = source_text_role(item)
        if (not role and old.get("automatic")
                and old.get("source_sha256") == inspection.sha256
                and item.id not in old.get("selected", ())
                and item.id not in old.get("combined_text_ids", ())
                and item.id not in old.get("period_review_items", ())):
            continue  # Do not resurrect earlier-month or deliberately omitted prose.
        key = prefix + "_role_" + source_stamp(inspection.sha256, item)
        if role:
            st.caption(literal(role) + " · source paragraph " + str(number))
            st.text(item.text)
            choice, text = review("Use source paragraph " + str(number), [item], item.text, key)
            if choice != "include":
                continue
        else:
            text = st.session_state.get(key + "_normal", old.get("texts", {}).get(item.id, item.text))
            if editing:
                text = st.text_area("Report paragraph " + str(number), key=field(key + "_normal", text))
            else:
                st.text(text)
            if contains_price(text):
                blocking.append("Remove pricing from the report text before continuing.")
        plan["selected"].append(item.id)
        plan["texts"][item.id] = text
        if item.id in old.get("destinations", {}):
            plan["destinations"][item.id] = old["destinations"][item.id]
    st.caption("Choices affect this import only. Original source text stays unchanged.")
    return True
