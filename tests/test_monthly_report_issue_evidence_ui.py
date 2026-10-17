"""One evidence area preserves issue links and the two section-asset scopes."""
from dataclasses import replace
from io import BytesIO

from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided
from app.monthly_report_model import ReportFollowUp, ReportSource, ResolvedBlock
from app.monthly_report_sources import source_reference
from test_monthly_report_issue_cards import draft_for
from test_monthly_report_sources import image_bytes


SCRIPT = '''
from dataclasses import replace
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_guided import _render_ordered_section
from app.monthly_report_issues import apply_issue_action
from app.monthly_report_ui import _field
draft = st.session_state["draft"]
section = draft.sections[0]
blocks = {block.key: block for block in draft.blocks}
specs = {spec.key: spec for spec in section.blocks}
draft, blocks = _render_ordered_section(draft, section, blocks, specs,
    SimpleNamespace(profile=draft.profile), "issue_evidence", st.session_state["assets"], _field)
st.session_state["draft"] = apply_issue_action(replace(draft, blocks=tuple(blocks.values())), "issue_evidence")
'''


def workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = draft_for("")
    source = ReportSource("inspection", "synthetic-inspection.pdf", "a" * 64, ".pdf",
                          page_texts=("Pump inspection.", "Valve inspection."))
    pump = ReportFollowUp("pump", "issue", "Pump vibration.", original.period.key,
                          update="Survey scheduled.", references=(source_reference(source, 1),))
    valve = ReportFollowUp("valve", "issue", "Valve seal.", original.period.key,
                           status="resolved", evidence_note="Inspection verified the repair.",
                           references=(source_reference(source, 2),))
    original = replace(original, sources=(source,), follow_ups=(pump, valve), blocks=(
        ResolvedBlock("equipment_issues", "This month", asset_hashes=("legacy-section-photo.png",),
                      asset_captions=("Section overview",)),
        ResolvedBlock("equipment_issues_evidence", "This month", asset_hashes=("native-evidence-page.png",),
                      asset_captions=("Inspection page",))))
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    app.session_state["draft"] = original
    app.session_state["assets"] = {reference: image_bytes() for block in original.blocks
                                    for reference in block.asset_hashes}
    app.run()
    assert not app.exception
    return app


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_display_uses_one_evidence_area_without_changing_issue_links_or_section_assets(monkeypatch, tmp_path):
    app = workspace(monkeypatch, tmp_path)
    before, assets = app.session_state["draft"], dict(app.session_state["assets"])
    evidence = [item for item in app.expander if item.label == "Evidence"]
    assert len(evidence) == 1 and evidence[0].proto.expanded
    assert len([item for item in evidence[0].text_area if item.label == "Issue update"]) == 2
    assert len(evidence[0].multiselect) == 2
    assert len(evidence[0].get("file_uploader")) == 2
    assert not any(item.label == "Add a supporting photo (optional)" for item in app.expander)
    assert len([item for item in evidence[0].expander
                if item.label == "Replace this section’s attached pages"]) == 1
    app.run()
    assert not app.exception
    assert app.session_state["draft"] == before
    assert app.session_state["assets"] == assets
    assert not list(tmp_path.rglob("*"))  # Opening/display performs no standing/shared save.


def test_delivered_evidence_edit_is_retained_when_issue_is_removed_in_the_same_packet(monkeypatch, tmp_path):
    app = workspace(monkeypatch, tmp_path)
    before = app.session_state["draft"]
    next(item for item in app.text_area if item.label == "Issue update").set_value(
        "Delivered survey result before leaving the issue out.")
    button(app, "Remove from this report").click().run()
    assert not app.exception
    removed = app.session_state["draft"]
    assert removed.follow_ups[0].update == "Delivered survey result before leaving the issue out."
    assert not removed.follow_ups[0].included
    assert removed.follow_ups[0].references == before.follow_ups[0].references
    assert removed.follow_ups[1] == before.follow_ups[1]
    assert removed.blocks == before.blocks and removed.sources == before.sources
    button(app, "Include again").click().run()
    app.run()
    assert not app.exception
    assert next(item for item in app.text_area if item.label == "Issue update").value == removed.follow_ups[0].update
    assert app.session_state["draft"].follow_ups[0].included


def test_explicit_section_photo_does_not_attach_to_an_issue_or_replace_evidence_pages(monkeypatch, tmp_path):
    app = workspace(monkeypatch, tmp_path)
    before = app.session_state["draft"]
    upload = BytesIO(image_bytes())
    upload.name = "synthetic-section-photo.png"
    uploader = guided.st.file_uploader
    monkeypatch.setattr(guided.st, "file_uploader", lambda label, *args, **kwargs:
        upload if label == "Photo to add to this section" else uploader(label, *args, **kwargs))
    app.run()
    button(app, "Add this photo").click().run()
    assert not app.exception
    current = app.session_state["draft"]
    photos = next(block for block in current.blocks if block.key == "equipment_issues")
    assert len(photos.asset_hashes) == 2
    assert photos.asset_hashes[0] == before.blocks[0].asset_hashes[0]
    assert photos.asset_captions == ("Section overview", "")
    assert next(block for block in current.blocks if block.key == "equipment_issues_evidence") == before.blocks[1]
    assert current.follow_ups == before.follow_ups and current.sources == before.sources
    assert all(reference in app.session_state["assets"] for reference in photos.asset_hashes)
