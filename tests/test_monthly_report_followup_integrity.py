"""Carried identity and oversized reports keep real rows and delivered work."""
from dataclasses import replace
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_followups import seed_followups
from app.monthly_report_issues import canonical_issues, issue_visibility
from app.monthly_report_model import (
    ReportDraft, ReportFollowUp, ReportPeriod, ReportTable, ResolvedBlock,
    default_sections, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft
from tests.conftest import requires_libreoffice


def fixture(*, count=0, proposals=False):
    sections = tuple(s for s in default_sections()
                     if s.key in {"activity", "issues", "proposals"})
    rows = tuple((f"EF-{n:03}", f"Damper travel obstruction {n:03}") for n in range(count))
    blocks = [ResolvedBlock("activity_summary", "This month", text="Inspected intake filters."),
              ResolvedBlock("equipment_issues", "This month", extra_tables=(
                  ReportTable(("Asset", "Condition"), rows),) if rows else ())]
    if proposals:
        blocks.append(ResolvedBlock("proposals", "This month", rows=(
            ("Demo North", "Synthetic Airflow", "Replace damper actuator", "Pending"),
            ("Demo North", "Synthetic Balancing", "Balance fan SF-4", "Pending"))))
    return ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 11),
                       "Synthetic Reviewer", sections, tuple(blocks))


@pytest.mark.parametrize("edited", [False, True])
def test_carried_proposal_edit_never_reseeds_its_old_row(edited):
    draft = fixture(proposals=True)
    rows = seed_followups(draft)
    if edited:
        rows = (replace(rows[0], text=rows[0].text + "; include end-switch wiring"), rows[1])
    carried = new_month_draft(replace(draft, follow_ups=rows), ReportPeriod(2026, 12))
    assert len(carried.follow_ups) == 2
    assert len({item.key for item in carried.follow_ups}) == 2
    assert tuple(item.text for item in carried.follow_ups) == tuple(item.text for item in rows)
    again = new_month_draft(carried, ReportPeriod(2027, 1))
    assert tuple(item.key for item in again.follow_ups) == tuple(item.key for item in rows)


@pytest.mark.parametrize("identical_rows", [False, True])
def test_colliding_saved_proposals_do_not_reseed_legacy_table_rows(identical_rows):
    prior = fixture(proposals=True)
    if identical_rows:
        block = prior.blocks[-1]
        prior = replace(prior, blocks=(*prior.blocks[:-1],
                                      replace(block, rows=(block.rows[0], block.rows[0]))))
    original = seed_followups(prior)
    assert len(original) == 2
    # Both saved rows had the same legacy ID. Repairing that ID must not make
    # the still-present legacy source rows appear new.
    collided = tuple(replace(item, key="old-shared-key") for item in original)
    current = new_month_draft(replace(prior, follow_ups=collided), ReportPeriod(2026, 12))
    assert len(current.follow_ups) == 2
    assert len({item.key for item in current.follow_ups}) == 2
    assert tuple(item.text for item in current.follow_ups) == tuple(item.text for item in original)
    again = new_month_draft(current, ReportPeriod(2027, 1))
    assert tuple(item.key for item in again.follow_ups) == tuple(item.key for item in current.follow_ups)


def test_saved_one_of_two_identical_source_rows_does_not_hide_missing_twin():
    prior = fixture(proposals=True)
    block = prior.blocks[-1]
    prior = replace(prior, blocks=(*prior.blocks[:-1],
                                  replace(block, rows=(block.rows[0], block.rows[0]))))
    original = seed_followups(prior)
    current = new_month_draft(replace(prior, follow_ups=(original[0],)), ReportPeriod(2026, 12))
    assert len(current.follow_ups) == 2
    assert len({item.key for item in current.follow_ups}) == 2
    assert all(item.text == original[0].text for item in current.follow_ups)


def test_equal_wording_does_not_erase_separately_identified_proposals():
    draft = fixture()
    text = "Separate inspection pending."
    items = (ReportFollowUp("first-proposal", "proposal", text, "2026-11", status="pending"),
             ReportFollowUp("second-proposal", "proposal", text, "2026-11", status="pending"))
    carried = new_month_draft(replace(draft, follow_ups=items), ReportPeriod(2026, 12))
    assert tuple(item.key for item in carried.follow_ups) == ("first-proposal", "second-proposal")
    assert len(carried.follow_ups) == 2


def test_distinct_repeated_source_rows_keep_stable_occurrence_identity():
    draft = fixture(proposals=True)
    block = draft.blocks[-1]
    draft = replace(draft, blocks=(*draft.blocks[:-1], replace(block, rows=(block.rows[0], block.rows[0]))))
    carried = new_month_draft(draft, ReportPeriod(2026, 12))
    assert len(carried.follow_ups) == 2
    assert len({item.key for item in carried.follow_ups}) == 2
    again = new_month_draft(carried, ReportPeriod(2027, 1))
    assert tuple(item.key for item in again.follow_ups) == tuple(item.key for item in carried.follow_ups)


APP = '''
import streamlit as st
from app.monthly_report_followups import render_followups
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state["draft"] = render_followups(st.session_state["draft"], "integrity", field,
                                             category=st.session_state["category"])
'''


def render(draft, category="issue"):
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.session_state["category"] = category
    return app.run()


def test_saved_colliding_proposals_render_without_erasing_either_version(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = fixture()
    rows = (ReportFollowUp("same-key", "proposal", "First scoped repair", "2026-11", status="pending"),
            ReportFollowUp("same-key", "proposal", "Different scoped repair", "2026-11", status="pending"))
    draft = replace(draft, follow_ups=rows)
    library.save_snapshot(draft, expected_revision=0)
    restored = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    app = render(restored.draft, "proposal")
    assert not app.exception
    current = app.session_state["draft"]
    assert len({item.key for item in current.follow_ups}) == 2
    assert tuple(item.text for item in current.follow_ups) == tuple(item.text for item in rows)
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key,
                                         draft.period, 1).draft == draft
    app.run()
    assert not app.exception and app.session_state["draft"].follow_ups == current.follow_ups


@requires_libreoffice
def test_edited_carried_proposals_save_reenter_and_print_once(monkeypatch, tmp_path):
    import json
    import os
    from hashlib import sha256
    from io import BytesIO
    from pathlib import Path
    import fitz
    from docx import Document
    from app.monthly_report_docx import generate_report

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    prior = fixture(proposals=True)
    rows = seed_followups(prior)
    rows = (replace(rows[0], text=rows[0].text + "; include end-switch wiring"), rows[1])
    prior = replace(prior, follow_ups=rows)
    library.save_snapshot(prior, expected_revision=0)
    prior_saved = library.load_snapshot(prior.profile.contract, prior.profile.key, prior.period)
    current = new_month_draft(prior_saved.draft, ReportPeriod(2026, 12))
    # This output scenario contains only the carried proposal section. A new
    # month's otherwise-required Activity cannot reuse November's operations.
    current = replace(current, sections=tuple(replace(section, included=section.key == "proposals")
                                              for section in current.sections))
    app = render(current, "proposal")
    assert not app.exception
    assert len([b for b in app.button if b.label == "Confirm unchanged"]) == 2
    for key in [b.key for b in app.button if b.label == "Confirm unchanged"]:
        next(b for b in app.button if b.key == key).click().run()
        assert not app.exception
    current = app.session_state["draft"]
    saved = library.save_snapshot(current, expected_revision=0)
    restored = library.load_snapshot(current.profile.contract, current.profile.key, current.period)
    assert restored.revision == saved.revision == 1
    assert tuple(item.text for item in restored.draft.follow_ups) == tuple(item.text for item in rows)
    assert not render(restored.draft, "proposal").exception
    assert library.load_snapshot(prior.profile.contract, prior.profile.key, prior.period).draft == prior
    package = generate_report(restored.draft, acknowledged_fingerprint=restored.draft.fingerprint)
    assert package.docx and package.pdf, package.pdf_error
    doc = Document(BytesIO(package.docx))
    paragraphs = "\n".join(p.text for p in doc.paragraphs)
    for item in rows:
        assert paragraphs.count(item.text) == 1
    out = Path(os.environ.get("INDEPENDENT_OUTPUT", str(tmp_path)))
    out.mkdir(parents=True, exist_ok=True)
    (out / "carried_proposals.docx").write_bytes(package.docx)
    (out / "carried_proposals.pdf").write_bytes(package.pdf)
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        text = " ".join(" ".join(page.get_text().split()) for page in pdf)
        for item in rows:
            assert text.count(" ".join(item.text.split())) == 1
        for n, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(out / f"carried_proposals_page_{n}.png")
        pages = len(pdf)
    (out / "carried_proposals.json").write_text(json.dumps({
        "source_sha": os.environ.get("MSAPO_SHA"), "fixture": "synthetic prior-month proposal rows",
        "original_fingerprint": prior.fingerprint, "saved_fingerprint": restored.draft.fingerprint,
        "saved_revision": restored.revision, "pages": pages,
        "docx_bytes": len(package.docx), "docx_sha256": sha256(package.docx).hexdigest(),
        "pdf_bytes": len(package.pdf), "pdf_sha256": sha256(package.pdf).hexdigest(),
        "renderer": "LibreOffice in isolated runtime; not native Microsoft Word",
    }, indent=2))


@pytest.mark.parametrize("count", [199, 200, 201, 205])
def test_issue_limit_is_a_preflight_condition_not_a_load_exception(count):
    original = fixture(count=count)
    current = canonical_issues(original)
    assert len(current.follow_ups) == count
    assert len(original.blocks[1].extra_tables[0].rows) == count
    limits = [check for check in preflight(current) if check.code == "follow_up_limit" and check.blocking]
    assert bool(limits) == (count > 200)
    if count > 200:
        assert limits[0].block_key == "equipment_issues"
        with pytest.raises(ValueError, match="200"):
            assemble_docx(current, acknowledged_fingerprint=current.fingerprint)
        for item in current.follow_ups[200:]:
            current = issue_visibility(current, item.key, False)
        assert len(current.follow_ups) == count
        assert not [check for check in preflight(current) if check.code == "follow_up_limit"]


def test_large_issue_editor_pages_preserve_same_event_text_and_last_row():
    app = render(fixture(count=205))
    assert not app.exception
    fields = [w for w in app.text_area if w.label == "Issue description"]
    assert 1 <= len(fields) <= 25, "Large lists must not mount every business editor."
    fields[0].set_value("EF-000 remains locked out pending review.")
    next(w for w in app.selectbox if w.label == "Issue page").set_value(9).run()
    assert not app.exception
    assert app.session_state["draft"].follow_ups[0].text == "EF-000 remains locked out pending review."
    assert any("EF-204" in w.value for w in app.text_area if w.label == "Issue description")
    next(w for w in app.selectbox if w.label == "Issue page").set_value(1).run()
    assert next(w for w in app.text_area if w.label == "Issue description").value == "EF-000 remains locked out pending review."


def test_saved_oversize_report_keeps_activity_save_reload_and_actions(monkeypatch, tmp_path):
    from app import monthly_report_guided as guided, monthly_report_section_preview_ui as previews
    from app.contracts import RRH_CONTRACT
    from test_monthly_report_ui import ROOT, choose_report

    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(guided, "operator_today", lambda tz: date(2026, 12, 7))
    monkeypatch.setattr(previews, "render_section_preview", lambda *a, **kw: None)
    draft = fixture(count=205)
    profile = replace(draft.profile, contract=RRH_CONTRACT, key="oversize-synthetic",
                      excluded_sections=tuple(s.key for s in default_sections() if s.key not in {"activity", "issues"}))
    library.save_profile(profile, expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    draft = replace(draft, profile=profile)
    library.save_snapshot(draft, expected_revision=0, entered_editor=draft.prepared_by)
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=40).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, profile.facilities[0].title)
    assert not app.exception
    assert any(b.label == "Create Word and PDF" for b in app.button)
    assert any(b.label == "Start this report over" for b in app.button)
    assert any("200" in w.value for w in (*app.warning, *app.error))
    # The guided workspace asks the current editor to identify themselves;
    # an author on an older saved version is not this session's preparer.
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Reviewer").run()
    edit = "The maintenance team found fan EF-205 still locked out."
    next(w for w in app.text_area if w.label == "Activity summary").set_value(edit).run()
    save = next(b for b in app.button if b.label == "Save shared version")
    assert not save.disabled
    save.click().run()
    assert not app.exception
    saved = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert saved.revision == 2
    assert next(b for b in saved.draft.blocks if b.key == "activity_summary").text == edit
    assert len(saved.draft.follow_ups) == 205
    reopened = AppTest.from_file(ROOT / "run_web.py", default_timeout=40).run()
    reopened.segmented_control[0].set_value("Monthly report").run()
    choose_report(reopened, profile.facilities[0].title)
    assert not reopened.exception
    assert next(w for w in reopened.text_area if w.label == "Activity summary").value == edit
    create = next(b for b in reopened.button if b.label == "Create Word and PDF")
    assert create.disabled


def test_explicit_whole_section_omission_excludes_its_rows_from_output_limit():
    current = canonical_issues(fixture(count=205))
    current = replace(current, sections=tuple(replace(section, included=False)
                      if section.key == "issues" else section for section in current.sections))
    assert len(current.follow_ups) == 205
    assert not [check for check in preflight(current) if check.code == "follow_up_limit"]


def test_add_issue_opens_the_page_containing_the_actual_new_row():
    app = render(fixture(count=30))
    next(b for b in app.button if b.label == "Add issue").click().run()
    assert not app.exception
    current = app.session_state["draft"]
    assert len(current.follow_ups) == 31
    assert next(w for w in app.selectbox if w.label == "Issue page").value == 2
    assert any(w.value == "" for w in app.text_area if w.label == "Issue description")


def test_detailed_editor_keeps_large_proposal_list_bounded_and_editable():
    draft = fixture()
    items = tuple(ReportFollowUp(f"proposal-{n}", "proposal", f"Repair scope {n}", "2026-11",
                                status="pending") for n in range(205))
    app = render(replace(draft, follow_ups=items), category=None)
    assert not app.exception
    fields = [w for w in app.text_area if w.label in ("Item to follow up", "Proposal scope")]
    assert len(fields) <= 25
    next(w for w in app.selectbox if w.label == "Proposal page").set_value(9).run()
    assert not app.exception and len(app.session_state["draft"].follow_ups) == 205
    next(b for b in reversed(app.button) if b.label == "Update proposal").click().run()
    assert any("Repair scope 204" == w.value for w in app.text_area)


@pytest.mark.parametrize("action", ["exclude", "remove_stale_link"])
def test_proposal_page_change_captures_delivered_explicit_choices(action):
    draft = fixture()
    items = tuple(ReportFollowUp(f"proposal-{n}", "proposal", f"Repair scope {n}", "2026-11",
                                status="pending", references=("missing-source:1:old",) if n == 0 else ())
                  for n in range(30))
    app = render(replace(draft, follow_ups=items), "proposal")
    label = "Leave this proposal out of the report" if action == "exclude" else "Remove unavailable source links"
    next(w for w in app.checkbox if w.label == label).set_value(True)
    next(w for w in app.selectbox if w.label == "Proposal page").set_value(2).run()
    assert not app.exception
    first = app.session_state["draft"].follow_ups[0]
    assert (not first.included) if action == "exclude" else (first.references == ())


@pytest.mark.parametrize("change", ["same_row", "source", "editor_reset"])
def test_late_proposal_choice_cannot_bind_to_changed_row_source_or_editor(change):
    from app.monthly_report_model import ReportSource
    draft = fixture()
    items = tuple(ReportFollowUp(f"proposal-{n}", "proposal", f"Repair scope {n}", "2026-11",
                                status="pending", references=("missing-source:1:old",))
                  for n in range(30))
    app = render(replace(draft, follow_ups=items), "proposal")
    next(w for w in app.checkbox if w.label == "Leave this proposal out of the report").set_value(True)
    current = app.session_state["draft"]
    if change == "same_row":
        current = replace(current, follow_ups=(replace(current.follow_ups[0], text="Concurrent corrected scope"),
                                               *current.follow_ups[1:]))
    elif change == "source":
        current = replace(current, sources=(ReportSource("new-source", "new.txt", "a" * 64, ".txt",
                                                         page_texts=("New source context",)),))
    else:
        app.session_state["integrity_rich_text_epoch"] = "different-report-editor-incarnation"
    app.session_state["draft"] = current
    next(w for w in app.selectbox if w.label == "Proposal page").set_value(2).run()
    assert not app.exception and app.session_state["draft"].follow_ups[0].included
    next(w for w in app.selectbox if w.label == "Proposal page").set_value(1).run()
    assert not next(w for w in app.checkbox if w.label == "Leave this proposal out of the report").value
    assert any("item changed" in w.value.lower() for w in app.warning)
