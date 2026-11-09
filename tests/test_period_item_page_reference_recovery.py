"""Damaged saved page references cannot prevent explicit dated-text decisions."""
from dataclasses import replace
from io import BytesIO

import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock, SectionSpec,
    synthetic_profiles,
)
from app.monthly_report_period_items import HISTORICAL, item_sources, pending_items


PERIOD = ReportPeriod(2026, 10)
OLD = "September 16, 2026: inspected the synthetic pump."
CURRENT = "October 2, 2026: corrected the synthetic valve."
RAW = (OLD + "\n" + CURRENT).encode()
INVALID_PAGES = ("\u00b2", "\u2460", "\u0661", "\uff11", "0", "000000", "-1", "+1", "1.0", "1" * 5000)
INVALID_IDS = ("superscript", "circled", "arabic-indic", "fullwidth", "zero", "padded-zero", "negative", "signed", "decimal", "oversized")


def sample(page, source=None):
    profile = synthetic_profiles()[0]
    source = source or ReportSource("a" * 64, "synthetic-period-evidence.txt", "b" * 64,
                                    ".txt", page_texts=(RAW.decode(),))
    reference = f"{source.id}:{page}:{source.fingerprint}"
    block = ResolvedBlock("activity_summary", "This month", text=OLD + "\n" + CURRENT,
                          references=(reference,))
    section = SectionSpec("activity", "2", "Activity", (BlockSpec(block.key, "rich_text"),))
    return ReportDraft(profile, PERIOD, "Synthetic reviewer", (section,), (block,), sources=(source,))


@pytest.mark.parametrize("page", INVALID_PAGES, ids=INVALID_IDS)
def test_malformed_page_is_not_a_source_label_or_a_draft_rewrite(page):
    draft = sample(page)
    item = pending_items(draft.blocks[0], PERIOD, draft.sources)[0]
    assert item_sources(draft.blocks[0], item, draft.sources) == ()
    assert draft.blocks[0].references == (f"{draft.sources[0].id}:{page}:{draft.sources[0].fingerprint}",)
    assert draft.blocks[0].text == OLD + "\n" + CURRENT
    assert draft.sources[0].page_texts == (RAW.decode(),)


@pytest.mark.parametrize("page", ("1", "01", "000001"))
def test_valid_and_historically_padded_pages_keep_exact_source_label(page):
    draft = sample(page)
    item = pending_items(draft.blocks[0], PERIOD, draft.sources)[0]
    assert item_sources(draft.blocks[0], item, draft.sources) == ("synthetic-period-evidence.txt · page/item 1",)


def test_bad_page_does_not_hide_valid_sibling_or_label_unrelated_source():
    draft = sample("\u00b2")
    source = draft.sources[0]
    other = replace(source, id="c" * 64, filename="unrelated-period-evidence.txt")
    block = replace(draft.blocks[0], references=(*draft.blocks[0].references,
                    sources.source_reference(source, 1), "not-a-source:1:stamp"))
    item = pending_items(block, PERIOD, draft.sources)[0]
    assert item_sources(block, item, (*draft.sources, other)) == ("synthetic-period-evidence.txt · page/item 1",)
    assert source.page_texts == (RAW.decode(),)


APP = '''
import streamlit as st
from app.monthly_report_period_items_ui import render_period_items
draft = st.session_state['seed']
block = st.session_state.setdefault('canonical', draft.blocks[0])
st.session_state['canonical'] = render_period_items(block, draft.period, draft.sources,
    'damaged_period_probe', section_title='Activity', editor_anchor='activity-editor')
'''


def text(app):
    return app.session_state['canonical'].text


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception
    app.run()
    assert not app.exception


@pytest.mark.parametrize("page", ("\u00b2", "1" * 5000), ids=("superscript", "oversized"))
def test_visible_period_panel_retains_explicit_actions_and_authored_wording(page):
    draft = sample(page)
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state['seed'] = draft
    app.run()
    assert not app.exception
    assert text(app) == draft.blocks[0].text
    assert any(c.value == "No exact source passage linked." for c in app.caption)
    assert app.session_state['canonical'] == draft.blocks[0]

    click(app, "Leave out")
    assert text(app) == CURRENT
    app.run()
    assert text(app) == CURRENT
    click(app, "Restore this wording")
    assert OLD in text(app) and CURRENT in text(app)
    click(app, "Keep as history")
    assert HISTORICAL + OLD in text(app) and CURRENT in text(app)
    app.run()
    assert not any(button.label == "Keep as history" for button in app.button)

    assert app.session_state['seed'] == draft


@pytest.mark.parametrize("page", ("\u00b2", "1" * 5000), ids=("superscript", "oversized"))
def test_saved_reopened_period_panel_and_word_preserve_sources_and_history(monkeypatch, tmp_path, page):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    content, _ = sources.ingest(synthetic_profiles()[0], "synthetic-period-evidence.txt", RAW)
    draft = sample(page, content.source)
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic reviewer")
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, PERIOD)
    assert reopened == saved
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state['seed'] = reopened.draft
    app.run()
    assert not app.exception
    assert app.session_state['canonical'] == draft.blocks[0]
    click(app, "Keep as history")
    after = replace(draft, blocks=(app.session_state['canonical'],))
    updated = library.save_snapshot(after, expected_revision=saved.revision,
                                    entered_editor="Synthetic reviewer")
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, PERIOD) == updated
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, PERIOD, 1) == saved
    assert sources.source_bytes(draft.profile, draft.sources[0]) == RAW
    assert draft.sources == after.sources
    assert draft.blocks[0].references[0] in after.blocks[0].references

    # Actual generic Word assembly: report wording survives, internal reference
    # tokens do not print. This is not served/native-design/PDF acceptance.
    document = Document(BytesIO(_build_docx(after)))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert HISTORICAL + OLD in text and CURRENT in text
    assert draft.blocks[0].references[0] not in text
