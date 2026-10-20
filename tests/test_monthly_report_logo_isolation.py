"""Synthetic undecodable artwork must not block contract choice or repair."""

from dataclasses import asdict, replace
from io import BytesIO
import json
import struct
import zlib

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_library as library
from test_monthly_report_branding import collection, bundle


def undecodable_png():
    """Valid PNG framing/CRCs, invalid compressed pixel stream."""
    _, assets = collection()
    original = next(iter(assets.values()))
    result, cursor = bytearray(original[:8]), 8
    while cursor < len(original):
        length = struct.unpack(">I", original[cursor:cursor + 4])[0]
        kind = original[cursor + 4:cursor + 8]
        data = original[cursor + 8:cursor + 8 + length]
        if kind == b"IDAT":
            data = b"not a zlib pixel stream"
        result.extend(struct.pack(">I", len(data)) + kind + data
                      + struct.pack(">I", zlib.crc32(kind + data)))
        cursor += length + 12
    raw = bytes(result)
    with Image.open(BytesIO(raw)) as image:
        image.verify()
    with pytest.raises(OSError):
        with Image.open(BytesIO(raw)) as image:
            image.load()
    return raw


@pytest.fixture
def logos(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    values, assets = collection()
    good = replace(values[0], key="healthy", title="Healthy client", contracts=("Healthy Contract",))
    broken = replace(good, key="damaged", title="Damaged client", contracts=("Damaged Contract",),
                     asset=library.asset_reference(undecodable_png(), "png"))
    return good, broken, assets


def seed_legacy(logos, *, missing=False):
    good, broken, assets = logos
    # Seed a record accepted by the old verifier; the new writer must reject it.
    first = branding.save_branding((good,), assets, expected_revision=0,
                                  actor="Synthetic Editor", confirmed=True)
    current = replace(first, revision=2, logos=(broken, good))
    path = branding._path()
    encoded = library._json({"schema": 1, **asdict(current)})
    library._atomic_write(path / "manifest.json", encoded)
    library._atomic_write(path / "history" / "00000002.json", encoded)
    if not missing:
        library._atomic_write(path / "assets" / broken.asset, undecodable_png())
    return first, current


def test_bundle_rejects_png_with_valid_chunks_but_undecodable_pixels(logos):
    _, broken, _ = logos
    with pytest.raises(ValueError, match="could not be read"):
        branding.inspect_bundle(bundle((broken,), {broken.asset: undecodable_png()}))


def test_shared_save_rejects_undecodable_pixels_without_promoting_revision(logos):
    good, broken, assets = logos
    initial = branding.save_branding((good,), assets, expected_revision=0,
                                    actor="Synthetic Editor", confirmed=True)
    manifest = (branding._path() / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="could not be read"):
        branding.save_branding((broken,), {broken.asset: undecodable_png()}, expected_revision=1,
                              actor="Synthetic Editor", confirmed=True)
    assert branding.load_branding() == initial
    assert (branding._path() / "manifest.json").read_bytes() == manifest
    assert not (branding._path() / "history" / "00000002.json").exists()


CARDS = '''
from app.monthly_report_start_ui import choose_contract
from app.monthly_report_ui import _field
choose_contract('', _field)
'''


@pytest.mark.parametrize("missing", [False, True])
def test_bad_shared_logo_keeps_healthy_and_affected_contract_selectable(logos, missing):
    seed_legacy(logos, missing=missing)
    manifest = (branding._path() / "manifest.json").read_bytes()
    # Catalog additions use the real directory path; no mocked card supplier.
    from app import monthly_report_directory as directory
    for name in ("Healthy Contract", "Damaged Contract"):
        directory.save_directory(name, (directory.DirectorySite("synthetic", "Synthetic Site"),),
                                 expected_revision=0, actor="Synthetic Editor", confirmed=True)
    app = AppTest.from_string(CARDS, default_timeout=30).run()
    assert not app.exception
    assert any("could not be read" in w.value for w in app.warning)
    next(b for b in app.button if b.label == "Healthy client").click().run()
    assert not app.exception and app.session_state["report_contract"] == "Healthy Contract"
    next(b for b in app.button if b.label == "Change contract").click().run()
    next(b for b in app.button if b.label == "Damaged client").click().run()
    assert not app.exception and app.session_state["report_contract"] == "Damaged Contract"
    assert next(b for b in app.button if b.label == "Change contract")
    assert any("could not be read" in w.value for w in app.warning)
    assert (branding._path() / "manifest.json").read_bytes() == manifest


def test_bad_logo_preview_keeps_existing_history_restore_controls(logos):
    initial, current = seed_legacy(logos)
    damaged_bytes = (branding._path() / "assets" / logos[1].asset).read_bytes()
    app = AppTest.from_string('''
from app.monthly_report_branding_ui import render_branding
from app.monthly_report_ui import _field
render_branding(_field)
''', default_timeout=30).run()
    assert not app.exception
    assert any("could not be read" in w.value for w in app.warning)
    assert app.get("file_uploader")
    app.text_input("report_branding_actor").set_value("Synthetic Reviewer").run()
    app.selectbox("report_branding_history").set_value(1).run()
    next(c for c in app.checkbox if c.label == "Restore this collection as a new shared version").check().run()
    app.button("report_branding_restore").click().run()
    assert not app.exception
    restored = branding.load_branding()
    assert restored.revision == 3 and restored.logos == initial.logos
    assert branding.load_branding(2) == current
    assert (branding._path() / "assets" / logos[1].asset).read_bytes() == damaged_bytes
    app.run()
    assert not app.exception and branding.load_branding() == restored


def test_shared_logo_admin_is_reachable_in_existing_administration_routes(logos):
    seed_legacy(logos)
    from app.monthly_report_admin_ui import admin_url
    assert admin_url("logos") == "?workflow=monthly&monthly_admin=logos"
    app = AppTest.from_string('''
from app.monthly_report_admin_ui import render_administration, render_administration_links
from app.monthly_report_ui import _field
render_administration_links()
render_administration('logos', _field, mode='live')
''', default_timeout=30).run()
    assert not app.exception
    assert any(h.value == "Shared contract logos" for h in app.subheader)
    assert app.get("file_uploader")
    assert any(b.label == "Restore logo collection" for b in app.button)


def test_card_fallback_does_not_swallow_storage_isolation_failure(logos, monkeypatch):
    from app.monthly_report_start_ui import _logo
    _, state = seed_legacy(logos)
    def forbidden(logo):
        raise library.LibraryError("Test report path is outside its isolated storage")
    monkeypatch.setattr(branding, "read_logo", forbidden)
    with pytest.raises(library.LibraryError, match="outside its isolated storage"):
        _logo("Damaged Contract", state, {})


@pytest.mark.parametrize("mode", ["isolated", "fixtures"])
def test_logo_administration_uses_the_requested_test_namespace(logos, monkeypatch, mode):
    from app.memory import _data_dir
    from app.monthly_report_testing import isolated
    from app.monthly_report_ui import shared_fixture_run_token
    from app import monthly_report_branding_ui
    live = _data_dir()
    seen = []
    monkeypatch.setattr(monthly_report_branding_ui, "render_branding", lambda field: seen.append(_data_dir()))
    app = AppTest.from_string('''
from app.monthly_report_ui import render_monthly_report_workflow
render_monthly_report_workflow('a' * 32)
''', default_timeout=30)
    app.query_params.update({"monthly_qa": mode, "monthly_admin": "logos"})
    app.run()
    assert not app.exception
    token = shared_fixture_run_token('a' * 32) if mode == "fixtures" else 'a' * 32
    with isolated(token):
        expected = _data_dir()
    assert seen == [expected] and expected != live
