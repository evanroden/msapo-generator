"""The ordinary ordered workspace retains a report-only cover photograph path."""

from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

import pytest

from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_cover_ui import replace_cover_picture
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import ResolvedBlock, ReportDraft
from test_monthly_report_cover_ui import picture
from test_monthly_report_ui import ROOT, choose_report, monthly


def current(app):
    return next(value for key, value in app.session_state.filtered_state.items()
                if key.startswith("report_guided_") and key.endswith("_draft")
                and isinstance(value, ReportDraft))


def photo(draft):
    return next(block for block in draft.blocks if block.key == "cover_photo")


def button(app, label):
    return next(item for item in app.button if item.label == label)


def input_photo(monkeypatch):
    # AppTest has no file-upload setter. Keep the actual native uploader
    # mounted, supplying only its bytes at this one seam. All action/edit/save
    # widgets below are the ordinary run_web controls, not backend injection.
    incoming = {}
    from app import monthly_report_cover_ui as ui
    real_upload = ui.st.file_uploader
    def upload(label, *args, **kwargs):
        value = real_upload(label, *args, **kwargs)
        return incoming.get(label, value)
    monkeypatch.setattr(ui.st, "file_uploader", upload)
    return incoming


def standing(draft):
    """Fresh persisted bytes, including mtimes to catch identical rewrites."""
    paths = (library._profile_path(draft.profile.contract, draft.profile.key),
             library._profile_path(draft.profile.contract, draft.profile.key, snapshots=True))
    return {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
            for root in paths for path in root.rglob("*") if path.is_file()}


def loaded_cover(monkeypatch, tmp_path, *, omitted=False):
    initial = monthly(monkeypatch, tmp_path)
    draft = current(initial)
    assets = {}
    blocks = {block.key: block for block in draft.blocks}
    for slot, color in (("cover_photo", "navy"), ("client_logo", "green"), ("brand_logo", "red")):
        block = replace_cover_picture(ResolvedBlock(slot, "This month"), picture(color).getvalue(), ".png", assets)
        blocks[slot] = approve_all_assets(replace(block, references=("retained-" + slot,)))
    if omitted:
        blocks["cover_photo"] = replace(blocks["cover_photo"], source="Omit")
    draft = replace(draft, prepared_by="Synthetic Editor", blocks=tuple(blocks.values()),
                    address_line="Retained report address")
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()),
                                  entered_editor="Synthetic Editor")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, draft.profile.facilities[0].title)
    assert not app.exception
    return app, saved, assets


def test_loaded_ordinary_report_has_reachable_cover_photo_change(monkeypatch, tmp_path):
    app, saved, assets = loaded_cover(monkeypatch, tmp_path, omitted=True)
    assert photo(current(app)) == photo(saved.draft)
    before, persisted = current(app), standing(current(app))
    controls = [item for item in app.expander if item.label == "Change cover photograph"]
    assert len(controls) == 1, "The ordinary Cover section needs a reachable photo change path"
    assert not controls[0].proto.expanded
    assert [item.label for item in controls[0].get("file_uploader")] == ["New photograph for this report"]
    assert not any(item.label in ("Change cover photo", "Edit footer") for item in app.button)
    assert any('id="report-cover-photograph"' in item.value for item in app.markdown)
    for _ in range(2):
        app.run()
        assert not app.exception
        assert current(app) == before
        assert standing(before) == persisted
        assert all(library.read_asset(before.profile.contract, before.profile.key, ref) == raw
                   for ref, raw in assets.items())


def test_use_new_photo_is_explicit_and_preserves_same_submission_and_other_art(monkeypatch, tmp_path):
    incoming = input_photo(monkeypatch)
    app, saved, assets = loaded_cover(monkeypatch, tmp_path, omitted=True)
    before, persisted = current(app), standing(current(app))
    incoming["New photograph for this report"] = picture("purple")
    app.run()
    assert current(app) == before, "Choosing a file is not using it"
    assert standing(before) == persisted
    next(item for item in app.text_area if item.label == "Activity summary").set_value("Delivered alongside photograph.")
    button(app, "Use this photograph").click().run()
    assert not app.exception
    panel = next(item for item in app.expander if item.label == "Change cover photograph")
    assert not any(item.value == "No cover photograph in this report (optional)." for item in panel.caption)
    after = current(app)
    assert photo(after).source == "Replace once"
    assert photo(after).asset_hashes != photo(before).asset_hashes
    assert photo(after).references == () and pending_asset_indexes(photo(after)) == (0,)
    changed = {block.key: block for block in after.blocks}
    assert changed["activity_summary"].text == "Delivered alongside photograph."
    assert all(changed[block.key] == block for block in before.blocks
               if block.key not in ("cover_photo", "activity_summary"))
    assert after.profile == before.profile and after.address_line == before.address_line
    assert after.sources == before.sources
    assert standing(before) == persisted
    assert all(library.read_asset(before.profile.contract, before.profile.key, ref) == raw
               for ref, raw in assets.items())


def test_same_photo_keeps_reviews_and_no_photo_retains_originals_without_native_output(monkeypatch, tmp_path):
    incoming = input_photo(monkeypatch)
    app, saved, assets = loaded_cover(monkeypatch, tmp_path)
    before, persisted = current(app), standing(current(app))
    incoming["New photograph for this report"] = picture()
    app.run()
    old_omit = button(app, "No cover photograph")
    button(app, "Use this photograph").click().run()
    assert not app.exception
    assert photo(current(app)) == photo(before)
    app.run()
    assert button(app, "No cover photograph").key != old_omit.key
    old_omit.click().run()
    assert photo(current(app)) == photo(before), "Old native actions cannot rebind after an identical replacement"
    button(app, "No cover photograph").click().run()
    assert not app.exception
    panel = next(item for item in app.expander if item.label == "Change cover photograph")
    assert any(item.value == "No cover photograph in this report (optional)." for item in panel.caption)
    omitted = current(app)
    assert photo(omitted) == replace(photo(before), source="Omit")
    assert standing(before) == persisted
    assert all(library.read_asset(before.profile.contract, before.profile.key, ref) == raw
               for ref, raw in assets.items())
    output = replace(omitted, prepared_by="Synthetic Editor")
    raw = assemble_docx(output, acknowledged_fingerprint=output.fingerprint,
                        asset_loader=lambda ref: assets[ref])
    with ZipFile(BytesIO(raw)) as package:
        media = [package.read(name) for name in package.namelist() if name.startswith("word/media/")]
    assert assets[photo(before).asset_hashes[0]] not in media
    assert all(assets[block.asset_hashes[0]] in media for block in output.blocks
               if block.key in ("client_logo", "brand_logo"))


@pytest.mark.parametrize("change", ["source", "reset"])
def test_old_native_use_cannot_apply_another_upload_or_editor_incarnation(monkeypatch, tmp_path, change):
    incoming = input_photo(monkeypatch)
    app, saved, assets = loaded_cover(monkeypatch, tmp_path)
    incoming["New photograph for this report"] = picture("purple")
    app.run()
    old_use = button(app, "Use this photograph")
    before = current(app)
    if change == "source":
        incoming["New photograph for this report"] = picture("orange")
    else:
        epoch = next(key for key in app.session_state.filtered_state if key.endswith("_rich_text_epoch"))
        app.session_state[epoch] = "new-report-incarnation"
    app.run()
    assert button(app, "Use this photograph").key != old_use.key
    if change == "reset":
        # The held native button's old ElementTree also contains retired text
        # fields. AppTest cannot marshal those removed keys, before any app code
        # runs. Deliver its ACTUAL old native ID with the CURRENT other widget
        # states, rather than changing the click or calling a Python callback.
        old_use.click()
        packet = app._tree.get_widget_states()
        packet.widgets.append(old_use._widget_state)
        app._run(packet)
    else:
        old_use.click().run()
    assert not app.exception
    assert photo(current(app)) == photo(before)
    button(app, "Use this photograph").click().run()
    assert not app.exception
    assert photo(current(app)).asset_hashes != photo(before).asset_hashes


def test_unreadable_replacement_does_not_discard_current_photo(monkeypatch, tmp_path):
    incoming = input_photo(monkeypatch)
    app, saved, assets = loaded_cover(monkeypatch, tmp_path)
    before, persisted = current(app), standing(current(app))
    raw = BytesIO(b"not an image")
    raw.name, raw.size = "broken.png", len(raw.getvalue())
    incoming["New photograph for this report"] = raw
    app.run()
    button(app, "Use this photograph").click().run()
    assert not app.exception
    assert any("could not be read" in item.value for item in app.error)
    assert current(app) == before
    assert standing(before) == persisted


def test_explicit_shared_save_reopens_report_photo_without_changing_standing_slot(monkeypatch, tmp_path):
    incoming = input_photo(monkeypatch)
    app, saved, assets = loaded_cover(monkeypatch, tmp_path, omitted=True)
    profile = library.load_profile(saved.draft.profile.contract, saved.draft.profile.key)
    incoming["New photograph for this report"] = picture("purple")
    app.run()
    button(app, "Use this photograph").click().run()
    next(item for item in app.text_input if item.label == "Prepared by").set_value("Synthetic Editor").run()
    selected = photo(current(app))
    assert library.load_snapshot(profile.profile.contract, profile.profile.key, saved.draft.period) == saved
    button(app, "Save shared version").click().run()
    assert not app.exception
    latest = library.load_snapshot(profile.profile.contract, profile.profile.key, saved.draft.period)
    assert latest.revision == saved.revision + 1 and photo(latest.draft) == selected
    assert library.load_profile(profile.profile.contract, profile.profile.key) == profile
    assert all(library.read_asset(profile.profile.contract, profile.profile.key, ref) == raw
               for ref, raw in assets.items())
    incoming.clear()
    other = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    other.segmented_control[0].set_value("Monthly report").run()
    choose_report(other, saved.draft.profile.facilities[0].title)
    assert not other.exception and photo(current(other)) == selected
