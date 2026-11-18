"""A78: the native AR editor uses the same included-section identity as Word/PDF.

Synthetic empty/filled 12, 10 and 8 section variants. No financial export
authorization and no source or persisted draft mutation.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import (
    ReportPeriod, ResolvedBlock, included_sections, optional_sections,
    synthetic_draft, synthetic_profiles,
)


APP = """
import streamlit as st
from app.monthly_report_receivable_ui import render_receivable_intake
draft = st.session_state["report"]
blocks = {block.key: block for block in draft.blocks}
draft, blocks = render_receivable_intake(draft, blocks, "synthetic_a78")
st.session_state["result_blocks"] = blocks
st.session_state["report"] = draft
"""


def _draft(excluded=(), *, filled=False, omit_ar=False, duplicate_ar=False):
    base = synthetic_draft(synthetic_profiles()[1], ReportPeriod(2026, 10))
    ar = optional_sections()[0]
    sections = (*base.sections[:9], ar, *base.sections[9:])
    sections = tuple(
        replace(s, included=False) if s.key in excluded or (omit_ar and s.key == "accounts_receivable")
        else s for s in sections
    )
    if duplicate_ar:
        sections = (*sections, ar)
    rows = (("Synthetic facility", "SYN-INV-1", "Awaiting review"),) if filled else ()
    blocks = (*base.blocks, ResolvedBlock("accounts_receivable", "This month", rows=rows))
    return replace(base, sections=sections, blocks=blocks)


@pytest.mark.parametrize("excluded,number,total", [
    ((), 10, 12),
    (("water", "training"), 9, 10),
    (("water", "issues", "proposals", "training"), 8, 8),
])
@pytest.mark.parametrize("filled", [False, True])
def test_native_editor_matches_actual_report_order_and_preserves_rows(excluded, number, total, filled):
    draft = _draft(excluded, filled=filled)
    selected = included_sections(draft.sections)
    assert len(selected) == total
    ar = [s for s in selected if s.key == "accounts_receivable"]
    assert len(ar) == 1 and (ar[0].number, ar[0].title) == (str(number), "Accounts Receivable")

    app = AppTest.from_string(APP)
    app.session_state["report"] = draft
    app.run()
    assert not app.exception
    captions = [c.value for c in app.caption]
    label = f"Section {number} — Accounts Receivable"
    assert any(c.startswith(label + " · Open invoices and AR Aging") for c in captions)
    if filled:
        assert f"Current {label} invoice status rows: 1" in captions
    else:
        assert not any("Current Section" in c for c in captions)
    if number != 10:
        assert all("Section 10" not in c for c in captions)
    assert app.session_state["report"] == draft
    assert app.session_state["result_blocks"]["accounts_receivable"].rows == (
        (("Synthetic facility", "SYN-INV-1", "Awaiting review"),) if filled else ()
    )


@pytest.mark.parametrize("missing,duplicate", [(True, False), (False, True)])
def test_missing_or_ambiguous_ar_section_never_claims_a_number(missing, duplicate):
    draft = _draft(omit_ar=missing, duplicate_ar=duplicate, filled=True)
    app = AppTest.from_string(APP)
    app.session_state["report"] = draft
    app.run()
    assert not app.exception
    captions = [c.value for c in app.caption]
    assert any(c.startswith("Accounts Receivable (not uniquely included) · Open invoices") for c in captions)
    assert not any(c.startswith("Section ") for c in captions)
    assert app.session_state["report"] == draft
