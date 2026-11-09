"""Synthetic source paragraphs must survive Starting-report narrative merges."""
from dataclasses import asdict, replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_ai as ai
from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_guided import _edited_rich_text
from app.monthly_report_import import ImportMapping, imported_draft, inspect_docx, map_items
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_native_layout import build_native_docx
from app.monthly_report_preview import section_preview_docx
from app.monthly_report_setup import merge_blocks
from app.monthly_report_start_replay import merge_starting_drafts
from tests.conftest import requires_libreoffice


PERIOD = ReportPeriod(2026, 11)
KEY = "utility_analysis"
INCOMING = "The steam pressure is 13 psi."
EXISTING = (
    "The earlier statement “The steam pressure is 13 psi.” was retracted; "
    "the verified pressure is 113 psi."
)


@pytest.fixture(autouse=True)
def isolated_synthetic_data(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))

    def forbidden(*args, **kwargs):
        pytest.fail("A native narrative import must not make a model call")

    monkeypatch.setattr(ai, "reserve_call", forbidden)
    monkeypatch.setattr(ai, "request_json", forbidden)


def block(text, reference="manual:existing"):
    return ResolvedBlock(KEY, "This month", text=text, references=(reference,))


def item(draft):
    return next(value for value in draft.blocks if value.key == KEY)


def with_block(draft, updated):
    return replace(draft, blocks=tuple(updated if value.key == KEY else value
                                       for value in draft.blocks))


def word_source(tmp_path, name, paragraphs):
    document = Document()
    document.add_heading(synthetic_profiles()[0].facilities[0].title, 0)
    document.add_paragraph("Monthly Report · November 2026")
    document.add_heading("3 Monthly Scorecards", 1)
    for text in paragraphs:
        document.add_paragraph(text)
    path = tmp_path / name
    document.save(path)
    return path


def import_word(path, paragraphs):
    inspection = inspect_docx(path)
    selected = tuple(ImportMapping(value.id, KEY) for value in inspection.items
                     if value.kind == "text" and value.text in paragraphs)
    assert len(selected) == len(paragraphs), "Every synthetic body paragraph must be mapped"
    mapped = map_items(path, inspection, selected)
    return imported_draft(synthetic_profiles()[0], PERIOD, "Synthetic reviewer", mapped)


def source_pair(tmp_path, existing=EXISTING):
    first = word_source(tmp_path, "synthetic-existing.docx", (existing,))
    second = word_source(tmp_path, "synthetic-addition.docx", (INCOMING,))
    return (first, second), (import_word(first, (existing,)), import_word(second, (INCOMING,)))


def paragraphs(raw):
    return [value.text for value in Document(BytesIO(raw)).paragraphs]


@pytest.mark.parametrize("existing,incoming", [
    pytest.param(EXISTING, INCOMING, id="inline-retracted-quotation"),
    pytest.param("Unverified: " + INCOMING, INCOMING, id="inline-prefix"),
    pytest.param(INCOMING + " This reading was withdrawn.", INCOMING, id="inline-suffix"),
    pytest.param("The measured pressure is 113 psi.", "13 psi.", id="partial-numeric-word"),
    pytest.param("Operator note\n" + INCOMING, INCOMING, id="soft-line-prefix"),
    pytest.param(INCOMING + "\nThe earlier reading was withdrawn.", INCOMING, id="soft-line-suffix"),
    pytest.param("Quoted: First reading\nSecond reading", "First reading\nSecond reading",
                 id="multiline-partial-first-line"),
    pytest.param("First reading\nSecond reading was withdrawn.", "First reading\nSecond reading",
                 id="multiline-partial-last-line"),
    pytest.param("Earlier [P-2] (13 psi).* was withdrawn.", "[P-2] (13 psi).*",
                 id="literal-punctuation"),
    pytest.param("First reading\n\nSecond reading", "Second reading\n\nFirst reading",
                 id="contribution-order-is-significant"),
    pytest.param("First reading\n\nSecond reading", "First reading\n\nFirst reading",
                 id="contribution-multiplicity-is-significant"),
])
def test_inline_or_partial_contribution_is_appended_without_editing_either_input(existing, incoming):
    before, addition = block(existing), block(incoming, "manual:incoming")
    originals = asdict(before), asdict(addition)
    merged = merge_blocks(before, addition)
    assert merged.text == existing + "\n\n" + incoming
    assert merged.references == ("manual:existing", "manual:incoming")
    assert (asdict(before), asdict(addition)) == originals


@pytest.mark.parametrize("existing,incoming,duplicate", [
    pytest.param("A" * 2048, "A" * 1024, False, id="large-word-internal-overlaps"),
    pytest.param("AA\n\n" * 512, ("AA\n\n" * 256) + "A", False,
                 id="large-valid-left-invalid-right-overlaps"),
    pytest.param("X A\n\nA\n\nA", "A\n\nA", True,
                 id="later-overlap-after-invalid-left"),
    pytest.param("AA\n\nAA\n\nAA\n\nA", "AA\n\nA", True,
                 id="later-overlap-after-invalid-right"),
])
def test_repeated_patterns_retain_every_later_overlapping_candidate(existing, incoming, duplicate):
    before, addition = block(existing), block(incoming, "manual:incoming")
    originals = asdict(before), asdict(addition)
    merged = merge_blocks(before, addition)
    assert merged.text == (existing if duplicate else existing + "\n\n" + incoming)
    assert merged.references == ("manual:existing", "manual:incoming")
    assert (asdict(before), asdict(addition)) == originals
    assert merge_blocks(merged, addition) == merged


@pytest.mark.parametrize("existing,incoming", [
    pytest.param(INCOMING, INCOMING, id="entire-block"),
    pytest.param(INCOMING + "\n\nAnother measurement.", INCOMING, id="first-contribution"),
    pytest.param("Earlier measurement.\n\n" + INCOMING + "\n\nLater measurement.", INCOMING,
                 id="middle-contribution"),
    pytest.param("Earlier measurement.\n\n" + INCOMING, INCOMING, id="last-contribution"),
    pytest.param("Earlier.\n\nFirst\nsoft continuation\n\nSecond\n\nLater.",
                 "First\nsoft continuation\n\nSecond", id="contiguous-multiline-contribution"),
    pytest.param(EXISTING + "\n\n" + INCOMING, INCOMING, id="valid-later-occurrence"),
    pytest.param("Earlier.\n \t\n  " + INCOMING + "  \n\nLater.", " \t" + INCOMING + " \n",
                 id="surrounding-whitespace"),
    pytest.param("Earlier.\r\n\r\nFirst\r\ncontinuation\r\n\r\nLater.",
                 "First\r\ncontinuation", id="literal-crlf-contribution"),
])
def test_whole_contiguous_contribution_remains_idempotent(existing, incoming):
    merged = merge_blocks(block(existing), block(incoming, "manual:incoming"))
    assert merged.text == existing
    assert merge_blocks(merged, block(incoming, "manual:incoming")) == merged


def test_surrounding_spaces_remain_idempotent_after_another_append():
    first = merge_blocks(block("Initial reading."), block(" A ", "manual:a"))
    second = merge_blocks(first, block("B", "manual:b"))
    assert second.text == "Initial reading.\n\n A \n\nB"
    assert merge_blocks(second, block(" A ", "manual:a")) == second


def test_different_internal_newline_spelling_is_preserved_as_new_content():
    before = block("First reading\nSecond reading")
    addition = block("First reading\r\nSecond reading", "manual:incoming")
    assert merge_blocks(before, addition).text == before.text + "\n\n" + addition.text


@pytest.mark.parametrize("empty", ["", " \t\n", "\r\n"])
def test_empty_incoming_text_does_not_clear_or_rewrite_existing_text(empty):
    assert merge_blocks(block("  Authored text.\r\n"), block(empty, "manual:incoming")).text == "  Authored text.\r\n"


def test_new_paragraph_invalidates_review_but_exact_replay_retains_it():
    before = block(EXISTING)
    before = replace(before, reviewed_fingerprint=before.fingerprint,
                     client_reviewed_fingerprint=before.fingerprint)
    merged = merge_blocks(before, block(INCOMING, "manual:incoming"))
    assert merged.text == EXISTING + "\n\n" + INCOMING
    assert merged.reviewed_fingerprint == merged.client_reviewed_fingerprint == ""
    accepted = replace(merged, reviewed_fingerprint=merged.fingerprint,
                       client_reviewed_fingerprint=merged.fingerprint)
    assert merge_blocks(accepted, accepted) == accepted
    assert before.reviewed_fingerprint == before.client_reviewed_fingerprint == before.fingerprint


@pytest.mark.parametrize("renderer", ["compatibility", "native"])
def test_actual_starting_docx_merge_preserves_new_paragraph_in_both_word_routes(tmp_path, renderer):
    paths, drafts = source_pair(tmp_path)
    originals = tuple(path.read_bytes() for path in paths)
    snapshots = tuple(asdict(draft) for draft in drafts)
    merged = merge_starting_drafts(*drafts)
    assert not preflight(merged)
    raw = (assemble_docx(merged, acknowledged_fingerprint=merged.fingerprint)
           if renderer == "compatibility" else build_native_docx(merged, paths[0], section_key="scorecards"))
    output = paragraphs(raw)
    assert output.count(EXISTING) == 1
    assert output.count(INCOMING) == 1, "The incoming source paragraph must exist independently in Word"
    assert item(merged).references == (*item(drafts[0]).references, *item(drafts[1]).references)
    assert tuple(path.read_bytes() for path in paths) == originals
    assert tuple(asdict(draft) for draft in drafts) == snapshots
    assert merge_starting_drafts(merged, drafts[1]) == merged


@pytest.mark.parametrize("decision", ["edit", "clear", "omit", "remove"])
def test_acknowledged_source_replay_preserves_saved_manual_decisions_and_history(tmp_path, decision):
    paths, (existing, incoming) = source_pair(tmp_path)
    originals = tuple(path.read_bytes() for path in paths)
    combined = merge_starting_drafts(existing, incoming)
    first = library.save_snapshot(combined, expected_revision=0, entered_editor="Synthetic reviewer")
    if decision == "remove":
        edited = replace(combined, blocks=())
    else:
        current = item(combined)
        changed = (replace(current, source="Omit") if decision == "omit"
                   else _edited_rich_text(current, "Operator corrected the pressure to 114 psi."
                                         if decision == "edit" else ""))
        edited = with_block(combined, changed)
    second = library.save_snapshot(edited, expected_revision=1, entered_editor="Synthetic reviewer")
    reopened = library.load_snapshot(edited.profile.contract, edited.profile.key, PERIOD)
    assert reopened == second
    assert merge_starting_drafts(reopened.draft, incoming, incoming) == edited
    assert library.load_snapshot_version(edited.profile.contract, edited.profile.key, PERIOD, 1) == first
    assert library.load_snapshot(edited.profile.contract, edited.profile.key, PERIOD) == second
    assert tuple(path.read_bytes() for path in paths) == originals


START_APP = '''
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_model import synthetic_profiles, ReportPeriod
from app.monthly_report_ui import _field
p = synthetic_profiles()[0]
state = library.load_profile(p.contract, p.key) if st.session_state.get("resume") else None
render_section_setup(p.contract, ReportPeriod(2026, 11), "Synthetic reviewer", _field,
                     state=state, identity=p)
'''

EDITOR_APP = '''
from dataclasses import replace
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_guided import _edit_content
from app.monthly_report_ui import _field
draft = st.session_state["draft"]
block = next(b for b in draft.blocks if b.key == "utility_analysis")
spec = next(b for s in draft.sections for b in s.blocks if b.key == block.key)
updated = _edit_content(spec, block, None, "narrative_merge", {}, _field,
                        text_label="Utility narrative")
st.session_state["draft"] = replace(draft, blocks=tuple(updated if b.key == block.key else b for b in draft.blocks))
if st.button("Save synthetic report"):
    saved = library.save_snapshot(st.session_state["draft"],
        expected_revision=st.session_state["revision"], entered_editor="Synthetic reviewer")
    st.session_state["revision"] = saved.revision
'''


def starting_app(resume=False):
    app = AppTest.from_string(START_APP, default_timeout=30)
    app.session_state["resume"] = resume
    app.run()
    assert not app.exception
    assert len(app.get("file_uploader")) >= 1
    button = next(value for value in app.button if value.label == "Continue to this month’s updates")
    assert not button.disabled, [value.value for value in app.info]
    button.click().run()
    assert not app.exception and not app.error
    profile = synthetic_profiles()[0]
    return app, library.load_imported_draft(profile.contract, profile.key)


def editor_app(draft, revision):
    app = AppTest.from_string(EDITOR_APP, default_timeout=30)
    app.session_state["draft"], app.session_state["revision"] = draft, revision
    app.run()
    assert not app.exception
    return app


@pytest.mark.parametrize("existing_text", [EXISTING, "A separate verified reading was 113 psi."],
                         ids=["inline-quotation-regression", "unrelated-paragraph-control"])
def test_real_starting_upload_then_native_edit_save_reopen_and_reimport(tmp_path, monkeypatch, existing_text):
    from app import monthly_report_section_ui as ui

    paths, _ = source_pair(tmp_path, existing_text)
    originals = tuple(path.read_bytes() for path in paths)
    selected = [0]
    native = ui.st.file_uploader

    def transported(label, *args, **kwargs):
        actual = native(label, *args, **kwargs)
        if label != "Starting report":
            return actual
        upload = BytesIO(originals[selected[0]])
        upload.name, upload.size = paths[selected[0]].name, len(upload.getvalue())
        return upload

    monkeypatch.setattr(ui.st, "file_uploader", transported)
    _, initial = starting_app()
    assert item(initial).text == existing_text
    first = library.save_snapshot(initial, expected_revision=0, entered_editor="Synthetic reviewer")
    selected[0] = 1
    start, combined = starting_app(resume=True)
    assert item(combined).text == existing_text + "\n\n" + INCOMING
    start.run()
    assert not start.exception and not start.error
    assert library.load_imported_draft(initial.profile.contract, initial.profile.key) == combined
    assert library.load_snapshot(initial.profile.contract, initial.profile.key, PERIOD) == first

    editor = editor_app(combined, first.revision)
    correction = existing_text + "\n\nOperator confirmed the new reading is 14 psi."
    next(value for value in editor.text_area if value.label == "Utility narrative").set_value(correction).run()
    next(value for value in editor.button if value.label == "Save synthetic report").click().run()
    assert not editor.exception and not editor.error
    saved = library.load_snapshot(initial.profile.contract, initial.profile.key, PERIOD)
    assert saved.revision == 2 and item(saved.draft).text == correction
    reopened = editor_app(saved.draft, saved.revision)
    reopened.run()
    assert reopened.session_state["draft"] == saved.draft
    _, replayed = starting_app(resume=True)
    assert item(replayed) == item(saved.draft)
    assert library.load_snapshot(initial.profile.contract, initial.profile.key, PERIOD) == saved
    assert library.load_snapshot_version(initial.profile.contract, initial.profile.key, PERIOD, 1) == first
    with pytest.raises(ValueError, match="Resolve required block"):
        assemble_docx(replayed, acknowledged_fingerprint=replayed.fingerprint)
    preview = paragraphs(section_preview_docx(replayed, "scorecards"))
    assert existing_text in preview
    assert "Operator confirmed the new reading is 14 psi." in preview
    assert INCOMING not in preview
    assert library.imported_original(initial.profile.contract, initial.profile.key).read_bytes() == originals[1]
    assert tuple(path.read_bytes() for path in paths) == originals


@requires_libreoffice
def test_real_native_pdf_retains_both_source_paragraphs(tmp_path, monkeypatch):
    import fitz
    from app import pdf_converter

    paths, drafts = source_pair(tmp_path)
    originals = tuple(path.read_bytes() for path in paths)
    merged = merge_starting_drafts(*drafts)
    assert not preflight(merged)
    raw = build_native_docx(merged, paths[0], section_key="scorecards")
    assert paragraphs(raw).count(INCOMING) == 1
    output = tmp_path / "synthetic-narrative-merge.docx"
    output.write_bytes(raw)
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    pdf = pdf_converter.convert_to_pdf(output).read_bytes()
    with fitz.open(stream=pdf, filetype="pdf") as document:
        text = " ".join(" ".join(page.get_text().split()) for page in document)
    assert EXISTING in text
    assert text.count(INCOMING) == 2, "The quoted wording and the independent paragraph must both remain"
    assert tuple(path.read_bytes() for path in paths) == originals
    if directory := os.environ.get("INDEPENDENT_OUTPUT"):
        target = Path(directory) / "narrative-merge"
        target.mkdir(parents=True, exist_ok=True)
        for path, original in zip(paths, originals):
            (target / path.name).write_bytes(original)
        (target / "synthetic-merged.docx").write_bytes(raw)
        (target / "synthetic-merged.pdf").write_bytes(pdf)
        (target / "manifest.json").write_text(json.dumps({
            "fixture": "synthetic independent narrative contributions", "source_unchanged": True,
            "source_sha256": [sha256(original).hexdigest() for original in originals],
            "docx_sha256": sha256(raw).hexdigest(), "pdf_sha256": sha256(pdf).hexdigest(),
            "word_independent_paragraphs": paragraphs(raw).count(INCOMING),
            "pdf_reading_occurrences": text.count(INCOMING), "model_calls": 0,
            "commit": os.environ.get("MSAPO_SHA", ""),
        }, indent=2))
