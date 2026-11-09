"""Damaged compressed logo uploads fail locally without changing saved artwork."""
from dataclasses import asdict
from io import BytesIO
import json
import struct
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
import zlib

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_start import design_seed, save_design_start
from test_monthly_report_branding import collection


ERROR = "The logo collection is not a readable, complete ZIP."


def _bundle(logos, assets, compression=ZIP_DEFLATED):
    stream = BytesIO()
    with ZipFile(stream, "w", compression=compression) as archive:
        archive.writestr("manifest.json", json.dumps({"schema": 1, "logos": [asdict(v) for v in logos]}))
        for ref, raw in assets.items():
            archive.writestr("assets/" + ref, raw)
    return stream.getvalue()


def _damaged(raw, target):
    """Keep ZIP metadata intact but set the member's first DEFLATE block to reserved type 3."""
    changed = bytearray(raw)
    with ZipFile(BytesIO(raw)) as archive:
        member = archive.getinfo(target)
        assert member.compress_type == ZIP_DEFLATED and member.compress_size > 0
        names = archive.namelist()
        name_size, extra_size = struct.unpack_from("<HH", raw, member.header_offset + 26)
        start = member.header_offset + 30 + name_size + extra_size
    changed[start] = 7
    result = bytes(changed)
    # Prove this is a real decoder fault, not a mocked exception or broken ZIP directory.
    with ZipFile(BytesIO(result)) as archive:
        assert archive.namelist() == names
        with pytest.raises(zlib.error):
            archive.read(target)
    return result


def _target(logos, target):
    return "manifest.json" if target == "manifest" else "assets/" + logos[0].asset


def _files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def saved(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    logos, assets = collection()
    state = branding.save_branding(logos, assets, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    profile = synthetic_profiles()[0]
    draft, draft_assets = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Editor")
    save_design_start(draft, draft_assets, actor="Synthetic Editor", confirmed=True)
    return state, draft, _files(library._root())


@pytest.mark.parametrize("target", ["manifest", "artwork"])
def test_invalid_deflate_member_uses_recoverable_bundle_error(target):
    logos, assets = collection()
    raw = _damaged(_bundle(logos, assets), _target(logos, target))
    before = bytes(raw)
    with pytest.raises(ValueError, match="not a readable, complete ZIP") as error:
        branding.inspect_bundle(raw)
    assert isinstance(error.value.__cause__, zlib.error)
    assert str(error.value) == ERROR
    assert raw == before


@pytest.mark.parametrize("compression", [ZIP_STORED, ZIP_DEFLATED])
def test_valid_collections_keep_exact_logo_bytes_and_mapping(compression):
    logos, assets = collection()
    raw = _bundle(logos, assets, compression)
    assert branding.inspect_bundle(raw) == (logos, assets)


@pytest.mark.parametrize("target", ["manifest", "artwork"])
def test_failed_inspection_retains_current_history_and_pinned_report_then_allows_retry(saved, target):
    state, draft, before = saved
    logos, assets = collection("blue")
    valid = _bundle(logos, assets)
    with pytest.raises(ValueError, match="not a readable, complete ZIP"):
        branding.inspect_bundle(_damaged(valid, _target(logos, target)))
    assert _files(library._root()) == before
    assert branding.load_branding() == state
    checked, images = branding.inspect_bundle(valid)
    with pytest.raises(ValueError):
        branding.save_branding(checked, images, expected_revision=1, actor="Synthetic Editor", confirmed=False)
    assert _files(library._root()) == before
    updated = branding.save_branding(checked, images, expected_revision=1, actor="Synthetic Editor", confirmed=True)
    assert updated.revision == 2 and updated.logos == logos
    assert branding.load_branding(1) == state
    assert library.load_imported_draft(draft.profile.contract, draft.profile.key) == draft
    for path, original in before.items():
        if path != "branding/manifest.json":
            assert (library._root() / path).read_bytes() == original
    with pytest.raises(library.RevisionConflict):
        branding.save_branding(checked, images, expected_revision=1, actor="Synthetic Editor", confirmed=True)
    assert branding.load_branding() == updated


@pytest.mark.parametrize("target", ["manifest", "artwork"])
def test_uploader_recovers_without_traceback_and_valid_retry_still_requires_review(saved, monkeypatch, target):
    import streamlit as st
    state, draft, before = saved
    logos, assets = collection("blue")
    valid = _bundle(logos, assets)
    source = {"raw": _damaged(valid, _target(logos, target))}
    original = st.file_uploader
    def upload(label, *args, **kwargs):
        if label == "Reviewed logo collection":
            return SimpleNamespace(getvalue=lambda: source["raw"])
        return original(label, *args, **kwargs)
    monkeypatch.setattr(st, "file_uploader", upload)
    app = AppTest.from_string('''
from app.monthly_report_branding_ui import render_branding
from app.monthly_report_ui import _field
render_branding(_field)
''', default_timeout=30).run()
    assert not app.exception
    assert [item.value for item in app.error] == [ERROR]
    assert not any(button.label == "Save shared logos" for button in app.button)
    assert _files(library._root()) == before
    source["raw"] = valid
    app.run()
    assert not app.exception and not app.error
    app.text_input("report_branding_actor").set_value("Synthetic Reviewer").run()
    assert next(button for button in app.button if button.label == "Save shared logos").disabled
    next(box for box in app.checkbox if box.label.startswith("I reviewed the logos")).check().run()
    next(button for button in app.button if button.label == "Save shared logos").click().run()
    assert not app.exception and branding.load_branding().revision == 2
    assert branding.load_branding(1) == state
    assert library.load_imported_draft(draft.profile.contract, draft.profile.key) == draft
    assert branding.read_logo(branding.load_branding().logos[0]) == assets[logos[0].asset]
    app.run()
    assert not app.exception and branding.load_branding().revision == 2


def test_unrelated_programming_errors_are_not_reclassified_as_bad_uploads(monkeypatch):
    logos, assets = collection()
    def bad_mapper(_):
        raise TypeError("synthetic programmer failure")
    monkeypatch.setattr(branding, "_logos", bad_mapper)
    with pytest.raises(TypeError, match="synthetic programmer failure"):
        branding.inspect_bundle(_bundle(logos, assets))
