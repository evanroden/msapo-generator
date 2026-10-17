"""Delivered source page decisions survive the next metadata-owner render."""
from dataclasses import replace
from io import BytesIO

from app import monthly_report_upload_ui as ui
from app.monthly_report_guided import _current_source_detail
from app.monthly_report_model import ReportSource
from app.monthly_report_sources import SourceContent, source_bytes
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_upload_ui import (
    app_with_library, button, current_draft, reviewed_source, select,
)


def test_current_source_detail_requires_one_matching_original():
    old = ReportSource("original", "original.pdf", "original-sha", ".pdf")
    delivered = replace(old, client_page_reviews=((1, "reviewed-page"),))
    assert _current_source_detail(old, (SourceContent(delivered),)) == delivered
    for changed in (replace(delivered, id="other"), replace(delivered, sha256="other-sha"),
                    replace(delivered, suffix=".png")):
        assert _current_source_detail(old, (SourceContent(changed),)) == old
    assert _current_source_detail(old, (SourceContent(delivered), SourceContent(delivered))) == old
    assert _current_source_detail(old, ()) == old


def test_structured_source_review_decisions_survive_metadata_owner_and_reload(monkeypatch, tmp_path):
    from app import monthly_report_active_work as active, web_ui
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_ui import ROOT, choose_report
    token = "e" * 32
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: token)
    app, _ = app_with_library(monkeypatch, tmp_path)
    original = pdf_bytes(3)
    stream = BytesIO(original)
    stream.name = "synthetic-owner-order.pdf"
    uploader = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *args, **kwargs:
        [stream] if label == "Add source files" else uploader(label, *args, **kwargs))
    app.run()
    assert not app.exception
    select(app, "Classification").set_value("Vendor service").run()
    # Include explicitly reruns after storing the reviewed source but before
    # the full draft commit. A top metadata form must not restore its old copy.
    button(app, "Include page and continue").click().run()
    assert not app.exception
    assert 1 in dict(reviewed_source(app).client_page_reviews)
    assert select(app, "Preview page / item").value == 2
    button(app, "Leave page out and continue").click().run()
    assert 2 in dict(reviewed_source(app).client_page_exclusions)
    assert select(app, "Preview page / item").value == 3
    next(widget for widget in app.text_input if widget.label == "Page caption").set_value("Reviewed third page")
    button(app, "Include page and continue").click().run()
    source = reviewed_source(app)
    assert set(dict(source.client_page_reviews)) == {1, 3}
    assert set(dict(source.client_page_exclusions)) == {2}
    assert dict(source.captions)[3] == "Reviewed third page"
    assert button(app, "Next page needing review").disabled
    button(app, "Add selected pages and tables to report").click().run()
    assert not app.exception
    draft = current_draft(app)
    pages = next(block for block in draft.blocks if block.key == "improvements")
    assert len(pages.asset_hashes) == len(set(pages.asset_hashes)) == 2
    assert pages.asset_captions[-1] == "Reviewed third page"
    assert draft.sources[0].client_page_reviews == source.client_page_reviews
    before = draft.fingerprint
    app.run()
    assert current_draft(app).fingerprint == before
    # Workflow return uses the ordinary retained native source state, not a
    # synthetic injected source snapshot.
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Monthly report").run()
    assert not app.exception
    assert current_draft(app).fingerprint == before
    assert source_bytes(draft.profile, source) == original
    durable = active.load(token, draft.profile.contract, draft.profile.key, draft.period)
    assert durable is not None and durable.draft.fingerprint == before
    monkeypatch.setattr(ui.st, "file_uploader", uploader)
    reloaded = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    reloaded.segmented_control[0].set_value("Monthly report").run()
    choose_report(reloaded, draft.profile.facilities[0].title)
    assert not reloaded.exception
    assert current_draft(reloaded).fingerprint == before
    assert current_draft(reloaded).sources[0].client_page_reviews == source.client_page_reviews
