"""Synthetic native AppTest proof of one mixed-source correction before paid reading."""
from hashlib import sha256
from io import BytesIO

from test_monthly_report_activity_intake_commit import setup_app, activity, draft


def test_mixed_vendor_proposal_page_needs_one_destination_before_reader(monkeypatch, tmp_path):
    import streamlit as st
    from app import monthly_report_sources as sources
    from app import monthly_report_ai as ai
    app, profile = setup_app(monkeypatch, tmp_path)
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "test-key-not-used")
    raw = (b"Vendor service report\nProposal quotation\n"
           b"Inspected synthetic pump. A replacement was recommended, not completed.\n")
    original_upload = st.file_uploader

    def upload(label, *args, **kwargs):
        if label == "Add source files":
            stream = BytesIO(raw)
            stream.name = "synthetic-mixed-source.txt"
            return [stream]
        return original_upload(label, *args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", upload)
    before = activity(app)
    app.run()
    assert not app.exception
    assert activity(app).text == before.text  # An ambiguous page was not auto-Activity.
    assert not any(b.label == "Read selected files" for b in app.button)
    candidates = [w for w in app.selectbox if w.label == "Choose destination for this ambiguous page"]
    assert len(candidates) == 1
    assert any("conflicting page headings" in c.value for c in app.caption)
    assert any(s.sha256 == sha256(raw).hexdigest() for s in draft(app).sources)

    candidates[0].set_value("activity_summary").run()
    assert not app.exception
    assert any(b.label == "Read selected files" for b in app.button)
    assert sources.source_bytes(profile, next(s for s in draft(app).sources if s.sha256 == sha256(raw).hexdigest())) == raw
    assert activity(app).text == before.text  # Choosing an AI route never accepts its contents.
