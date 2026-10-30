"""Actual isolated Monthly save/reopen for #490; AppTest is not native delivery."""
from io import BytesIO

from app import monthly_report_library as library
from app import monthly_report_qa_fixture as fixture
from app import monthly_report_sources as sources
from app import monthly_report_testing as testing
from app import monthly_report_upload_ui as uploads
from test_monthly_issue_page_gallery import synthetic_pdf
from test_monthly_report_qa_ui import ACTOR_COOKIE, visit
from test_monthly_report_upload_ui import button, current_draft


def test_gallery_path_saves_real_shared_version_and_reopens_exact_sources(monkeypatch, tmp_path):
    app = visit(monkeypatch, tmp_path)
    button(app, "Load known-value report").click().run()
    originals = {"alpha-equipment.pdf": synthetic_pdf("alpha", 5),
                 "beta-equipment.pdf": synthetic_pdf("beta", 2)}
    files = []
    for name, raw in originals.items():
        upload = BytesIO(raw)
        upload.name = name
        files.append(upload)
    native_upload = uploads.st.file_uploader
    monkeypatch.setattr(uploads.st, "file_uploader", lambda label, *args, **kwargs:
                        files if label == "Add source files" else native_upload(label, *args, **kwargs))
    opener = next((item for item in app.button if item.label == "Manage source files"), None)
    if opener:
        opener.click().run()
    app.run()
    button(app, "Done with source files").click().run()
    assert not app.exception
    before = current_draft(app)
    by_name = {source.filename: source for source in before.sources}
    assert set(by_name) == set(originals)
    wanted = (sources.source_reference(by_name["alpha-equipment.pdf"], 2),
              sources.source_reference(by_name["beta-equipment.pdf"], 1))
    next(box for box in app.checkbox if box.label ==
         "Include alpha-equipment.pdf · page 2 as issue evidence").check().run()
    next(choice for choice in app.selectbox if choice.label == "Source file to inspect").set_value(
        by_name["beta-equipment.pdf"].id).run()
    next(box for box in app.checkbox if box.label ==
         "Include beta-equipment.pdf · page 1 as issue evidence").check().run()
    assert not app.exception
    current = current_draft(app)
    assert current.follow_ups[0].references == wanted
    assert current.blocks == before.blocks and current.sources == before.sources
    assert not button(app, "Save shared version").disabled
    button(app, "Save shared version").click().run()
    assert not app.exception
    with testing.isolated(ACTOR_COOKIE):
        saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        assert saved.revision == 2 and saved.draft.follow_ups[0].references == wanted
        previous = library.load_snapshot_version(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD, 1)
        assert previous is not None and not previous.draft.sources
        for name, source in by_name.items():
            assert sources.source_bytes(saved.draft.profile, source) == originals[name]

    # A new Streamlit session reads normal saved state; no draft or widget
    # payload is seeded into session_state, and no replacement save is used.
    monkeypatch.setattr(uploads.st, "file_uploader", native_upload)
    fresh = visit(monkeypatch, tmp_path)
    restored = current_draft(fresh)
    assert restored.follow_ups[0].references == wanted
    assert restored.sources == saved.draft.sources and restored.blocks == saved.draft.blocks
    assert next(box for box in fresh.checkbox if box.label ==
                "Include alpha-equipment.pdf · page 2 as issue evidence").value
    assert not next(box for box in fresh.checkbox if box.label ==
                    "Include alpha-equipment.pdf · page 1 as issue evidence").value
