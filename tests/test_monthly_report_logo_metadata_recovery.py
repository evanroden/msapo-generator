"""A PNG metadata decoder refusal must leave logo selection/recovery usable."""

from dataclasses import asdict, replace
from io import BytesIO

from PIL import Image, PngImagePlugin
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding
from app import monthly_report_directory as directory
from app import monthly_report_library as library


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def png(kind="zTXt", *, excessive=False, size=(12, 8)):
    info = PngImagePlugin.PngInfo()
    text = "x" * (PngImagePlugin.MAX_TEXT_CHUNK + 1) if excessive else "Synthetic logo description."
    if kind == "zTXt":
        info.add_text("Description", text, zip=True)
    else:
        info.add_itxt("Description", text, zip=True)
    output = BytesIO()
    Image.new("RGBA", size, (30, 80, 120, 180)).save(output, "PNG", pnginfo=info)
    return output.getvalue()


def logo(key, raw):
    return branding.BrandLogo(
        key, key.title() + " client", (key.title() + " Contract",),
        library.asset_reference(raw, "png"), "https://example.invalid/source",
        "https://example.invalid/logo.png", "2026-10-28",
    )


def saved_healthy():
    raw = png()
    healthy = logo("healthy", raw)
    state = branding.save_branding((healthy,), {healthy.asset: raw}, expected_revision=0,
                                  actor="Synthetic Reviewer", confirmed=True)
    return state, raw


def saved_unreadable(kind):
    first, healthy_raw = saved_healthy()
    bad_raw = png(kind, excessive=True)
    damaged = logo("damaged", bad_raw)
    # Model an existing unreadable catalog record, not an accepted new upload.
    # Current save validation must still refuse this image in its separate test.
    current = replace(first, revision=2, logos=(damaged, *first.logos))
    encoded = library._json({"schema": 1, **asdict(current)})
    path = branding._path()
    library._atomic_write(path / "manifest.json", encoded)
    library._atomic_write(path / "history" / "00000002.json", encoded)
    library._atomic_write(path / "assets" / damaged.asset, bad_raw)
    return first, current, healthy_raw, bad_raw


@pytest.mark.parametrize("kind", ("zTXt", "iTXt"))
def test_actual_png_metadata_limit_is_a_scoped_artwork_error(kind):
    raw = png(kind, excessive=True)
    assert len(raw) < 5000
    with pytest.raises(ValueError, match="Decompressed data too large"):
        Image.open(BytesIO(raw))
    with pytest.raises(branding.LogoArtworkError, match="A logo image could not be read") as rejected:
        branding._image(raw, library.asset_reference(raw, "png"))
    assert type(rejected.value.__cause__) is ValueError
    assert "MAX_TEXT_CHUNK" not in str(rejected.value)


@pytest.mark.parametrize("kind", ("zTXt", "iTXt"))
def test_valid_small_metadata_stays_readable_and_exact_in_shared_storage(kind):
    raw = png(kind)
    healthy = logo("healthy", raw)
    saved = branding.save_branding((healthy,), {healthy.asset: raw}, expected_revision=0,
                                  actor="Synthetic Reviewer", confirmed=True)
    assert branding.load_branding() == saved
    assert branding.read_logo(healthy) == raw
    with Image.open(BytesIO(branding.read_logo(healthy))) as image:
        image.load()
        assert image.size == (12, 8) and image.info["Description"] == "Synthetic logo description."


def test_dimension_validation_retains_its_specific_guidance():
    raw = png(size=(2401, 8))
    with pytest.raises(branding.LogoArtworkError) as rejected:
        branding._image(raw, library.asset_reference(raw, "png"))
    assert str(rejected.value) == "Logos must be PNG images no larger than 2400 × 1600 pixels."


def test_rejected_shared_save_preserves_current_history_and_original_artwork():
    first, healthy_raw = saved_healthy()
    path = branding._path()
    manifest = (path / "manifest.json").read_bytes()
    history = (path / "history" / "00000001.json").read_bytes()
    bad_raw = png("iTXt", excessive=True)
    damaged = logo("damaged", bad_raw)
    with pytest.raises(branding.LogoArtworkError, match="could not be read"):
        branding.save_branding((damaged, *first.logos), {damaged.asset: bad_raw},
                              expected_revision=1, actor="Synthetic Reviewer", confirmed=True)
    assert branding.load_branding() == first
    assert (path / "manifest.json").read_bytes() == manifest
    assert (path / "history" / "00000001.json").read_bytes() == history
    assert not (path / "history" / "00000002.json").exists()
    assert not (path / "assets" / damaged.asset).exists()
    assert branding.read_logo(first.logos[0]) == healthy_raw


def test_unreadable_metadata_keeps_healthy_and_affected_contracts_selectable():
    first, current, healthy_raw, bad_raw = saved_unreadable("zTXt")
    for name in ("Healthy Contract", "Damaged Contract"):
        directory.save_directory(name, (directory.DirectorySite("synthetic", "Synthetic Site"),),
                                 expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    app = AppTest.from_string('''
from app.monthly_report_start_ui import choose_contract
from app.monthly_report_ui import _field
choose_contract('', _field)
''', default_timeout=30).run()
    assert not app.exception
    assert any("could not be read" in item.value for item in app.warning)
    next(button for button in app.button if button.label == "Healthy client").click().run()
    assert not app.exception and app.session_state["report_contract"] == "Healthy Contract"
    next(button for button in app.button if button.label == "Change contract").click().run()
    next(button for button in app.button if button.label == "Damaged client").click().run()
    assert not app.exception and app.session_state["report_contract"] == "Damaged Contract"
    assert any("could not be read" in item.value for item in app.warning)
    assert branding.load_branding() == current and branding.load_branding(1) == first
    assert branding.read_logo(first.logos[0]) == healthy_raw
    assert (branding._path() / "assets" / current.logos[0].asset).read_bytes() == bad_raw


def test_admin_can_restore_readable_history_without_rewriting_bad_metadata():
    first, current, healthy_raw, bad_raw = saved_unreadable("iTXt")
    path = branding._path()
    old_histories = tuple((path / "history" / f"{revision:08d}.json").read_bytes() for revision in (1, 2))
    app = AppTest.from_string('''
from app.monthly_report_branding_ui import render_branding
from app.monthly_report_ui import _field
render_branding(_field)
''', default_timeout=30).run()
    assert not app.exception and app.get("file_uploader")
    assert any("could not be read" in item.value for item in app.warning)
    app.text_input("report_branding_actor").set_value("Synthetic Reviewer").run()
    app.selectbox("report_branding_history").set_value(1).run()
    next(item for item in app.checkbox if item.label == "Restore this collection as a new shared version").check().run()
    app.button("report_branding_restore").click().run()
    assert not app.exception
    restored = branding.load_branding()
    assert restored.revision == 3 and restored.action == "restore:1" and restored.logos == first.logos
    assert branding.load_branding(2) == current
    assert tuple((path / "history" / f"{revision:08d}.json").read_bytes() for revision in (1, 2)) == old_histories
    assert (path / "assets" / current.logos[0].asset).read_bytes() == bad_raw
    assert branding.read_logo(first.logos[0]) == healthy_raw
    app.run()
    assert not app.exception and branding.load_branding() == restored
