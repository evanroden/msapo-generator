"""Synthetic regressions for PR273's remaining source privacy/meaning findings."""
from dataclasses import replace

import pytest

from app import monthly_report_structured_uploads as structured
from test_monthly_report_activity_wrap_integrity import ingest_lines


@pytest.mark.parametrize("contact", [
    "+44 20 7946 0958", "+49 (30) 1234-5678", "+61 2 1234 5678",
    "0044 20 7946 0958", "+442079460958",
])
def test_labelled_international_contact_is_removed_but_technical_value_is_kept(contact):
    action = "Inspected pump P-1; call " + contact + " for access."
    assert structured._activity_text(action) == (
        "Inspected pump P-1; call [contact omitted] for access.")
    identifier = "Inspected asset serial " + contact + "; unit remains offline."
    assert structured._activity_text(identifier) == identifier


@pytest.mark.parametrize("opening,tail", [
    ("Inspected pump P-1 and confirmed the", "unit remains offline."),
    ("Checked the actuator and found a", "failed limit switch."),
    ("Inspected pump P-1 and confirmed that", "isolation remains necessary."),
])
def test_short_qualifier_is_preserved_after_incomplete_line(monkeypatch, tmp_path, opening, tail):
    _, content = ingest_lines(monkeypatch, tmp_path, (opening, tail))
    assert structured.native_update((content,), "activity_summary").text == opening + " " + tail


@pytest.mark.parametrize("boundary", ["", "Fee $500", "Phone: +44 20 7946 0958",
                                     "- Replaced filter F-2", "Replaced filter F-2"])
def test_incomplete_line_does_not_consume_an_independent_boundary(boundary):
    opening = "Inspected pump P-1 and confirmed the"
    assert structured._logical_activity_lines((opening, boundary)) == tuple(
        text for text in (opening, boundary) if text)


@pytest.mark.parametrize("scan", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_contact_anywhere_on_page_prevents_automatic_original_inclusion(
        monkeypatch, tmp_path, scan, reverse):
    safe = "Inspected pump P-1 and confirmed the unit remains offline."
    contact = "Telephone: +44 20 7946 0958; synthetic@example.invalid"
    _, content = ingest_lines(monkeypatch, tmp_path, (safe, contact))
    if scan:
        content = replace(content, source=replace(content.source, page_texts=("",), needs_vision=(1,)))
    items = [
        {"source": content.source.id, "page": 1, "text": safe, "row": [], "include_page": True},
        {"source": content.source.id, "page": 1, "text": contact, "row": [], "include_page": False},
    ]
    if reverse:
        items.reverse()
    value = {"items": items, "visual_pages": [[content.source.id, 1]]}
    result, pages = structured.reader_update((content,), "activity_summary", value)
    assert result.text == safe
    assert not pages, "A clean narrative is not proof that the original page is private."
    assert structured.reader_page_notices((content,), "activity_summary", value)


def test_native_contact_elsewhere_on_page_blocks_clean_reader_passage(monkeypatch, tmp_path):
    safe = "Inspected pump P-1 and confirmed the unit remains offline."
    _, content = ingest_lines(monkeypatch, tmp_path, (safe, "Phone: 202-555-0176"))
    value = {"items": [{"source": content.source.id, "page": 1, "text": safe,
                        "row": [], "include_page": True}],
             "visual_pages": [[content.source.id, 1]]}
    result, pages = structured.reader_update((content,), "activity_summary", value)
    assert result.text == safe and not pages


def test_clean_technical_page_remains_eligible(monkeypatch, tmp_path):
    safe = "Inspected asset serial SN-202-555-0176; unit remains offline."
    _, content = ingest_lines(monkeypatch, tmp_path, (safe,))
    value = {"items": [{"source": content.source.id, "page": 1, "text": safe,
                        "row": [], "include_page": True}],
             "visual_pages": [[content.source.id, 1]]}
    result, pages = structured.reader_update((content,), "activity_summary", value)
    assert result.text == safe and pages == {content.source.id: {1}}
    assert not structured.reader_page_notices((content,), "activity_summary", value)


def test_cached_reader_explains_excluded_original_without_creating_assets(monkeypatch, tmp_path):
    from io import BytesIO
    from app import monthly_report_ai as ai, monthly_report_sources as sources
    from app import monthly_report_upload_ui as ui
    from test_monthly_report_ui import monthly

    safe = "Inspected pump P-1 and confirmed the unit remains offline."
    profile, content = ingest_lines(monkeypatch, tmp_path, (safe, "Telephone: +44 20 7946 0958"))
    raw = sources.source_bytes(profile, content.source)
    app = monthly(monkeypatch, tmp_path)
    original = ui.st.file_uploader
    def upload(label, *args, **kwargs):
        if label == "Add activity files (optional)":
            stream = BytesIO(raw)
            stream.name = "synthetic-contact-service.pdf"
            return [stream]
        return original(label, *args, **kwargs)
    def cached(profile, kind, digest):
        if kind != "section_upload":
            return None
        return {"items": [{"source": content.source.id, "page": 1, "text": safe,
                            "row": [], "include_page": True}],
                 "visual_pages": [[content.source.id, 1]]}
    monkeypatch.setattr(ui.st, "file_uploader", upload)
    monkeypatch.setattr(ai, "cached", cached)
    monkeypatch.setattr(sources, "prepare_pages", lambda *args, **kwargs:
                        pytest.fail("Contact-bearing originals must not reach page preparation."))
    app.run()
    assert not app.exception
    app.run()
    assert not app.exception
    assert safe in next(w.value for w in app.text_area if w.label == "Activity summary")
    assert any("original page was left out" in w.value for w in app.warning)
    drafts = [v for k, v in app.session_state.filtered_state.items()
              if k.endswith("_draft") and hasattr(v, "sources")]
    assert len(drafts) == 1 and drafts[0].sources
    assert all(not source.client_page_reviews for source in drafts[0].sources)
    assert all(not block.asset_hashes for block in drafts[0].blocks)


@pytest.mark.parametrize("label", ["Technician", "Prepared by", "Contact", "Service engineer"])
def test_bare_number_with_contact_owner_does_not_make_original_page_safe(monkeypatch, tmp_path, label):
    safe = "Inspected the isolation valve and confirmed it remains closed."
    contact = label + ": Synthetic Person 2025550176"
    _, content = ingest_lines(monkeypatch, tmp_path, (safe, contact))
    assert structured._activity_text(contact) == label + ": Synthetic Person [contact omitted]"
    value = {"items": [{"source": content.source.id, "page": 1, "text": safe,
                        "row": [], "include_page": True}],
             "visual_pages": [[content.source.id, 1]]}
    result, pages = structured.reader_update((content,), "activity_summary", value)
    assert result.text == safe and not pages
    identifier = label + ": inspected asset serial 2025550176"
    assert structured._activity_text(identifier) == identifier


def test_same_action_edit_totals_and_new_source_keep_both_contributions(monkeypatch, tmp_path):
    from io import BytesIO
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    from test_monthly_report_activity_review_guards import workorder_app
    from test_monthly_report_activity_intake_commit import APP, activity, editor
    app, _, original_uploader = workorder_app(monkeypatch, tmp_path)
    workorder_uploader = st.file_uploader
    additional = b"Inspected synthetic generator G-37 and confirmed it remains offline."
    def upload(label, *args, **kwargs):
        files = workorder_uploader(label, *args, **kwargs)
        if label == "Add activity files (optional)":
            stream = BytesIO(additional)
            stream.name = "synthetic-additional-activity.txt"
            return [*files, stream]
        return files
    monkeypatch.setattr(st, "file_uploader", upload)
    manual = "  Operator confirmed the starter remains locked out.\n"
    editor(app).set_value(manual)
    next(b for b in app.button if b.label == "Add totals to summary").click().run()
    assert not app.exception
    expected = activity(app).text
    assert expected.startswith(manual + "\n\n")
    assert expected.count("2 total, 1 completed, 1 open") == 1
    assert expected.count(additional.decode()) == 1
    assert not any("earlier edit was interrupted" in w.value for w in app.warning)
    assert not any(b.label == "Apply interrupted edit" for b in app.button)
    assert editor(app).value == expected
    monkeypatch.setattr(st, "file_uploader", original_uploader)
    resumed = AppTest.from_string(APP, default_timeout=45).run()
    assert not resumed.exception
    assert activity(resumed).text == expected and editor(resumed).value == expected
    assert not any(b.label == "Apply interrupted edit" for b in resumed.button)
