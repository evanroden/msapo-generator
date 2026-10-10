"""The site picker acknowledges changes and report setup shows progress."""
from contextlib import contextmanager
from io import BytesIO

from PIL import Image

from app import monthly_report_branding as branding
from app import monthly_report_start_ui as start_ui
from app.contracts import RRH_CONTRACT
from app import monthly_report_library as library
from test_monthly_report_ui import monthly


def _sites(app):
    return [w for w in app.checkbox
            if w.key and w.key.startswith("report_sites_") and w.label != "This is a regional report"]


def test_each_site_checkbox_produces_a_visible_current_selection(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    options = _sites(app)
    assert len(options) >= 2
    first = options[0].label
    options[0].check().run()
    assert not app.exception
    assert next(w for w in _sites(app) if w.label == first).value
    assert any(f"Sites selected (1): {first}" in note.value for note in app.caption)
    app.run()
    assert next(w for w in _sites(app) if w.label == first).value
    second = next(w for w in _sites(app) if w.label != first)
    second.check().run()
    assert not app.exception
    assert next(w for w in _sites(app) if w.label == first).value
    assert next(w for w in _sites(app) if w.label == second.label).value
    assert any("Sites selected (2):" in note.value for note in app.caption)


def _new_report(app):
    next(w for w in _sites(app)).check().run()
    template = next((b for b in app.button if b.label == "Use ENFRA template"), None)
    if template:
        template.click().run()
    next(w for w in app.text_input if w.label == "Your name").set_value("Synthetic Start Editor").run()
    return app


def test_start_reports_spinner_and_persists_one_profile(monkeypatch, tmp_path):
    app = _new_report(monthly(monkeypatch, tmp_path, saved=False))
    events = []
    original = start_ui.st.spinner

    @contextmanager
    def capture(label, *args, **kwargs):
        events.append(("begin", label))
        with original(label, *args, **kwargs):
            yield
        events.append(("end", label))

    monkeypatch.setattr(start_ui.st, "spinner", capture)
    next(b for b in app.button if b.label == "Start this report").click().run()
    assert not app.exception
    assert any("Preparing this report" in event[1] for event in events if event[0] == "begin")
    assert [event[0] for event in events if "Preparing this report" in event[1]] == ["begin", "end"]
    assert len(library.list_profiles(RRH_CONTRACT)) == 1
    assert not any(b.label == "Start this report" for b in app.button)


def test_failed_start_clears_pending_state_and_can_be_retried(monkeypatch, tmp_path):
    app = _new_report(monthly(monkeypatch, tmp_path, saved=False))

    def fail(*args, **kwargs):
        raise ValueError("Synthetic input failed validation.")

    monkeypatch.setattr(start_ui, "save_design_start", fail)
    next(b for b in app.button if b.label == "Start this report").click().run()
    assert not app.exception
    assert any("Synthetic input failed validation" in e.value for e in app.error)
    retry = next(b for b in app.button if b.label == "Start this report")
    assert not retry.disabled
    assert not any(key.startswith("report_start_pending_") for key in app.session_state.filtered_state)
    assert not library.list_profiles(RRH_CONTRACT)


def test_logo_card_cache_reuses_only_image_canvas(monkeypatch):
    branding.card_image.clear()
    picture = BytesIO()
    Image.new("RGB", (307, 81), (180, 130, 80)).save(picture, format="PNG")
    raw = picture.getvalue()
    called = []
    original = branding.ImageOps.contain

    def record(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(branding.ImageOps, "contain", record)
    first = branding.card_image(raw)
    second = branding.card_image(raw)
    assert first == second and len(called) == 1
    with Image.open(BytesIO(first)) as result:
        assert result.size == (480, 192)
    branding.card_image.clear()
