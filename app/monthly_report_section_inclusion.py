"""Reversible, report-owned whole-section inclusion choices."""
from dataclasses import replace


def set_section_included(draft, key, included):
    if type(included) is not bool or sum(s.key == key for s in draft.sections) != 1:
        raise ValueError("Choose one current report section.")
    omitted = set(draft.omitted_sections)
    if included:
        omitted.discard(key)
    else:
        omitted.add(key)
    return replace(draft,
        omitted_sections=tuple(s.key for s in draft.sections if s.key in omitted),
        sections=tuple(replace(s, included=included) if s.key == key else s for s in draft.sections))


def render_section_inclusion(draft, section, prefix, field):
    import streamlit as st
    included = st.checkbox(
        "Include " + section.title + " in this report", value=section.included,
        key=field(prefix + "_section_included_" + section.key, section.included),
        help="Uncheck a section that does not apply. Content is kept. Section and contents numbering update automatically.")
    # Render the old included section once more before applying a removal.
    # Native fields delivered with the checkbox click must reach their normal
    # collectors before those widgets disappear on the next rerun.
    return included
